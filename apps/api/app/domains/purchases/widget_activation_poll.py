"""Durable slot selection and completion for one Widget activation point read."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from time import monotonic
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing import work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import lock_user
from app.domains.billing.first_activation import ActivationWindowKey, ReconciliationQueuePayload, reusable_first_primary
from app.domains.billing.reconciliation_contracts import SubscriptionLifecycleReason
from app.domains.billing.work_contracts import WorkAttemptOutcome, WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.widget_activation import awaiting_first_activation
from app.domains.purchases.widget_activation_window import (
    ATTEMPT_INTERVAL,
    CLOSING_GRACE,
    WidgetActivationCompletion,
    WidgetActivationCompletionReason,
    WidgetActivationWindow,
)
from app.infrastructure.preflight import PreflightDeadlineExceeded
from app.infrastructure.queries import billing_reconciliation as queries, billing_work, purchases
from app.models import (
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState,
    ExternalSubscription,
    PurchaseIntentState,
)

ERROR_BACKOFF = timedelta(seconds=40)
READ_LIMIT = timedelta(seconds=5)
MAX_READ_CLEANUP_SECONDS = READ_LIMIT.total_seconds() / 2
ATTEMPT_INTERRUPTED = "widget_activation_attempt_interrupted"


@dataclass(frozen=True)
class WidgetActivationRead:
    provider_subscription_id: int
    provider_agreement_id: int
    allowed_until: datetime
    monotonic_deadline: float
    started_at: datetime
    previous_started_at: datetime | None
    previous_error: str | None


@dataclass(frozen=True)
class WidgetActivationReadFailure:
    code: str


# None means the budget expired before any source task could be scheduled.
WidgetActivationResult = SubscriptionLifecycleReason | WidgetActivationReadFailure | None


def _slot_after(window: WidgetActivationWindow, started_at: datetime) -> datetime:
    slot = (as_utc(started_at) - window.prepared_at) // ATTEMPT_INTERVAL + 1
    return min(window.prepared_at + slot * ATTEMPT_INTERVAL, window.deadline_at)


def _next_due(window: WidgetActivationWindow, row: BillingWorkItem) -> datetime:
    start = row.last_attempt_started_at
    slot = 1
    if start is not None:
        elapsed = as_utc(start) - window.prepared_at
        if row.last_error_classification is not None:
            slots, remainder = divmod(elapsed + ERROR_BACKOFF, ATTEMPT_INTERVAL)
            slot = slots + bool(remainder)
        else:
            return _slot_after(window, start)
    return min(window.prepared_at + slot * ATTEMPT_INTERVAL, window.deadline_at)


def _exhausted(window: WidgetActivationWindow, row: BillingWorkItem, now: datetime) -> bool:
    if now < window.deadline_at:
        return False
    if now >= window.deadline_at + CLOSING_GRACE:
        return True
    if row.last_attempt_started_at is None:
        return False
    start = as_utc(row.last_attempt_started_at)
    return start >= window.deadline_at or (
        row.last_error_classification is not None and start + ERROR_BACKOFF > window.deadline_at
    )


def _verify_claim(db: Session, claim: WorkClaim) -> BillingWorkItem:
    row = work.verify_claim(db, claim)
    if row.enqueue_generation != claim.generation:
        raise BillingRefused("billing_work_stale", 409)
    return row


def _complete(
    db: Session,
    row: BillingWorkItem,
    claim: WorkClaim,
    window: WidgetActivationWindow,
    now: datetime,
    reason: WidgetActivationCompletionReason,
) -> None:
    row.payload_document = window.model_copy(
        update={"completion": WidgetActivationCompletion(reason=reason, at=now)}
    ).model_dump(mode="json")
    work.finish(db, row, claim, due=None, error=row.last_error_classification)


def _eligible_subscription(
    db: Session, row: BillingWorkItem, window: WidgetActivationWindow, user_id: UUID
) -> ExternalSubscription | None:
    purchase = purchases.owned(db, user_id, window.purchase_id, lock=True)
    if purchase is None or purchase.state != PurchaseIntentState.LINKED:
        return None
    hold = purchases.hold(db, user_id, purchase.product_id)
    if hold is None or hold.purchase_intent_id != window.purchase_id:
        return None
    sub = queries.subscription(db, UUID(row.scope_reference), lock=True)
    if (
        sub is None
        or sub.purchase_intent_id != window.purchase_id
        or work.key(sub) != row.coalescing_key
        or not awaiting_first_activation(db, purchase, sub, existing_window=True)
        or queries.open_reviews(db, sub.subscription_id)
    ):
        return None
    customer = db.get(ExternalBillingCustomer, sub.customer_id)
    if customer is None or customer.binding_state != ExternalBillingCustomerBindingState.BOUND:
        return None
    return sub


def _provider_id(provider_id: str | None) -> int | None:
    if provider_id is None or not provider_id.isascii() or not provider_id.isdecimal() or len(provider_id) > 20:
        return None
    numeric = int(provider_id)
    return numeric if numeric > 0 and str(numeric) == provider_id else None


def _locked_target(
    db: Session, configuration: Settings, claim: WorkClaim
) -> tuple[BillingWorkItem, WidgetActivationWindow, ExternalSubscription | None]:
    sub = queries.subscription(db, UUID(claim.reference))
    # Serialize against Widget enqueue and reconciliation before locking the queue row.
    user = lock_user(db, sub.user_id) if sub is not None else None
    row = _verify_claim(db, claim)
    window = WidgetActivationWindow.from_work(row)
    target = None
    if user is not None and (user.tenant_id, user.region) == (
        configuration.instance_tenant_id,
        configuration.instance_region,
    ):
        target = _eligible_subscription(db, row, window, user.id)
    return row, window, target


def _claim_time(db: Session, claim: WorkClaim) -> datetime:
    now = as_utc(queries.database_now(db))
    if now >= claim.expires_at:
        raise BillingRefused("billing_work_stale", 409)
    return now


def prepare_widget_activation_read(
    factory: SessionFactory, configuration: Settings, claim: WorkClaim
) -> WidgetActivationRead | None:
    with factory() as db:
        row, window, target = _locked_target(db, configuration, claim)
        subscription_id = _provider_id(target.external_subscription_id) if target is not None else None
        agreement_id = _provider_id(target.external_agreement_id) if target is not None else None
        # A delay obtaining the locks, committing, or resuming the waiter consumes the same budget.
        sampled_at = monotonic()
        now = _claim_time(db, claim)
        due = _next_due(window, row)
        attempt = None
        if _exhausted(window, row, now):
            _complete(db, row, claim, window, now, WidgetActivationCompletionReason.WINDOW_EXPIRED)
        elif now < due:
            work.finish(db, row, claim, due=due, error=row.last_error_classification)
        elif subscription_id is None or agreement_id is None:
            _complete(db, row, claim, window, now, WidgetActivationCompletionReason.PURCHASE_INELIGIBLE)
        else:
            cutoff = window.deadline_at if now < window.deadline_at else window.deadline_at + CLOSING_GRACE
            allowed_until = min(cutoff, now + READ_LIMIT, claim.expires_at)
            attempt = WidgetActivationRead(
                provider_subscription_id=subscription_id,
                provider_agreement_id=agreement_id,
                allowed_until=allowed_until,
                monotonic_deadline=sampled_at + (allowed_until - now).total_seconds(),
                started_at=now,
                previous_started_at=row.last_attempt_started_at,
                previous_error=row.last_error_classification,
            )
            row.attempt_count += 1
            row.last_attempt_started_at = now
            # An abandoned claim still consumed this slot, including the one closing slot.
            row.last_error_classification = ATTEMPT_INTERRUPTED
        db.commit()
        return attempt


def defer_widget_activation_read(factory: SessionFactory, claim: WorkClaim) -> WorkAttemptOutcome:
    # Preparation rolled back before LBX I/O. Ownership of the queue row is enough to skip the slot.
    with factory() as db:
        row = _verify_claim(db, claim)
        window = WidgetActivationWindow.from_work(row)
        now = _claim_time(db, claim)
        if _exhausted(window, row, now) or claim.started_at >= window.deadline_at:
            _complete(db, row, claim, window, now, WidgetActivationCompletionReason.WINDOW_EXPIRED)
        else:
            due = max(_next_due(window, row), _slot_after(window, now))
            work.finish(db, row, claim, due=due, error=row.last_error_classification)
        db.commit()
        return WorkAttemptOutcome.REFUSED


def _try_handoff(
    db: Session,
    subscription: ExternalSubscription,
    window: ActivationWindowKey,
    claim: WorkClaim,
    allowed_until: datetime,
) -> datetime:
    regular = billing_work.by_key(db, work.RECONCILIATION, work.key(subscription))
    link = ReconciliationQueuePayload.from_job(regular).first_primary
    if reusable_first_primary(db, subscription, link, window, _claim_time(db, claim)):
        return _claim_time(db, claim)
    # The regular queue upsert can wait on another owner. Undo the hint if that wait consumes the budget.
    with db.begin_nested() as handoff:
        work.hint_widget_reconciliation(db, subscription, window)
        now = _claim_time(db, claim)
        if now > allowed_until:
            handoff.rollback()
    return now


def finish_widget_activation_read(
    factory: SessionFactory,
    configuration: Settings,
    claim: WorkClaim,
    attempt: WidgetActivationRead,
    result: WidgetActivationResult,
) -> WorkAttemptOutcome:
    with factory() as db:
        row, window, target = _locked_target(db, configuration, claim)
        if target is not None and (
            target.external_subscription_id != str(attempt.provider_subscription_id)
            or target.external_agreement_id != str(attempt.provider_agreement_id)
        ):
            target = None
        now = _claim_time(db, claim)
        if target is not None and result == SubscriptionLifecycleReason.ACTIVE and now <= attempt.allowed_until:
            now = _try_handoff(db, target, ActivationWindowKey.from_job(row), claim, attempt.allowed_until)
        if result is None:
            row.attempt_count -= 1
            row.last_attempt_started_at = attempt.previous_started_at
            row.last_error_classification = attempt.previous_error
        elif now > attempt.allowed_until:
            result = WidgetActivationReadFailure(PreflightDeadlineExceeded().code)
        if result is not None:
            row.last_error_classification = result.code if isinstance(result, WidgetActivationReadFailure) else None

        completion = None
        if target is None or result == SubscriptionLifecycleReason.ENDED:
            completion = WidgetActivationCompletionReason.PURCHASE_INELIGIBLE
        elif result == SubscriptionLifecycleReason.ACTIVE:
            completion = WidgetActivationCompletionReason.ACTIVATION_DETECTED
        elif _exhausted(window, row, now) or (result is None and attempt.started_at >= window.deadline_at):
            completion = WidgetActivationCompletionReason.WINDOW_EXPIRED

        if completion is not None:
            _complete(db, row, claim, window, now, completion)
            outcome = WorkAttemptOutcome.COMPLETED
        else:
            due = _next_due(window, row)
            if result is None:
                due = max(due, _slot_after(window, attempt.started_at))
            work.finish(db, row, claim, due=due, error=row.last_error_classification)
            outcome = (
                WorkAttemptOutcome.RETRY
                if isinstance(result, WidgetActivationReadFailure)
                else WorkAttemptOutcome.COMPLETED
            )
        db.commit()
        return outcome
