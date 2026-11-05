"""Locked recovery routing and the resource-owning original-binding transaction."""

from sqlalchemy.exc import IntegrityError

from app.core.settings import Settings
from app.domains.billing.readback_binding import begin_first_binding
from app.domains.billing.readback_contracts import (
    OriginalCreateReadbackSubject,
    OriginalCreateProof,
    ReadbackApplyResult,
    BoundReadbackSubject,
)
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.operator_contracts import ReviewResolution, OriginalOperationProof
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.domains.purchases.contracts import (
    Purchase,
    FinancialOperation,
    PreparedSubscriptionObservation,
    PurchaseRefused,
)
from app.domains.purchases.financial_binding import bind_financial_in_transaction
from app.infrastructure.queries import purchases
from app.infrastructure.queries.billing_customers import open_customer_reviews
from app.models import ExternalCreateOperationState as State
from app.domains.billing.readback import _verify_subject, _verify_bound, _lock_purchase
from app.domains.billing.work import enroll_subscription
from app.domains.billing.contracts import BillingRefused
from app.infrastructure.queries import billing_reconciliation


def recovery_route(
    factory: SessionFactory, configuration: Settings, purchase: Purchase, expected: FinancialOperation
) -> tuple[bool, bool]:
    """Return original GET permission and canonical presence under business locks."""
    with factory() as db:
        _, _, operations = _lock_purchase(db, configuration, purchase)
        op = next(op for op in operations if op.create_operation_id == expected.id)
        if service._operation(db, op).admission_snapshot() != expected.admission_snapshot():
            raise PurchaseRefused("purchase_pending", 409)
        billing_reconciliation.scope(db, purchase.user_id, purchase.accepted.selection.product_id)
        canonical = purchases.linked_subscription(db, purchase.id) is not None
        allowed = op.operation_state in {State.BOUND, State.POSSIBLE_SEND, State.UNKNOWN}
        if canonical and op.bound_external_object_id is not None:
            allowed = True  # Negative readback can restrict while genuine review stays open.
        elif op.operation_state == State.MANUAL_REVIEW:
            cases = open_customer_reviews(db, op.create_operation_id)
            allowed = bool(cases) and all(
                case.reason_code == "external_create_outcome_unknown:" + op.operation_kind.value for case in cases
            )
            if not allowed:
                raise PurchaseRefused("purchase_review_required", 409)
        return allowed, canonical


def bind_original_readback(
    factory: SessionFactory,
    configuration: Settings,
    subject: OriginalCreateReadbackSubject,
    proof: OriginalCreateProof,
    observation: PreparedSubscriptionObservation,
    *,
    work_claim: WorkClaim | None = None,
    resolution: ReviewResolution | None = None,
    resolution_proof: OriginalOperationProof | None = None,
) -> ReadbackApplyResult:
    try:
        with factory() as db:
            context = begin_first_binding(
                db, configuration, subject, proof, resolution=resolution, resolution_proof=resolution_proof
            )
            outcome = bind_financial_in_transaction(
                db,
                subject.purchase,
                subject.operation,
                int(proof.provider_subscription_id),
                observation=observation,
                work_claim=work_claim,
                first_binding=context,
            )
            db.commit()
            return outcome
    except IntegrityError:
        # The failed binding/audit unit is closed before a separate restricting
        # conflict transition. An operator refusal preserves its open review.
        if resolution is None:
            from app.domains.purchases.financial import financial_pending

            financial_pending(factory, subject.purchase, subject.operation, conflict=True, work_claim=work_claim)
        raise PurchaseRefused("purchase_review_required", 409) from None


def ensure_bound_enrollment(factory: SessionFactory, configuration: Settings, subject: BoundReadbackSubject) -> None:
    with factory() as db:
        _, operations = _verify_subject(db, configuration, subject)
        billing_reconciliation.scope(db, subject.purchase.user_id, subject.purchase.accepted.selection.product_id)
        sub = purchases.linked_subscription(db, subject.purchase.id)
        if sub is None or sub.subscription_id != subject.subscription_id:
            raise BillingRefused("subscription_provenance_changed", 409)
        _verify_bound(subject, sub, operations)
        enroll_subscription(db, sub)
        db.commit()
