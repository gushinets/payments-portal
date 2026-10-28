"""Shared authoritative reconciliation: short claim/apply, no provider I/O."""

from dataclasses import asdict
from datetime import timedelta
from uuid import UUID, uuid4

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.customers import lock_user, mark_customer_identity_conflict
from app.domains.billing.reconciliation_contracts import (
    RECONCILIATION_SCHEMA,
    CommercialProof,
    IdentityProof,
    ReconciliationSubject,
    SubscriptionProof,
)
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.infrastructure.queries import billing_reconciliation as queries, purchases
from app.infrastructure.queries.billing_customers import lock_customer, customer_operation, open_customer_reviews
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    ManualReviewCase,
    PurchaseIntentState,
)

SOURCE_TRUST = timedelta(hours=6)
APPLY_SAFETY_SECONDS = 30


def claim_reconciliation(
    factory: SessionFactory, configuration: Settings, subscription_id: UUID, *, io_timeout_seconds: float
) -> ReconciliationSubject:
    if not 0 < io_timeout_seconds <= 600:
        raise ValueError("invalid reconciliation I/O budget")
    with factory() as db:
        initial = queries.subscription(db, subscription_id)
        if initial is None or initial.purchase_intent_id is None:
            raise BillingRefused("subscription_provenance_unproven", 409)
        user = lock_user(db, initial.user_id)
        if (user.tenant_id, user.region) != (configuration.instance_tenant_id, configuration.instance_region):
            raise BillingRefused("subscription_not_found", 404)
        customer = lock_customer(db, initial.customer_id)
        customer_op = customer_operation(db, customer.customer_id)
        row = purchases.owned(db, user.id, initial.purchase_intent_id, lock=True)
        if row is None:
            raise BillingRefused("subscription_provenance_unproven", 409)
        held = purchases.hold(db, user.id, row.product_id)
        if held is None or held.purchase_intent_id != row.purchase_intent_id:
            raise BillingRefused("purchase_scope_released", 409)
        operations = purchases.operations(db, row.purchase_intent_id, lock=True)
        evidence = service.accepted(row)
        service._verify_original_consent(db, row, evidence)
        purchase = service._snapshot(db, row)
        agreement = next((op for op in operations if op.operation_kind == Kind.AGREEMENT), None)
        subscription_op = next((op for op in operations if op.operation_kind == Kind.SUBSCRIPTION), None)
        if (
            customer.binding_state != Binding.BOUND
            or not customer.provider_customer_id
            or customer_op is None
            or customer_op.operation_state != State.BOUND
            or customer_op.bound_external_object_id != customer.provider_customer_id
            or customer_op.request_correlation_key != customer.billing_customer_key
            or customer.provider_origin != evidence.provider_origin
            or evidence.provider_origin != configuration.lbx_provider_origin
            or row.external_billing_account_id != configuration.lbx_external_billing_account_id
            or agreement is None
            or not agreement.bound_external_object_id
            or subscription_op is None
            or not subscription_op.bound_external_object_id
        ):
            raise BillingRefused("subscription_provenance_unproven", 409)
        for provider_id in (
            customer.provider_customer_id,
            agreement.bound_external_object_id,
            subscription_op.bound_external_object_id,
        ):
            if (
                not provider_id.isascii()
                or not provider_id.isdecimal()
                or len(provider_id) > 20
                or not 0 < int(provider_id) < 10**20
                or str(int(provider_id)) != provider_id
            ):
                raise BillingRefused("subscription_provenance_unproven", 409)
        scope = queries.scope(db, user.id, row.product_id)
        if scope is None:
            scope = BillingProductAccessScope(user_id=user.id, product_id=row.product_id, primary_subscription_id=None)
            db.add(scope)
            db.flush()
        current = queries.subscription(db, subscription_id, lock=True)
        if (
            (
                current.customer_id,
                current.user_id,
                current.product_id,
                current.mapping_revision_id,
                current.external_billing_account_id,
                current.purchase_intent_id,
            )
            != (
                row.customer_id,
                row.user_id,
                row.product_id,
                row.mapping_revision_id,
                row.external_billing_account_id,
                row.purchase_intent_id,
            )
            or current.external_subscription_id != subscription_op.bound_external_object_id
            or current.external_agreement_id != agreement.bound_external_object_id
        ):
            raise BillingRefused("subscription_provenance_unproven", 409)
        now = as_utc(queries.database_now(db))
        if current.reconciliation_lease_expires_at and as_utc(current.reconciliation_lease_expires_at) > now:
            raise BillingRefused("subscription_reconciliation_busy", 409)
        current.reconciliation_lease_owner = str(uuid4())
        current.reconciliation_lease_expires_at = now + timedelta(seconds=io_timeout_seconds + APPLY_SAFETY_SECONDS)
        current.reconciliation_fencing_token += 1
        result = ReconciliationSubject(
            current.subscription_id,
            purchase,
            CustomerOpen(
                customer.customer_id,
                customer_op.create_operation_id,
                customer_op.send_fence,
                customer.billing_customer_key,
                customer.provider_customer_id,
            ),
            current.external_agreement_id,
            agreement.request_correlation_key,
            current.external_subscription_id,
            current.reconciliation_lease_owner,
            current.reconciliation_fencing_token,
            current.reconciliation_lease_expires_at,
            now,
        )
        db.commit()
        return result


