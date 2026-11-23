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
from app.infrastructure.queries import billing_reconciliation as queries, purchases
from app.models import (
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState,
    ExternalSubscription,
    PurchaseIntentState,
)

ERROR_BACKOFF = timedelta(seconds=40)
READ_LIMIT = timedelta(seconds=5)
ATTEMPT_INTERRUPTED = "widget_activation_attempt_interrupted"


@dataclass(frozen=True)
class WidgetActivationRead:
    provider_subscription_id: int
    allowed_until: datetime
    monotonic_deadline: float


@dataclass(frozen=True)
class WidgetActivationReadFailure:
    code: str


WidgetActivationResult = SubscriptionLifecycleReason | WidgetActivationReadFailure


def _next_due(window: WidgetActivationWindow, row: BillingWorkItem) -> datetime:
    start = row.last_attempt_started_at
    slot = 1
    if start is not None:
        elapsed = as_utc(start) - window.prepared_at
        if row.last_error_classification is not None:
            slots, remainder = divmod(elapsed + ERROR_BACKOFF, ATTEMPT_INTERVAL)
            slot = slots + bool(remainder)
        else:
            slot = elapsed // ATTEMPT_INTERVAL + 1
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
        or not awaiting_first_activation(db, purchase, sub)
        or queries.open_reviews(db, sub.subscription_id)
    ):
        return None
    customer = db.get(ExternalBillingCustomer, sub.customer_id)
    if customer is None or customer.binding_state != ExternalBillingCustomerBindingState.BOUND:
        return None
    return sub


def _provider_subscription_id(subscription: ExternalSubscription | None) -> int | None:
    provider_id = subscription.external_subscription_id if subscription is not None else None
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
        provider_id = _provider_subscription_id(target)
        # A delay obtaining the locks, committing, or resuming the waiter consumes the same budget.
        sampled_at = monotonic()
        now = _claim_time(db, claim)
        due = _next_due(window, row)
        attempt = None
        if _exhausted(window, row, now):
            _complete(db, row, claim, window, now, WidgetActivationCompletionReason.WINDOW_EXPIRED)
        elif now < due:
            work.finish(db, row, claim, due=due, error=row.last_error_classification)
        elif provider_id is None:
            _complete(db, row, claim, window, now, WidgetActivationCompletionReason.PURCHASE_INELIGIBLE)
        else:
            cutoff = window.deadline_at if now < window.deadline_at else window.deadline_at + CLOSING_GRACE
            allowed_until = min(cutoff, now + READ_LIMIT, claim.expires_at)
            attempt = WidgetActivationRead(
                provider_id, allowed_until, sampled_at + (allowed_until - now).total_seconds()
            )
            row.attempt_count += 1
            row.last_attempt_started_at = now
            # An abandoned claim still consumed this slot, including the one closing slot.
            row.last_error_classification = ATTEMPT_INTERRUPTED
        db.commit()
        return attempt


def _try_handoff(
    db: Session, subscription: ExternalSubscription, claim: WorkClaim, allowed_until: datetime
) -> datetime:
    # The regular queue upsert can wait on another owner. Undo the hint if that wait consumes the budget.
    with db.begin_nested() as handoff:
        work.enroll_subscription(db, subscription, hint=True)
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
        if target is not None and target.external_subscription_id != str(attempt.provider_subscription_id):
            target = None
        now = _claim_time(db, claim)
        if target is not None and result == SubscriptionLifecycleReason.ACTIVE and now <= attempt.allowed_until:
            now = _try_handoff(db, target, claim, attempt.allowed_until)
        if now > attempt.allowed_until:
            result = WidgetActivationReadFailure(PreflightDeadlineExceeded().code)
        row.last_error_classification = result.code if isinstance(result, WidgetActivationReadFailure) else None

        completion = None
        if target is None or result == SubscriptionLifecycleReason.ENDED:
            completion = WidgetActivationCompletionReason.PURCHASE_INELIGIBLE
        elif result == SubscriptionLifecycleReason.ACTIVE:
            completion = WidgetActivationCompletionReason.ACTIVATION_DETECTED
        elif _exhausted(window, row, now):
            completion = WidgetActivationCompletionReason.WINDOW_EXPIRED

        if completion is not None:
            _complete(db, row, claim, window, now, completion)
            outcome = WorkAttemptOutcome.COMPLETED
        else:
            work.finish(db, row, claim, due=_next_due(window, row), error=row.last_error_classification)
            outcome = WorkAttemptOutcome.RETRY if row.last_error_classification else WorkAttemptOutcome.COMPLETED
        db.commit()
        return outcome
