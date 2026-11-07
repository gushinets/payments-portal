"""Initial subscription facts only, inside the original financial bind transaction."""

from dataclasses import asdict
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domains.billing.operator_contracts import OriginalOperationProof
from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof
from app.domains.billing.work import enroll_subscription
from app.infrastructure.queries.billing_reconciliation import scope as access_scope
from app.domains.purchases.contracts import PreparedSubscriptionObservation, PurchaseRefused
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    PurchaseIntent,
    PurchaseIntentState as IntentState,
)


def record_first_binding(
    db: Session,
    row: PurchaseIntent,
    op: ExternalCreateOperation,
    operations: list[ExternalCreateOperation],
    provider_id: int,
    observation: PreparedSubscriptionObservation | None,
    proof: OriginalOperationProof,
) -> ExternalSubscription | None:
    sub = None
    if op.operation_kind == Kind.SUBSCRIPTION:
        agreement = next(item for item in operations if item.operation_kind == Kind.AGREEMENT)
        original = proof.subscription
        if (
            agreement.operation_state != State.BOUND
            or observation is None
            or original is None
            or original.identity != IdentityProof.MATCH
            or original.commercial != CommercialProof.MATCH
            or original.lifecycle is None
            or not proof.read_started_at
            <= original.read_started_at
            <= original.read_finished_at
            <= proof.read_finished_at
        ):
            raise PurchaseRefused("purchase_history_unproven", 409)
        sub = ExternalSubscription(
            subscription_id=uuid4(),
            external_billing_account_id=row.external_billing_account_id,
            customer_id=row.customer_id,
            user_id=row.user_id,
            product_id=row.product_id,
            purchase_intent_id=row.purchase_intent_id,
            mapping_revision_id=row.mapping_revision_id,
            external_subscription_id=str(provider_id),
            external_agreement_id=agreement.bound_external_object_id,
            lifecycle_status=original.lifecycle,
            financial_access_status=Financial.BLOCKED
            if original.financial == Financial.BLOCKED
            else Financial.UNVERIFIED,
            commercial_access_status=Commercial.ELIGIBLE,
            last_authoritative_read_at=proof.read_started_at,
            projection_valid_until=proof.read_started_at,
        )
        db.add(sub)
        db.flush()
        row.state = IntentState.LINKED
        row.state_updated_at = proof.read_finished_at
    if sub is not None or proof.agreement_close_date is not None:
        document = asdict(observation) if observation else {"agreement_id": str(provider_id)}
        document["original_proof"] = {
            "request_digest": proof.request_digest,
            "read_started_at": proof.read_started_at.isoformat(),
            "read_finished_at": proof.read_finished_at.isoformat(),
            "agreement_close_date": proof.agreement_close_date,
            "subscription": {
                **asdict(proof.subscription),
                "read_started_at": proof.subscription.read_started_at.isoformat(),
                "read_finished_at": proof.subscription.read_finished_at.isoformat(),
            }
            if proof.subscription
            else None,
        }
        scope = None
        if sub is None:
            scope = access_scope(db, row.user_id, row.product_id)
            if scope is None:
                scope = BillingProductAccessScope(user_id=row.user_id, product_id=row.product_id)
                db.add(scope)
                db.flush()
        evidence = BillingStateObservation(
            observation_kind=BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ
            if sub
            else BillingStateObservationKind.TARGET_PRODUCT_DISCOVERY,
            external_billing_account_id=row.external_billing_account_id,
            user_id=row.user_id,
            product_id=row.product_id,
            subscription_id=sub.subscription_id if sub else None,
            access_scope_id=scope.access_scope_id if scope else None,
            purchase_intent_id=row.purchase_intent_id if scope else None,
            observed_at=proof.read_finished_at,
            evidence_schema_version="prepared-subscription:v1" if sub else "prepared-agreement:v1",
            evidence_document=document,
            completeness_classification="preparation_only",
            result_classification="source_negative"
            if proof.agreement_close_date or (proof.subscription and proof.subscription.financial == Financial.BLOCKED)
            else "not_paid_verified",
        )
        db.add(evidence)
        db.flush()
        if sub is not None:
            sub.latest_observation_id = evidence.observation_id
            enroll_subscription(db, sub)
    return sub