def apply_reconciliation(factory: SessionFactory, subject: ReconciliationSubject, proof: SubscriptionProof) -> UUID:
    """Recheck permanent provenance and current fences before any fact changes."""
    with factory() as db:
        purchase = subject.purchase
        lock_user(db, purchase.user_id)
        customer = lock_customer(db, purchase.customer_id)
        customer_op = customer_operation(db, customer.customer_id)
        row = service._locked(db, purchase)
        operations = purchases.operations(db, purchase.id, lock=True)
        scope = queries.scope(db, purchase.user_id, purchase.accepted.selection.product_id)
        current = queries.subscription(db, subject.subscription_id, lock=True)
        now = as_utc(queries.database_now(db))
        if (
            current is None
            or scope is None
            or current.reconciliation_lease_owner != subject.owner
            or current.reconciliation_fencing_token != subject.fence
            or current.reconciliation_lease_expires_at is None
            or as_utc(current.reconciliation_lease_expires_at) <= now
            or proof.read_started_at > proof.read_finished_at
            or proof.read_started_at < subject.claimed_at
            or proof.read_finished_at > now
            or proof.read_finished_at >= subject.lease_expires_at
        ):
            raise BillingRefused("subscription_reconciliation_stale", 409)
        if (
            current.purchase_intent_id != purchase.id
            or current.user_id != purchase.user_id
            or current.product_id != purchase.accepted.selection.product_id
            or current.customer_id != purchase.customer_id
            or current.mapping_revision_id != purchase.accepted.meaning.revision_id
            or current.external_billing_account_id != purchase.account_id
            or current.external_subscription_id != subject.provider_subscription_id
            or current.external_agreement_id != subject.agreement_id
            or service.accepted(row) != purchase.accepted
            or customer.binding_state != Binding.BOUND
            or customer.provider_customer_id != subject.customer.provider_id
            or customer.billing_customer_key != subject.customer.outer_key
            or customer.provider_origin != purchase.accepted.provider_origin
            or customer_op is None
            or customer_op.create_operation_id != subject.customer.operation_id
            or customer_op.request_correlation_key != subject.customer.outer_key
            or customer_op.send_fence != subject.customer.fence
            or customer_op.operation_state != State.BOUND
            or customer_op.bound_external_object_id != subject.customer.provider_id
            or {
                (op.create_operation_id, op.operation_kind, op.request_correlation_key, op.bound_external_object_id)
                for op in operations
            }
            != {(op.id, op.kind, op.key, op.bound_id) for op in purchase.operations}
        ):
            raise BillingRefused("subscription_provenance_changed", 409)
        service._verify_original_consent(db, row, purchase.accepted)
        reviews = queries.open_reviews(db, current.subscription_id)
        known_review = (
            row.state == PurchaseIntentState.MANUAL_REVIEW
            or bool(reviews)
            or any(
                op.operation_state == State.MANUAL_REVIEW or open_customer_reviews(db, op.create_operation_id)
                for op in operations
            )
        )
        conflict = None
        customer_conflict = "customer_identity_conflict" in proof.reasons
        if customer_conflict:
            mark_customer_identity_conflict(db, customer, customer_op)
        if proof.identity == IdentityProof.CONFLICT and (
            not customer_conflict or "subscription_identity_conflict" in proof.reasons
        ):
            conflict = "subscription_identity_conflict"
        elif current.lifecycle_status == Lifecycle.ENDED and proof.lifecycle not in {None, Lifecycle.ENDED}:
            conflict = "subscription_terminal_revival_conflict"
        elif proof.identity == IdentityProof.MATCH and proof.commercial == CommercialProof.MISMATCH:
            conflict = "subscription_commercial_mismatch"
        document = asdict(proof)
        document["read_started_at"] = proof.read_started_at.isoformat()
        document["read_finished_at"] = proof.read_finished_at.isoformat()
        document["provenance"] = {
            "purchase_intent_id": str(purchase.id),
            "mapping_revision_id": str(purchase.accepted.meaning.revision_id),
            "accepted_fingerprint": purchase.accepted.offer.fingerprint,
            "legal_document_version_ids": [str(doc.document_version_id) for doc in purchase.accepted.documents],
            "provider_origin": purchase.accepted.provider_origin,
            "provider_subscription_id": subject.provider_subscription_id,
            "agreement_id": subject.agreement_id,
            "fence": subject.fence,
        }
        observation = BillingStateObservation(
            observation_kind=BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ,
            external_billing_account_id=purchase.account_id,
            user_id=purchase.user_id,
            product_id=current.product_id,
            access_scope_id=scope.access_scope_id,
            subscription_id=current.subscription_id,
            observed_at=proof.read_finished_at,
            evidence_schema_version=RECONCILIATION_SCHEMA,
            evidence_document=document,
            completeness_classification="complete" if proof.complete else "incomplete",
            result_classification=conflict
            or (
                "customer_identity_conflict"
                if customer_conflict
                else "review_required"
                if known_review
                else proof.commercial.value
            ),
            resulting_access_revision=None,
        )
        db.add(observation)
        db.flush()
        if conflict:
            row.state = PurchaseIntentState.MANUAL_REVIEW
            row.state_updated_at = now
            if not any(case.reason_code == conflict for case in reviews):
                db.add(
                    ManualReviewCase(
                        reason_code=conflict,
                        scope_kind="subscription",
                        scope_reference=str(current.subscription_id),
                        evidence_schema_version=RECONCILIATION_SCHEMA,
                        evidence_document={"observation_id": str(observation.observation_id)},
                        case_state="open",
                    )
                )
        if (
            proof.identity == IdentityProof.MATCH
            and proof.financial == Financial.BLOCKED
            and current.lifecycle_status != Lifecycle.ENDED
        ):
            current.lifecycle_status = proof.lifecycle
        if conflict or known_review or customer_conflict:
            current.commercial_access_status = Commercial.INELIGIBLE
            current.financial_access_status = Financial.BLOCKED
            if conflict or customer_conflict or proof.complete:
                current.latest_observation_id = observation.observation_id
        elif proof.financial == Financial.BLOCKED:
            current.lifecycle_status = proof.lifecycle
            current.financial_access_status = Financial.BLOCKED
            current.latest_observation_id = observation.observation_id
        if proof.complete and not conflict and not known_review:
            current.lifecycle_status = proof.lifecycle
            current.financial_access_status = proof.financial
            current.commercial_access_status = Commercial.ELIGIBLE
            current.last_authoritative_read_at = proof.read_started_at
            current.projection_valid_until = proof.read_started_at + SOURCE_TRUST
            current.latest_observation_id = observation.observation_id
        # Incomplete attempts append evidence, preserving finite LKG support.
        # A negative with incomplete commercial proof reduces usability above,
        # but never renews trust. No paid-access writer runs in this step.
        current.reconciliation_lease_owner = None
        current.reconciliation_lease_expires_at = None
        db.commit()
        return observation.observation_id
