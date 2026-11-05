"""Validated first-CREATE context; canonical creation and negative share the caller transaction."""

from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy.orm import Session, SessionTransaction

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.operator_contracts import ReviewResolution, OriginalOperationProof
from app.domains.billing.readback_contracts import (
    OriginalCreateReadbackSubject,
    OriginalCreateProof,
    ReadbackApplyResult,
    ReadbackRecheck,
)
from app.domains.billing.readback import _verify_subject, _scope, _verify_negative, _window_valid, _write_negative
from app.domains.billing.work import enroll_subscription
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.contracts import FINANCIAL_HINT_SCHEMA, PurchaseRefused
from app.infrastructure.queries import purchases, billing_reconciliation as queries
from app.infrastructure.queries.billing_customers import open_customer_reviews
from app.models import (
    ExternalSubscription,
    ManualReviewCase,
    ExternalCreateOperationState as State,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)


@dataclass(frozen=True)
class FirstBindingContext:
    """Only minted after original witnesses and absence were checked under locks."""

    db: Session
    transaction: SessionTransaction
    subject: OriginalCreateReadbackSubject
    proof: OriginalCreateProof
    subscription: ExternalSubscription
    authorized_case: ManualReviewCase | None = None
    resolution_proof: OriginalOperationProof | None = None


def begin_first_binding(
    db: Session,
    configuration: Settings,
    subject: OriginalCreateReadbackSubject,
    proof: OriginalCreateProof,
    *,
    resolution: ReviewResolution | None = None,
    resolution_proof: OriginalOperationProof | None = None,
) -> FirstBindingContext:
    if resolution is not None:
        from app.domains.billing.customers import lock_user, lock_customer
        from app.domains.billing.operator_inventory import lock_inventory

        lock_user(db, subject.purchase.user_id)
        lock_customer(db, subject.purchase.customer_id)
        lock_inventory(db, resolution)
    row, operations = _verify_subject(db, configuration, subject)
    queries.scope(db, row.user_id, row.product_id)
    if purchases.linked_subscription(db, row.purchase_intent_id) is not None:
        raise ReadbackRecheck()
    op = next(op for op in operations if op.create_operation_id == subject.operation.id)
    operation_matches = service._operation(db, op).admission_snapshot() == subject.operation.admission_snapshot()
    if resolution is not None and not operation_matches:
        raise PurchaseRefused("billing_review_stale", 409)
    now = as_utc(queries.database_now(db))
    if (
        not operation_matches
        or op.unknown_since is None
        or as_utc(op.unknown_since) != subject.original_send_at
        or op.unknown_recovery_deadline_at is None
        or as_utc(op.unknown_recovery_deadline_at) != subject.original_deadline
        or op.recovery_hint_schema_version != FINANCIAL_HINT_SCHEMA
        or op.recovery_hint_document.get("request") != subject.saved_command
        or op.recovery_hint_document.get("purchase_intent_id") != str(subject.purchase.id)
        or op.recovery_hint_document.get("accepted_fingerprint") != subject.purchase.accepted.offer.fingerprint
        or op.send_fence is None
        or op.operation_state not in {State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW}
        or (
            proof.negative is not None
            and (
                proof.negative.read_started_at != proof.read_started_at
                or proof.negative.read_finished_at != proof.read_finished_at
                or proof.negative.provider_subscription_id != proof.provider_subscription_id
            )
        )
        or proof.command != subject.saved_command
        or proof.agreement_id != subject.agreement_id
        or subject.operation.candidate_id not in {None, proof.provider_subscription_id}
        or not subject.captured_at <= proof.read_started_at <= proof.read_finished_at <= now < subject.deadline
        or not {"customer", "agreement", "subscription", "unique_candidate", "effective_terms"}.issubset(proof.reads)
        or (
            resolution is None
            and any(
                case.reason_code != "external_create_outcome_unknown:subscription"
                for case in open_customer_reviews(db, op.create_operation_id)
            )
        )
    ):
        raise BillingRefused("purchase_history_unproven", 409)
    authorized_case = None
    if resolution is not None:
        from app.domains.billing.operator_review import authorize_original_binding

        authorized_case = authorize_original_binding(
            db, resolution, resolution_proof, row, operations, None, subject.operation
        )
    sub = ExternalSubscription(
        subscription_id=uuid4(),
        external_billing_account_id=row.external_billing_account_id,
        customer_id=row.customer_id,
        user_id=row.user_id,
        product_id=row.product_id,
        purchase_intent_id=row.purchase_intent_id,
        mapping_revision_id=row.mapping_revision_id,
        external_subscription_id=proof.provider_subscription_id,
        external_agreement_id=proof.agreement_id,
        lifecycle_status=Lifecycle.INACTIVE,
        financial_access_status=Financial.UNVERIFIED,
        commercial_access_status=Commercial.ELIGIBLE,
        last_authoritative_read_at=now,
        projection_valid_until=now,
    )
    _scope(db, sub)
    db.add(sub)
    db.flush()
    return FirstBindingContext(db, db.get_transaction(), subject, proof, sub, authorized_case, resolution_proof)


def apply_first_binding_negative(db: Session, context: FirstBindingContext) -> ReadbackApplyResult:
    """Binding/history are caller-owned outputs in this same validated unit."""
    sub, subject = context.subscription, context.subject
    if db is not context.db or db.get_transaction() is not context.transaction or sub not in db:
        raise BillingRefused("subscription_provenance_changed", 409)
    operations = purchases.operations(db, subject.purchase.id, lock=True)
    op = next(op for op in operations if op.create_operation_id == subject.operation.id)
    if op.operation_state != State.BOUND or op.bound_external_object_id != context.proof.provider_subscription_id:
        raise BillingRefused("purchase_history_unproven", 409)
    negative = context.proof.negative
    if negative is None:
        enroll_subscription(db, sub)
        return ReadbackApplyResult.HINT_ONLY
    _verify_negative(subject, sub, negative)
    if not _window_valid(subject, negative, as_utc(queries.database_now(db))):
        enroll_subscription(db, sub, hint=True)
        return ReadbackApplyResult.HINT_ONLY
    _write_negative(db, subject, sub, negative)
    return ReadbackApplyResult.APPLIED_NEGATIVE
