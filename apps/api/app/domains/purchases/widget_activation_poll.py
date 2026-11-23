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


def _provider_subscription_id(
    db: Session, row: BillingWorkItem, window: WidgetActivationWindow, user_id: UUID
) -> int | None:
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
    provider_id = sub.external_subscription_id
    if provider_id is None or not provider_id.isascii() or not provider_id.isdecimal() or len(provider_id) > 20:
        return None
    numeric = int(provider_id)
    return numeric if numeric > 0 and str(numeric) == provider_id else None


def prepare_widget_activation_read(
    factory: SessionFactory, configuration: Settings, claim: WorkClaim
) -> WidgetActivationRead | None:
    with factory() as db:
        sub = queries.subscription(db, UUID(claim.reference))
        # Serialize against Widget enqueue and reconciliation before locking the queue row.
        user = lock_user(db, sub.user_id) if sub is not None else None
        row = _verify_claim(db, claim)
        window = WidgetActivationWindow.from_work(row)
        provider_id = (
            _provider_subscription_id(db, row, window, user.id)
            if user is not None
            and (user.tenant_id, user.region) == (configuration.instance_tenant_id, configuration.instance_region)
            else None
        )
        # A delay obtaining the locks, committing, or resuming the waiter consumes the same budget.
        sampled_at = monotonic()
        now = as_utc(queries.database_now(db))
        if now >= claim.expires_at:
            raise BillingRefused("billing_work_stale", 409)
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


def finish_widget_activation_read(
    factory: SessionFactory, claim: WorkClaim, attempt: WidgetActivationRead, *, error: str | None
) -> WorkAttemptOutcome:
    with factory() as db:
        row = _verify_claim(db, claim)
        window = WidgetActivationWindow.from_work(row)
        now = as_utc(queries.database_now(db))
        row.last_error_classification = PreflightDeadlineExceeded().code if now > attempt.allowed_until else error
        if _exhausted(window, row, now):
            _complete(db, row, claim, window, now, WidgetActivationCompletionReason.WINDOW_EXPIRED)
            outcome = WorkAttemptOutcome.COMPLETED
        else:
            work.finish(db, row, claim, due=_next_due(window, row), error=row.last_error_classification)
            outcome = WorkAttemptOutcome.RETRY if row.last_error_classification else WorkAttemptOutcome.COMPLETED
        db.commit()
        return outcome
