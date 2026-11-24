"""Persist the current Widget activation window in the recurring billing queue."""

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from app.domains.identity.services.auth import as_utc
from app.domains.purchases.widget_activation import WidgetActivationOpening
from app.infrastructure.queries import billing_work
from app.infrastructure.queries.billing_reconciliation import database_now
from app.models import BillingWorkItem, BillingWorkKind, BillingWorkScope, BillingWorkState

WINDOW_SCHEMA = "widget-activation-window:v1"
ATTEMPT_INTERVAL = timedelta(seconds=20)
CLOSING_GRACE = timedelta(seconds=5)
HANDOFF_PICKUP_GRACE = timedelta(seconds=60)


class WidgetActivationCompletionReason(StrEnum):
    ACTIVATION_DETECTED = "activation_detected"
    WINDOW_EXPIRED = "window_expired"
    PURCHASE_INELIGIBLE = "purchase_ineligible"


class WidgetActivationCompletion(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: WidgetActivationCompletionReason
    at: AwareDatetime
    inventory_due_at: AwareDatetime | None = Field(default=None, exclude_if=lambda value: value is None)


class WidgetActivationWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    purchase_id: UUID
    prepared_at: AwareDatetime
    deadline_at: AwareDatetime
    completion: WidgetActivationCompletion | None = None

    @model_validator(mode="after")
    def validate_times(self) -> "WidgetActivationWindow":
        if self.deadline_at <= self.prepared_at:
            raise ValueError("Widget activation window must end after preparation")
        if self.completion is not None and self.completion.at < self.prepared_at:
            raise ValueError("Widget activation completion precedes preparation")
        return self

    def reopen_at(self) -> datetime:
        after_close = self.deadline_at + CLOSING_GRACE
        if (
            self.completion is not None
            and self.completion.reason == WidgetActivationCompletionReason.ACTIVATION_DETECTED
        ):
            return max(after_close, self.completion.at + HANDOFF_PICKUP_GRACE)
        return after_close

    @classmethod
    def from_work(cls, row: BillingWorkItem) -> "WidgetActivationWindow":
        if row.payload_schema_version != WINDOW_SCHEMA:
            raise ValueError("Unknown Widget activation window schema")
        return cls.model_validate(row.payload_document)


def record_widget_inventory_hint(
    db: Session,
    *,
    subscription_key: str,
    purchase_id: UUID,
    reconciliation_due_at: datetime,
    inventory_due_at: datetime,
) -> None:
    """Carry an outstanding Widget handoff into the customer's first-primary job."""
    row = billing_work.by_key(db, BillingWorkKind.WIDGET_ACTIVATION_CHECK, subscription_key, lock=True)
    if row is None:
        return
    try:
        window = WidgetActivationWindow.from_work(row)
    except ValueError:
        return
    completion = window.completion
    if (
        window.purchase_id == purchase_id
        and completion is not None
        and completion.reason == WidgetActivationCompletionReason.ACTIVATION_DETECTED
        and completion.inventory_due_at is None
        and reconciliation_due_at <= completion.at
    ):
        row.payload_document = window.model_copy(
            update={"completion": completion.model_copy(update={"inventory_due_at": inventory_due_at})}
        ).model_dump(mode="json")


def save_widget_activation_window(db: Session, opening: WidgetActivationOpening, *, duration_seconds: int) -> None:
    """Caller holds the verified purchase's user lock through commit."""
    kind = BillingWorkKind.WIDGET_ACTIVATION_CHECK
    key = f"{opening.account_id}:{opening.subscription_id}"
    row = billing_work.by_key(db, kind, key, lock=True)
    # Read the clock after the queue lock. The callback may have waited even
    # when its captured opening time satisfies the prior window's bounds.
    now = as_utc(database_now(db))
    deadline = opening.prepared_at + timedelta(seconds=duration_seconds)
    if deadline <= now:
        return
    if row is not None and (
        (row.lease_expires_at is not None and as_utc(row.lease_expires_at) > now)
        or opening.prepared_at < WidgetActivationWindow.from_work(row).reopen_at()
    ):
        return

    window = WidgetActivationWindow(
        purchase_id=opening.purchase_id, prepared_at=opening.prepared_at, deadline_at=deadline
    )
    due = min(window.prepared_at + ATTEMPT_INTERVAL, window.deadline_at)
    if row is None:
        db.add(
            BillingWorkItem(
                work_kind=kind,
                coalescing_key=key,
                scope_kind=BillingWorkScope.SUBSCRIPTION,
                scope_reference=str(opening.subscription_id),
                payload_schema_version=WINDOW_SCHEMA,
                payload_document=window.model_dump(mode="json"),
                next_attempt_at=due,
                work_state=BillingWorkState.PENDING,
            )
        )
        return

    row.payload_document = window.model_dump(mode="json")
    row.next_attempt_at = due
    row.work_state = BillingWorkState.PENDING
    row.enqueue_generation += 1
    row.attempt_count = 0
    row.last_attempt_started_at = None
    row.last_error_classification = None
    row.lease_owner = row.lease_expires_at = None
