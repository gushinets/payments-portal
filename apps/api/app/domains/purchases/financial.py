"""Financial claims retain identity; only fenced proven-not-sent attempts may resume."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.customers import authenticate
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.contracts import (
    FinancialOperation,
    FinancialRequestDocument,
    FinancialFailureFacts,
    PreparedSubscriptionObservation,
    Purchase,
    PurchaseRefused,
)
from app.domains.purchases.service import _locked, _operation, read_purchase
from app.infrastructure.queries import purchases as queries
from app.infrastructure.queries.billing_reconciliation import open_reviews
from app.infrastructure.queries.billing_customers import recovery_work, open_customer_reviews
from app.domains.billing.work import enroll_subscription
from app.models import (
    BillingStateObservation,
    BillingStateObservationKind,
    BillingWorkItem,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState as IntentState,
)

RECOVERY_WINDOW = timedelta(hours=2)
MAX_FINANCIAL_RECOVERY_BATCH = 100
FINANCIAL_HINT_SCHEMA = "financial-create:v1"


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
        # Business uniqueness is the locked user/product hold, not the tariff.
        others = queries.other_held_purchases(db, purchase.user_id, purchase.id)
        if len(others) >= queries.MAX_HELD_PURCHASES:
            raise PurchaseRefused("purchase_scope_occupied", 409)
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


def _review(db: Session, row: PurchaseIntent, operation: ExternalCreateOperation, reason: str) -> None:
    if not any(case.reason_code == reason for case in open_customer_reviews(db, operation.create_operation_id)):
        db.add(
            ManualReviewCase(
                reason_code=reason,
                scope_kind="create_operation",
                scope_reference=str(operation.create_operation_id),
                evidence_schema_version="financial-review:v1",
                evidence_document={
                    "purchase_intent_id": str(row.purchase_intent_id),
                    "create_operation_id": str(operation.create_operation_id),
                },
                case_state="open",
            )
        )
    operation.operation_state = State.MANUAL_REVIEW
    operation.send_fence = uuid4()
    row.state = IntentState.MANUAL_REVIEW
    row.state_updated_at = utc_now()


def financial_pending(
    factory: SessionFactory,
    purchase: Purchase,
    expected: FinancialOperation,
    *,
    conflict: bool = False,
    failure_facts: FinancialFailureFacts | None = None,
) -> None:
    with factory() as db:
        row = _locked(db, purchase)
        op = next(op for op in queries.operations(db, purchase.id, lock=True) if op.create_operation_id == expected.id)
        if op.send_fence != expected.fence:
            return  # A stale failure cannot demote a newer proven result.
        work = recovery_work(db, op.create_operation_id)
        deadline = queries.financial_recovery_deadline(op, work)
        if conflict:
            _review(db, row, op, "financial_binding_conflict")
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
        if work and op.operation_state == State.BOUND:
            work.work_state = "pending"
            work.next_attempt_at = utc_now()
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
) -> None:
    with factory() as db:
        row = _locked(db, purchase)
        operations = queries.operations(db, purchase.id, lock=True)
        existing = queries.linked_subscription(db, purchase.id)
        if existing is not None and open_reviews(db, existing.subscription_id):
            raise PurchaseRefused("purchase_review_required", 409)
        op = next(op for op in operations if op.create_operation_id == expected.id)
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
        op.bound_external_object_id = str(provider_id)
        op.operation_state = State.BOUND
        op.resolved_at = op.resolved_at or utc_now()
        op.send_fence = uuid4()
        work = recovery_work(db, op.create_operation_id)
        if work:
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
                evidence_schema_version="prepared-subscription:v1",
                evidence_document=asdict(observation),
                completeness_classification="preparation_only",
                result_classification="not_paid_verified",
            )
            db.add(evidence)
            db.flush()
            # Any reconciliation claim marks this as a monitored subscription.
            # Preparation may append evidence, but it cannot replace lifecycle,
            # financial status, supporting observation or source trust.
            if sub.reconciliation_fencing_token == 0:
                sub.lifecycle_status = Lifecycle.ACTIVE if observation.state == 2 else Lifecycle.INACTIVE
                sub.latest_observation_id = evidence.observation_id
            if new_subscription:
                enroll_subscription(db, sub)
            # No paid trust extension, financial eligibility, access scope, grant or allowance.
            row.state = IntentState.LINKED
            row.state_updated_at = now
        db.flush()
        db.commit()


def bind_financial(
    factory: SessionFactory,
    purchase: Purchase,
    expected: FinancialOperation,
    provider_id: int,
    *,
    observation: PreparedSubscriptionObservation | None = None,
) -> None:
    if type(provider_id) is not int or not 0 < provider_id < 10**20:
        raise ValueError("invalid financial provider identity")
    try:
        _bind_financial(factory, purchase, expected, provider_id, observation=observation)
    except IntegrityError:
        # The failed unit has closed/rolled back before recording the conflict.
        financial_pending(factory, purchase, expected, conflict=True)
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
