"""Financial claims retain identity; only fenced proven-not-sent attempts may resume."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domains.purchases.inventory_contracts import InventoryResult

from datetime import timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.customer_reviews import customer_admission_reviews
from app.domains.billing.customers import authenticate, lock_customer
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
from app.domains.purchases.financial_reviews import record_financial_review, review_identity_conflict
from app.domains.purchases.preparation import record_first_binding
from app.domains.purchases.recovery_evidence import (
    require_current_customer,
    binding_identity_matches,
    same_send,
    retained_points,
    saved_request,
    settle_point_conflict,
)
from app.domains.purchases.service import _locked, _operation, _verify_original_consent
from app.infrastructure.queries import purchases as queries
from app.infrastructure.queries.billing_customers import (
    customer_operation,
    recovery_work,
    open_customer_reviews,
)
from app.infrastructure.queries.billing_reconciliation import database_now
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.operator_contracts import OriginalOperationProof, ReviewResolution
from app.models import (
    BillingWorkItem,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    PurchaseIntentState as IntentState,
)

RECOVERY_WINDOW = timedelta(hours=2)


def claim_financial(
    factory: SessionFactory,
    purchase: Purchase,
    expected: FinancialOperation,
    request_document: FinancialRequestDocument,
    *,
    configuration: Settings,
    token: str,
    inventory: "InventoryResult | None" = None,
) -> FinancialOperation:
    with factory() as db:
        if authenticate(db, configuration, token).id != purchase.user_id:
            raise PurchaseRefused("purchase_not_found", 404)
        row = _locked(db, purchase)
        from app.domains.purchases.inventory import require_financial_admission

        require_financial_admission(db, purchase, inventory)
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
            or retained_points(db, operation) is not None
        ):
            raise PurchaseRefused("purchase_history_unproven", 409)
        if operation.operation_kind == Kind.SUBSCRIPTION and any(
            op.operation_kind == Kind.AGREEMENT
            and op.bound_external_object_id
            and queries.closed_original_agreement(db, purchase.id, op.bound_external_object_id)
            for op in operations
        ):
            raise PurchaseRefused("purchase_not_prepared", 409)
        if operation.operation_kind == Kind.SUBSCRIPTION and not any(
            op.operation_kind == Kind.AGREEMENT and op.operation_state == State.BOUND for op in operations
        ):
            raise PurchaseRefused("purchase_pending", 409)
        now = as_utc(database_now(db))
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
            or retained_points(db, op) is not None
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


def record_receipt(factory: SessionFactory, purchase: Purchase, expected: FinancialOperation, provider_id: int) -> bool:
    """Store the receipt candidate, or return False if that object is already bound."""
    if type(provider_id) is not int or not 0 < provider_id < 10**20:
        raise ValueError("invalid provider receipt")
    candidate_id = str(provider_id)
    with factory() as db:
        _locked(db, purchase)
        op = next(op for op in queries.operations(db, purchase.id, lock=True) if op.create_operation_id == expected.id)
        if expected.may_send and op.operation_state == State.BOUND and op.bound_external_object_id == candidate_id:
            return False
        if (
            op.send_fence != expected.fence
            or not expected.may_send
            or op.operation_state not in {State.POSSIBLE_SEND, State.UNKNOWN}
        ):
            raise PurchaseRefused("purchase_pending", 409)
        work = recovery_work(db, op.create_operation_id)
        if work is None or work.payload_document.get("candidate_id") not in {None, candidate_id}:
            raise PurchaseRefused("purchase_review_required", 409)
        work.payload_document = {**work.payload_document, "candidate_id": candidate_id}
        db.commit()
        return True


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
        row = _locked(db, purchase)
        op = next(op for op in queries.operations(db, purchase.id, lock=True) if op.create_operation_id == expected.id)
        if op.send_fence != expected.fence:
            return  # A stale failure cannot demote a newer proven result.
        work = recovery_work(db, op.create_operation_id)
        deadline = queries.financial_recovery_deadline(op, work)
        if conflict:
            record_financial_review(db, row, op, "financial_binding_conflict")
        elif op.operation_state == State.PROVEN_NOT_SENT:
            return  # A failed GET cannot erase completed no-send evidence.
        elif op.operation_state != State.BOUND:
            if deadline and as_utc(database_now(db)) >= as_utc(deadline):
                record_financial_review(db, row, op, "external_create_outcome_unknown:" + op.operation_kind.value)
            elif op.operation_state != State.MANUAL_REVIEW:
                op.operation_state = State.UNKNOWN if op.unknown_since else State.PENDING
                row.state = IntentState.AWAITING_EXTERNAL_RESULT
                row.state_updated_at = utc_now()
        elif row.state not in {IntentState.MANUAL_REVIEW, IntentState.LINKED}:
            # Keep proven preparation LINKED across incomplete reads. Each
            # payment opening still requires complete fresh point proof.
            row.state = IntentState.AWAITING_EXTERNAL_RESULT
            row.state_updated_at = utc_now()
        if work and op.operation_state == State.BOUND:
            work.work_state = "pending"
            work.next_attempt_at = utc_now()
        if work and failure_facts:
            work.payload_document = {**work.payload_document, "last_failure": failure_facts}
        from app.domains.billing.paid_access import reduce_paid_access

        reduce_paid_access(db, row.user_id)
        if work_claim is not None:
            from app.domains.billing.work import verify_operation_claim

            verify_operation_claim(db, work_claim, expected.id)
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
            record_financial_review(db, row, target, "accepted_terms_changed_after_preparation")
        else:
            row.state = IntentState.FAILED_BEFORE_EXTERNAL_EFFECT
            row.resolved_at = utc_now()
            row.state_updated_at = utc_now()
            db.delete(queries.hold(db, row.user_id, row.product_id))
        from app.domains.billing.paid_access import reduce_paid_access

        reduce_paid_access(db, row.user_id)
        db.commit()


def _original_request(operation: ExternalCreateOperation, purchase: Purchase) -> FinancialRequestDocument:
    if operation.operation_state not in {State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW}:
        raise PurchaseRefused("purchase_history_unproven", 409)
    return saved_request(operation, purchase)


def original_request(
    factory: SessionFactory,
    purchase: Purchase,
    expected: FinancialOperation,
    command: FinancialRequestDocument,
    *,
    resolution: ReviewResolution | None = None,
) -> bool:
    """Reject unproved history before discovery; recheck it at the actual bind."""
    with factory() as db:
        _locked(db, purchase)
        operation = next(
            op for op in queries.operations(db, purchase.id, lock=True) if op.create_operation_id == expected.id
        )
        if operation.bound_external_object_id is not None:
            if resolution is not None:
                raise PurchaseRefused("billing_review_stale", 409)
            return False
        if operation.send_fence != expected.fence:
            raise PurchaseRefused("billing_review_stale" if resolution is not None else "purchase_pending", 409)
        if _original_request(operation, purchase) != command:
            raise PurchaseRefused("purchase_history_unproven", 409)
        if resolution is None and any(
            case.reason_code != "external_create_outcome_unknown:" + operation.operation_kind.value
            for case in open_customer_reviews(db, operation.create_operation_id)
        ):
            raise PurchaseRefused("purchase_review_required", 409)
        return True


def _bind_financial(
    factory: SessionFactory,
    purchase: Purchase,
    expected: FinancialOperation,
    provider_id: int,
    *,
    proof: OriginalOperationProof,
    observation: PreparedSubscriptionObservation | None = None,
    work_claim: WorkClaim | None = None,
    resolution: ReviewResolution | None = None,
) -> bool:
    from app.domains.billing.operator_review import digest

    with factory() as db:
        row = _locked(db, purchase)
        _verify_original_consent(db, row, purchase.accepted)
        operations = queries.operations(db, purchase.id, lock=True)
        op = next(op for op in operations if op.create_operation_id == expected.id)
        if op.bound_external_object_id is not None:
            if resolution is not None:
                raise PurchaseRefused("billing_review_stale", 409)
            if op.bound_external_object_id == str(provider_id):
                return False  # The matching binder won; use canonical reconciliation.
            if not same_send(db, op, expected, _operation(db, op)):
                raise PurchaseRefused("purchase_pending", 409)
        elif op.send_fence != expected.fence:
            raise PurchaseRefused("billing_review_stale" if resolution is not None else "purchase_pending", 409)
        request = (
            saved_request(op, purchase) if op.bound_external_object_id is not None else _original_request(op, purchase)
        )
        if proof.request_digest != digest(request):
            raise PurchaseRefused("purchase_history_unproven", 409)
        now = as_utc(database_now(db))
        if (
            proof.read_started_at < as_utc(op.unknown_since)
            or not proof.read_started_at <= proof.read_finished_at <= now
        ):
            raise PurchaseRefused("purchase_history_unproven", 409)
        account = require_current_customer(db, row, purchase, proof.customer)
        if work_claim is not None:
            from app.domains.billing.background_recovery import pause_expired_recovery
            from app.domains.billing.work import verify_operation_claim

            verify_operation_claim(db, work_claim, expected.id)
            if pause_expired_recovery(db, op, account):
                db.commit()
                raise PurchaseRefused("billing_work_stale", 409)
        if not binding_identity_matches(db, op, expected, str(provider_id), proof, operator=resolution is not None):
            if resolution is None:
                review_identity_conflict(db, row, op)
                db.commit()
            raise PurchaseRefused("purchase_review_required", 409)
        existing = queries.linked_subscription(db, purchase.id)
        if existing is not None:
            raise PurchaseRefused("purchase_review_required", 409)
        resolved_case = None
        if resolution is not None:
            from app.domains.billing.operator_review import authorize_original_binding

            resolved_case = authorize_original_binding(db, resolution, proof, row, operations, existing, expected)
        elif any(
            case.reason_code != "external_create_outcome_unknown:" + op.operation_kind.value
            for case in open_customer_reviews(db, op.create_operation_id)
        ):
            raise PurchaseRefused("purchase_review_required", 409)
        op.send_fence = uuid4()
        op.bound_external_object_id = str(provider_id)
        op.operation_state = State.BOUND
        op.resolved_at = now
        work = recovery_work(db, op.create_operation_id)
        if work is not None and resolution is not None:
            settle_point_conflict(work, op, str(provider_id))
        if work and (work_claim is not None or work.work_state != "running"):
            if work_claim is not None:
                from app.domains.billing.work import finish

                finish(db, work, work_claim, due=None)
            else:
                work.work_state = "done"
        for case in open_customer_reviews(db, op.create_operation_id):
            if case.reason_code == "external_create_outcome_unknown:" + op.operation_kind.value:
                case.case_state = "resolved"
                case.resolved_at = now
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
            row.state_updated_at = now
        sub = record_first_binding(db, row, op, operations, provider_id, observation, proof)
        if resolved_case is not None:
            from app.domains.billing.operator_review import audit_original_binding

            audit_original_binding(db, resolved_case, operations, sub, proof=proof)
        db.commit()
        return True


def bind_financial(
    factory: SessionFactory,
    purchase: Purchase,
    expected: FinancialOperation,
    provider_id: int,
    *,
    proof: OriginalOperationProof,
    observation: PreparedSubscriptionObservation | None = None,
    work_claim: WorkClaim | None = None,
    resolution: ReviewResolution | None = None,
) -> bool:
    if type(provider_id) is not int or not 0 < provider_id < 10**20:
        raise ValueError("invalid financial provider identity")
    try:
        return _bind_financial(
            factory,
            purchase,
            expected,
            provider_id,
            proof=proof,
            observation=observation,
            work_claim=work_claim,
            resolution=resolution,
        )
    except IntegrityError:
        if resolution is not None:
            raise PurchaseRefused("purchase_review_required", 409) from None
        financial_pending(factory, purchase, expected, conflict=True, work_claim=work_claim)
        raise PurchaseRefused("purchase_review_required", 409) from None
