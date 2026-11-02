"""Apply persisted target discovery using original locked reconciliation facts."""

from dataclasses import asdict
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.domains.billing.contracts import BillingRefused
from app.domains.billing.discovery import DISCOVERY_SCHEMA, ProductDiscovery
from app.domains.billing.paid_access import apply_paid_source
from app.domains.billing.reconciliation_contracts import RECONCILIATION_SCHEMA
from app.domains.billing.reconciliation_facts import apply_source_facts, source_conflict
from app.domains.billing.customers import mark_customer_identity_conflict
from app.domains.billing.work_contracts import WorkClaim
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.infrastructure.queries import billing_reconciliation, paid_access, purchases, billing_customers
from app.models import (
    BillingStateObservation,
    BillingStateObservationKind,
    User,
    PurchaseIntentState,
    ManualReviewCase,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperationState as OperationState,
)


def apply_discoveries(
    db: Session,
    user: User,
    claim: WorkClaim,
    identities: tuple[UUID, ...],
    now: datetime,
    *,
    skew_seconds: int | None,
    conflicted_purchases: frozenset[UUID] = frozenset(),
) -> tuple[BillingStateObservation, ...]:
    causes = []
    observations = [paid_access.discovery(db, identity) for identity in identities]
    if any(observation is None for observation in observations):
        raise BillingRefused("billing_work_stale", 409)
    for cause in sorted(
        observations, key=lambda observation: (observation.product_id or "", str(observation.purchase_intent_id))
    ):
        identity = cause.observation_id
        if cause.user_id != user.id or cause.evidence_schema_version != DISCOVERY_SCHEMA:
            raise BillingRefused("billing_work_stale", 409)
        if (
            cause.evidence_document["generation"] != claim.generation
            or cause.work_item_id != claim.id
            or UUID(cause.evidence_document["customer_id"]) != UUID(claim.reference)
            or as_utc(cause.observed_at) < claim.started_at
            or as_utc(cause.observed_at) >= claim.expires_at
        ):
            raise BillingRefused("billing_work_stale", 409)
        customer = billing_customers.lock_customer(db, UUID(claim.reference))
        customer_op = billing_customers.customer_operation(db, customer.customer_id)
        document = cause.evidence_document
        if (
            customer_op is None
            or customer_op.operation_state != OperationState.BOUND
            or customer.binding_state != Binding.BOUND
            or str(customer_op.send_fence) != document["customer_fence"]
            or customer.provider_customer_id != document["provider_customer_id"]
            or customer_op.bound_external_object_id != customer.provider_customer_id
            or customer.provider_origin != document["provider_origin"]
        ):
            raise BillingRefused("billing_work_stale", 409)
        row = purchases.owned(db, user.id, cause.purchase_intent_id, lock=True)
        if row is None:
            raise BillingRefused("billing_work_stale", 409)
        snapshot = service._snapshot(db, row)
        service._locked(db, snapshot)
        operations = purchases.operations(db, row.purchase_intent_id, lock=True)
        service._verify_original_consent(db, row, snapshot.accepted)
        scope = billing_reconciliation.scope(db, user.id, row.product_id)
        subscription = purchases.linked_subscription(db, row.purchase_intent_id)
        if scope is None or subscription is None:
            continue
        if (
            document["accepted_fingerprint"] != snapshot.accepted.offer.fingerprint
            or document["provider_origin"] != snapshot.accepted.provider_origin
            or document["operations"] != [[str(op.id), str(op.fence), op.bound_id] for op in snapshot.operations]
        ):
            raise BillingRefused("billing_work_stale", 409)
        observed = ProductDiscovery.model_validate({key: document[key] for key in ProductDiscovery.model_fields})
        proof = observed.linked_proof
        if proof is None:
            continue
        if (
            proof.read_started_at < claim.started_at
            or proof.read_started_at > proof.read_finished_at
            or proof.read_finished_at > as_utc(cause.observed_at)
            or proof.read_finished_at > now
        ):
            raise BillingRefused("billing_work_stale", 409)
        latest = (
            paid_access.discovery(db, subscription.latest_observation_id)
            if subscription.latest_observation_id
            else None
        )
        if latest and as_utc(latest.observed_at) > proof.read_started_at:
            continue  # Newer authority won while discovery was in flight.
        known_review = (
            row.state == PurchaseIntentState.MANUAL_REVIEW
            or bool(billing_reconciliation.open_reviews(db, subscription.subscription_id))
            or any(
                op.operation_state == OperationState.MANUAL_REVIEW
                or billing_customers.open_customer_reviews(db, op.create_operation_id)
                for op in operations
            )
        )
        known_review = known_review or (
            snapshot.id in conflicted_purchases and scope.primary_subscription_id != subscription.subscription_id
        )
        conflict = source_conflict(subscription, proof)
        customer_conflict = "customer_identity_conflict" in proof.reasons
        if customer_conflict:
            mark_customer_identity_conflict(db, customer, customer_op)
        if conflict:
            row.state = PurchaseIntentState.MANUAL_REVIEW
            row.state_updated_at = now
            if not any(
                case.reason_code == conflict
                for case in billing_reconciliation.open_reviews(db, subscription.subscription_id)
            ):
                db.add(
                    ManualReviewCase(
                        reason_code=conflict,
                        scope_kind="subscription",
                        scope_reference=str(subscription.subscription_id),
                        evidence_schema_version=DISCOVERY_SCHEMA,
                        evidence_document={"observation_id": str(identity)},
                        case_state="open",
                    )
                )
        proof_document = asdict(proof)
        proof_document["read_started_at"] = proof.read_started_at.isoformat()
        proof_document["read_finished_at"] = proof.read_finished_at.isoformat()
        proof_document["cycle"] = proof.cycle.model_dump(mode="json") if proof.cycle else None
        authoritative = BillingStateObservation(
            observation_kind=BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ,
            external_billing_account_id=subscription.external_billing_account_id,
            user_id=user.id,
            product_id=subscription.product_id,
            subscription_id=subscription.subscription_id,
            access_scope_id=cause.access_scope_id,
            basis_observation_id=cause.observation_id,
            observed_at=proof.read_finished_at,
            evidence_schema_version=RECONCILIATION_SCHEMA,
            evidence_document=proof_document,
            completeness_classification="complete" if proof.complete else "incomplete",
            result_classification=conflict or ("review_required" if known_review else proof.commercial.value),
        )
        db.add(authoritative)
        db.flush()
        apply_source_facts(
            subscription,
            proof,
            authoritative,
            conflict=bool(conflict),
            known_review=known_review,
            customer_conflict=customer_conflict,
        )
        apply_paid_source(
            db,
            scope,
            subscription,
            snapshot,
            proof,
            authoritative,
            now,
            skew_seconds=skew_seconds,
            discovery_id=identity,
            generation=claim.generation,
            review=bool(known_review or conflict or customer_conflict),
        )
        causes.extend((cause, authoritative))
    return tuple(causes)
