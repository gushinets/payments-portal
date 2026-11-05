"""Financial claims retain identity; only fenced proven-not-sent attempts may resume."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.customer_reviews import customer_admission_reviews
from app.domains.billing.customers import authenticate, lock_customer, lock_user
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.contracts import (
    FINANCIAL_HINT_SCHEMA,
    FinancialOperation,
    FinancialRequestDocument,
    FinancialFailureFacts,
    PreparedSubscriptionObservation,
    Purchase,
    PurchaseRefused,
)
from app.domains.purchases.service import _locked, _operation, read_purchase
from app.domains.purchases.financial_binding import bind_financial_in_transaction
from app.domains.purchases.financial_reviews import record_review as _review
from app.infrastructure.queries import purchases as queries
from app.infrastructure.queries.billing_customers import (
    customer_operation,
    recovery_work,
)
from app.infrastructure.queries import billing_reconciliation
from app.domains.billing.work import enroll_subscription
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.operator_contracts import OriginalOperationProof, ReviewResolution
from app.models import (
    BillingWorkItem,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    PurchaseIntentState as IntentState,
)

RECOVERY_WINDOW = timedelta(hours=2)
MAX_FINANCIAL_RECOVERY_BATCH = 100


def claim_financial(
    factory: SessionFactory,
    purchase: Purchase,
    expected: FinancialOperation,
    request_document: FinancialRequestDocument,
    *,
    configuration: Settings,
    token: str,
) -> FinancialOperation:
    with factory() as db:
        if authenticate(db, configuration, token).id != purchase.user_id:
            raise PurchaseRefused("purchase_not_found", 404)
        row = _locked(db, purchase)
        operations = queries.operations(db, row.purchase_intent_id, lock=True)
        operation = next(op for op in operations if op.create_operation_id == expected.id)
        if (
            row.state == IntentState.MANUAL_REVIEW
            or operation.operation_state not in {State.PENDING, State.PROVEN_NOT_SENT}
            or operation.send_fence != expected.fence
            or operation.bound_external_object_id is not None
        ):
            return _operation(db, operation)
        retry_unsent = operation.operation_state == State.PROVEN_NOT_SENT
        if not retry_unsent and operation.unknown_since is not None:
            return _operation(db, operation)
        # Serialize customer conflicts arriving during source I/O with the new possible-send claim.
        customer = lock_customer(db, row.customer_id)
        customer_create = customer_operation(db, customer.customer_id)
        if customer_create is None:
            raise PurchaseRefused("billing_identity_unproven", 409)
        customer_admission_reviews(db, customer, customer_create)
        work = recovery_work(db, operation.create_operation_id)
        if retry_unsent and (
            operation.unknown_since is None
            or operation.recovery_hint_schema_version != FINANCIAL_HINT_SCHEMA
            or not isinstance(operation.recovery_hint_document, dict)
            or operation.recovery_hint_document.get("request") != request_document
            or work is None
            or work.payload_document.get("candidate_id") is not None
        ):
            raise PurchaseRefused("purchase_history_unproven", 409)
        if operation.operation_kind == Kind.SUBSCRIPTION and not any(
            op.operation_kind == Kind.AGREEMENT and op.operation_state == State.BOUND for op in operations
        ):
            raise PurchaseRefused("purchase_pending", 409)
        now = utc_now()
        operation.send_fence = uuid4()
        operation.operation_state = State.POSSIBLE_SEND
        if not retry_unsent:
            operation.unknown_since = now
            operation.unknown_recovery_deadline_at = now + RECOVERY_WINDOW
            operation.recovery_hint_schema_version = FINANCIAL_HINT_SCHEMA
            operation.recovery_hint_document = {
                "request": request_document,
                "purchase_intent_id": str(purchase.id),
                "accepted_fingerprint": purchase.accepted.offer.fingerprint,
            }
        if work is None:
            work = BillingWorkItem(
                work_kind="external_create_recovery",
                scope_kind="create_operation",
                scope_reference=str(operation.create_operation_id),
                coalescing_key=str(operation.create_operation_id),
                payload_schema_version="financial-recovery:v1",
                payload_document={
                    "purchase_intent_id": str(purchase.id),
                    "create_operation_id": str(operation.create_operation_id),
                },
                next_attempt_at=now + RECOVERY_WINDOW,
                active_recovery_deadline_at=now + RECOVERY_WINDOW,
                work_state="pending",
                attempt_count=1,
            )
            db.add(work)
        else:
            work.work_state = "pending"
            work.active_recovery_deadline_at = now + RECOVERY_WINDOW
            work.next_attempt_at = work.active_recovery_deadline_at
            work.attempt_count += 1
        from app.domains.billing.background_recovery import enroll_operation

        db.flush()
        enroll_operation(db, operation, row.external_billing_account_id, sent=True)
        row.state = IntentState.PREPARING
        row.state_updated_at = now
        db.flush()
        result = _operation(db, operation, may_send=True)
        db.commit()
        return result


def proven_not_sent(factory: SessionFactory, purchase: Purchase, expected: FinancialOperation) -> None:
    """Only a completed typed no-send result, never a GET or expiry, permits resume."""
    with factory() as db:
        row = _locked(db, purchase)
        op = next(op for op in queries.operations(db, purchase.id, lock=True) if op.create_operation_id == expected.id)
        work = recovery_work(db, op.create_operation_id)
        if (
            not expected.may_send
            or expected.fence is None
            or op.send_fence != expected.fence
            or op.operation_state not in {State.POSSIBLE_SEND, State.UNKNOWN}
            or op.bound_external_object_id is not None
            or op.unknown_since is None
            or op.recovery_hint_schema_version != FINANCIAL_HINT_SCHEMA
            or work is None
            or work.payload_document.get("candidate_id") is not None
            or row.state == IntentState.MANUAL_REVIEW
        ):
            return
        op.operation_state = State.PROVEN_NOT_SENT
        op.send_fence = uuid4()
        work.work_state = "done"
        work.payload_document = {
            **work.payload_document,
            "last_failure": {"code": "lbx_create_not_sent", "reason": "network"},
        }
        row.state = IntentState.PREPARING
        row.state_updated_at = utc_now()
        db.commit()


def record_receipt(factory: SessionFactory, purchase: Purchase, expected: FinancialOperation, provider_id: int) -> None:
    if type(provider_id) is not int or not 0 < provider_id < 10**20:
        raise ValueError("invalid provider receipt")
    with factory() as db:
        _locked(db, purchase)
        op = next(op for op in queries.operations(db, purchase.id, lock=True) if op.create_operation_id == expected.id)
        if (
            op.send_fence != expected.fence
            or not expected.may_send
            or op.operation_state not in {State.POSSIBLE_SEND, State.UNKNOWN}
        ):
            raise PurchaseRefused("purchase_pending", 409)
        work = recovery_work(db, op.create_operation_id)
        if work is None or work.payload_document.get("candidate_id") not in {None, str(provider_id)}:
            raise PurchaseRefused("purchase_review_required", 409)
        work.payload_document = {**work.payload_document, "candidate_id": str(provider_id)}
        db.commit()


def financial_pending(
    factory: SessionFactory,
    purchase: Purchase,
    expected: FinancialOperation,
    *,
    conflict: bool = False,
    failure_facts: FinancialFailureFacts | None = None,
    work_claim: WorkClaim | None = None,
) -> None:
    with factory() as db:
        lock_user(db, purchase.user_id)
        lock_customer(db, purchase.customer_id)
        customer_operation(db, purchase.customer_id)
        row = _locked(db, purchase)
        op = next(op for op in queries.operations(db, purchase.id, lock=True) if op.create_operation_id == expected.id)
        # Acquire the affected business row before an optional work-claim lock.
        billing_reconciliation.scope(db, purchase.user_id, purchase.accepted.selection.product_id)
        subscription = queries.linked_subscription(db, purchase.id)
        if work_claim is not None:
            from app.domains.billing.work import verify_operation_claim

            verify_operation_claim(db, work_claim, expected.id)
        if op.send_fence != expected.fence:
            return  # A stale failure cannot demote a newer proven result.
        work = recovery_work(db, op.create_operation_id)
        deadline = queries.financial_recovery_deadline(op, work)
        if conflict:
            _review(db, row, op, "financial_binding_conflict")
            if subscription is not None:
                # A known conflict withdraws usability in this transaction;
                # retain the last source proof, trust timestamps and bindings.
                subscription.commercial_access_status = Commercial.INELIGIBLE
                subscription.financial_access_status = Financial.BLOCKED
                enroll_subscription(db, subscription, hint=True)
        elif op.operation_state == State.PROVEN_NOT_SENT:
            return  # A failed GET cannot erase completed no-send evidence.
        elif op.operation_state != State.BOUND:
            if deadline and utc_now() >= as_utc(deadline):
                _review(db, row, op, "external_create_outcome_unknown:" + op.operation_kind.value)
            elif op.operation_state != State.MANUAL_REVIEW:
                op.operation_state = State.UNKNOWN if op.unknown_since else State.PENDING
                row.state = IntentState.AWAITING_EXTERNAL_RESULT
                row.state_updated_at = utc_now()
        elif row.state not in {IntentState.MANUAL_REVIEW, IntentState.LINKED}:
            # Keep proven preparation LINKED across incomplete reads. Each
            # payment opening still requires complete fresh point proof.
            row.state = IntentState.AWAITING_EXTERNAL_RESULT
            row.state_updated_at = utc_now()
        if op.bound_external_object_id is not None and subscription is not None and not conflict:
            enroll_subscription(db, subscription, hint=True)
        if work and failure_facts:
            work.payload_document = {**work.payload_document, "last_failure": failure_facts}
        db.commit()


def changed_unsent_terms(factory: SessionFactory, purchase: Purchase) -> None:
    with factory() as db:
        row = _locked(db, purchase)
        operations = queries.operations(db, purchase.id, lock=True)
        # Source I/O used this frozen snapshot. A later send, receipt or binding
        # invalidates its decision; the caller reloads the current purchase.
        if (
            row.state == IntentState.LINKED
            or row.state != purchase.state
            or tuple(_operation(db, op) for op in operations) != purchase.operations
        ):
            return
        if any(
            op.operation_state not in {State.PENDING, State.PROVEN_NOT_SENT} or op.bound_external_object_id
            for op in operations
        ):
            target = next(op for op in operations if op.operation_kind == Kind.SUBSCRIPTION)
            _review(db, row, target, "accepted_terms_changed_after_preparation")
        else:
            row.state = IntentState.FAILED_BEFORE_EXTERNAL_EFFECT
            row.resolved_at = utc_now()
            row.state_updated_at = utc_now()
            db.delete(queries.hold(db, row.user_id, row.product_id))
        db.commit()


def _bind_financial(
    factory: SessionFactory,
    purchase: Purchase,
    expected: FinancialOperation,
    provider_id: int,
    *,
    observation: PreparedSubscriptionObservation | None = None,
    work_claim: WorkClaim | None = None,
    resolution: ReviewResolution | None = None,
    resolution_proof: OriginalOperationProof | None = None,
) -> None:
    with factory() as db:
        bind_financial_in_transaction(
            db,
            purchase,
            expected,
            provider_id,
            observation=observation,
            work_claim=work_claim,
            resolution=resolution,
            resolution_proof=resolution_proof,
        )
        db.commit()


def bind_financial(
    factory: SessionFactory,
    purchase: Purchase,
    expected: FinancialOperation,
    provider_id: int,
    *,
    observation: PreparedSubscriptionObservation | None = None,
    work_claim: WorkClaim | None = None,
    resolution: ReviewResolution | None = None,
    resolution_proof: OriginalOperationProof | None = None,
) -> None:
    if type(provider_id) is not int or not 0 < provider_id < 10**20:
        raise ValueError("invalid financial provider identity")
    try:
        _bind_financial(
            factory,
            purchase,
            expected,
            provider_id,
            observation=observation,
            work_claim=work_claim,
            resolution=resolution,
            resolution_proof=resolution_proof,
        )
    except IntegrityError:
        if resolution is not None:
            raise PurchaseRefused("purchase_review_required", 409) from None
        # The failed unit has closed/rolled back before recording the conflict.
        financial_pending(factory, purchase, expected, conflict=True, work_claim=work_claim)
        raise PurchaseRefused("purchase_review_required", 409) from None


def escalate_overdue_financial(
    factory: SessionFactory, *, now: datetime | None = None, limit: int = MAX_FINANCIAL_RECOVERY_BATCH
) -> int:
    if not 1 <= limit <= MAX_FINANCIAL_RECOVERY_BATCH:
        raise ValueError("invalid recovery batch limit")
    instant = now or utc_now()
    with factory() as db:
        candidates = queries.overdue_financial(db, instant, limit)
    count = 0
    for user_id, purchase_id in candidates:
        purchase = read_purchase(factory, user_id, purchase_id)
        for op in purchase.operations:
            if count >= limit:
                return count
            if op.state in {State.POSSIBLE_SEND, State.UNKNOWN} and op.deadline and as_utc(op.deadline) <= instant:
                with factory() as db:
                    row = _locked(db, purchase)
                    current = next(
                        item
                        for item in queries.operations(db, purchase.id, lock=True)
                        if item.create_operation_id == op.id
                    )
                    deadline = queries.financial_recovery_deadline(
                        current, recovery_work(db, current.create_operation_id)
                    )
                    if (
                        deadline
                        and as_utc(deadline) <= instant
                        and current.send_fence == op.fence
                        and current.operation_state
                        in {
                            State.POSSIBLE_SEND,
                            State.UNKNOWN,
                        }
                    ):
                        _review(db, row, current, "external_create_outcome_unknown:" + current.operation_kind.value)
                        db.commit()
                        count += 1
    return count
