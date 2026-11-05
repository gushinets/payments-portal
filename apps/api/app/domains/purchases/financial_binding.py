"""Caller-transaction financial binding/history writer, including validated first binding."""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING
from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domains.billing.work import enroll_subscription
from app.domains.purchases.contracts import (
    FINANCIAL_HINT_SCHEMA,
    Purchase,
    FinancialOperation,
    PreparedSubscriptionObservation,
    PurchaseRefused,
)
from app.domains.purchases.service import _locked
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.operator_contracts import OriginalOperationProof, ReviewResolution
from app.infrastructure.queries import purchases as queries
from app.infrastructure.queries.billing_customers import recovery_work, open_customer_reviews
from app.infrastructure.queries.billing_reconciliation import open_reviews
from app.models import (
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalSubscription,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    PurchaseIntentState as IntentState,
)

if TYPE_CHECKING:
    from app.domains.billing.readback_binding import FirstBindingContext
    from app.domains.billing.readback_contracts import ReadbackApplyResult


def bind_financial_in_transaction(
    db: Session,
    purchase: Purchase,
    expected: FinancialOperation,
    provider_id: int,
    *,
    observation: PreparedSubscriptionObservation | None = None,
    work_claim: WorkClaim | None = None,
    resolution: ReviewResolution | None = None,
    resolution_proof: OriginalOperationProof | None = None,
    first_binding: FirstBindingContext | None = None,
) -> ReadbackApplyResult | None:
    if first_binding is not None and (
        first_binding.db is not db
        or first_binding.transaction is not db.get_transaction()
        or first_binding.subject.purchase.id != purchase.id
        or first_binding.subject.operation.id != expected.id
        or first_binding.proof.provider_subscription_id != str(provider_id)
    ):
        raise PurchaseRefused("purchase_history_unproven", 409)
    row = _locked(db, purchase)
    operations = queries.operations(db, purchase.id, lock=True)
    existing = queries.linked_subscription(db, purchase.id)
    if first_binding is not None and existing is not first_binding.subscription:
        raise PurchaseRefused("purchase_history_unproven", 409)
    resolved_case = first_binding.authorized_case if first_binding else None
    if first_binding is not None:
        resolution_proof = first_binding.resolution_proof
    if resolution is not None:
        from app.domains.billing.operator_review import authorize_original_binding

        resolved_case = authorize_original_binding(
            db, resolution, resolution_proof, row, operations, existing, expected
        )
    if existing is not None and open_reviews(db, existing.subscription_id):
        raise PurchaseRefused("purchase_review_required", 409)
    op = next(op for op in operations if op.create_operation_id == expected.id)
    if work_claim is not None:
        from app.domains.billing.work import verify_operation_claim

        verify_operation_claim(db, work_claim, expected.id)
    if op.send_fence != expected.fence:
        raise PurchaseRefused("purchase_pending", 409)
    if (
        op.operation_state in {State.PENDING, State.PROVEN_NOT_SENT}
        or op.unknown_since is None
        or op.recovery_hint_schema_version != FINANCIAL_HINT_SCHEMA
    ):
        raise PurchaseRefused("purchase_history_unproven", 409)
    if op.bound_external_object_id not in {None, str(provider_id)}:
        raise PurchaseRefused("purchase_review_required", 409)
    if op.operation_state == State.MANUAL_REVIEW and row.state == IntentState.MANUAL_REVIEW:
        # Deadline escalation can recover; a known mismatch needs an audited decision.
        if any(
            case.reason_code != "external_create_outcome_unknown:" + op.operation_kind.value
            for case in open_customer_reviews(db, op.create_operation_id)
        ):
            raise PurchaseRefused("purchase_review_required", 409)
    if op.operation_state != State.BOUND:  # Re-observation preserves healthy Widget fences.
        op.send_fence = uuid4()
    op.bound_external_object_id = str(provider_id)
    op.operation_state = State.BOUND
    op.resolved_at = op.resolved_at or utc_now()
    work = recovery_work(db, op.create_operation_id)
    if work:
        if work_claim is not None:
            from app.domains.billing.work import finish

            finish(db, work, work_claim, due=None)
        elif work.work_state != "running":
            work.work_state = "done"
    for case in open_customer_reviews(db, op.create_operation_id):
        if case.reason_code == "external_create_outcome_unknown:" + op.operation_kind.value:
            case.case_state = "resolved"
            case.resolved_at = utc_now()
            case.resolved_by_principal = "system:financial-point-read"
            case.resolution_schema_version = "financial-resolution:v1"
            case.resolution_document = {
                "create_operation_id": str(op.create_operation_id),
                "proof": "original_point_read",
            }
    if row.state == IntentState.MANUAL_REVIEW and not any(
        item.operation_state == State.MANUAL_REVIEW for item in operations
    ):
        row.state = IntentState.PREPARING
        row.state_updated_at = utc_now()
    if op.operation_kind == Kind.SUBSCRIPTION:
        agreement = next(item for item in operations if item.operation_kind == Kind.AGREEMENT)
        if agreement.operation_state != State.BOUND or not observation:
            raise PurchaseRefused("purchase_pending", 409)
        now = utc_now()
        sub = queries.linked_subscription(db, purchase.id)
        new_subscription = sub is None
        if sub is None:
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
                lifecycle_status=Lifecycle.ACTIVE if observation.state == 2 else Lifecycle.INACTIVE,
                financial_access_status=Financial.UNVERIFIED,
                commercial_access_status=Commercial.ELIGIBLE,
                last_authoritative_read_at=now,
                projection_valid_until=now,
            )
            db.add(sub)
            db.flush()
        if (
            sub.external_subscription_id != str(provider_id)
            or sub.external_agreement_id != agreement.bound_external_object_id
        ):
            raise PurchaseRefused("purchase_review_required", 409)
        evidence = BillingStateObservation(
            observation_kind=BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ,
            external_billing_account_id=row.external_billing_account_id,
            user_id=row.user_id,
            product_id=row.product_id,
            subscription_id=sub.subscription_id,
            observed_at=now,
            evidence_schema_version="financial-terminal:v1" if observation.terminal else "prepared-subscription:v1",
            evidence_document=asdict(observation),
            completeness_classification="original_terms_only" if observation.terminal else "preparation_only",
            result_classification="terminal_not_paid" if observation.terminal else "not_paid_verified",
        )
        db.add(evidence)
        db.flush()
        # Any reconciliation claim marks this subscription as monitored.
        # Preparation cannot replace its lifecycle, financial status, supporting observation or trust.
        if sub.reconciliation_fencing_token == 0:
            sub.lifecycle_status = Lifecycle.ACTIVE if observation.state == 2 else Lifecycle.INACTIVE
            sub.latest_observation_id = evidence.observation_id
        if new_subscription or observation.terminal:
            enroll_subscription(db, sub, hint=observation.terminal)
        # No paid trust extension, financial eligibility, access scope, grant or allowance.
        row.state = IntentState.LINKED
        row.state_updated_at = now
    outcome = None
    if first_binding is not None:
        from app.domains.billing.readback_binding import apply_first_binding_negative

        outcome = apply_first_binding_negative(db, first_binding)
    if resolved_case is not None:
        from app.domains.billing.operator_review import audit_original_binding

        sub = queries.linked_subscription(db, purchase.id)
        resolved_case.resolution_document = {**resolved_case.resolution_document, "readback_outcome": outcome}
        audit_original_binding(db, resolved_case, operations, sub, proof=resolution_proof)
    db.flush()
    return outcome
