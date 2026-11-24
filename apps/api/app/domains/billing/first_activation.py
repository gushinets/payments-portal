"""Link first activation to the existing reconciliation and inventory attempts."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.domains.identity.services.auth import as_utc
from app.domains.purchases.widget_activation_window import (
    CLOSING_GRACE,
    WidgetActivationCompletionReason,
    WidgetActivationWindow,
)
from app.infrastructure.queries import billing_reconciliation, billing_work
from app.models import (
    BillingWorkItem,
    BillingWorkKind,
    BillingWorkState,
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)


class ActivationWindowKey(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    work_item_id: UUID
    generation: int

    @classmethod
    def from_job(cls, job: BillingWorkItem) -> "ActivationWindowKey":
        return cls(work_item_id=job.work_item_id, generation=job.enqueue_generation)


@dataclass(frozen=True)
class InventoryHint:
    work_item_id: UUID
    attempt: int
    queued_at: datetime


class ReconciliationAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generation: int
    number: int


class FirstPrimaryAttempt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    purchase_id: UUID
    window: ActivationWindowKey
    work_item_id: UUID
    attempt: int
    queued_at: AwareDatetime
    reconciliation_attempt: ReconciliationAttempt | None

    def phase(self, inventory: BillingWorkItem | None, now: datetime) -> BillingWorkState | None:
        if inventory is None or inventory.work_item_id != self.work_item_id:
            return None
        if inventory.attempt_count == self.attempt:
            if (
                inventory.work_state == BillingWorkState.RUNNING
                and inventory.lease_expires_at is not None
                and as_utc(inventory.lease_expires_at) > now
            ):
                return BillingWorkState.RUNNING
        elif inventory.attempt_count + 1 == self.attempt and inventory.work_state in (
            BillingWorkState.PENDING,
            BillingWorkState.RUNNING,
        ):
            # An older inventory claim can still be running when hint_inventory advances its generation.
            return BillingWorkState.PENDING
        return None


class WidgetReconciliationWakeup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window: ActivationWindowKey
    generation: int
    running_attempt: ReconciliationAttempt | None
    original_due_at: AwareDatetime | None
    original_priority: int


class ReconciliationQueuePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    first_primary: FirstPrimaryAttempt | None = Field(default=None, exclude_if=lambda value: value is None)
    widget_wakeup: WidgetReconciliationWakeup | None = Field(default=None, exclude_if=lambda value: value is None)

    @classmethod
    def from_job(cls, job: BillingWorkItem | None) -> "ReconciliationQueuePayload":
        if job is not None and job.payload_schema_version == "billing-work:v1":
            try:
                return cls.model_validate(job.payload_document)
            except ValidationError:
                pass
        return cls()


def inventory_key(subscription: ExternalSubscription) -> str:
    return f"{subscription.external_billing_account_id}:{subscription.customer_id}"


def reusable_first_primary(
    db: Session,
    subscription: ExternalSubscription,
    link: FirstPrimaryAttempt | None,
    window: ActivationWindowKey,
    now: datetime,
) -> bool:
    if (
        link is None
        or link.purchase_id != subscription.purchase_intent_id
        or link.window != window
        or subscription.commercial_access_status != Commercial.ELIGIBLE
        or subscription.lifecycle_status != Lifecycle.ACTIVE
        or subscription.financial_access_status != Financial.ALLOWED
        or as_utc(subscription.projection_valid_until) <= now
        or billing_reconciliation.open_reviews(db, subscription.subscription_id)
    ):
        return False
    inventory = billing_work.by_key(db, BillingWorkKind.CUSTOMER_INVENTORY, inventory_key(subscription))
    return link.phase(inventory, now) is not None


def record_first_primary_attempt(
    db: Session,
    *,
    subscription_key: str,
    purchase_id: UUID,
    hint: InventoryHint,
    reconciliation_due_at: datetime | None,
    reconciliation_attempt: ReconciliationAttempt | None,
) -> None:
    # The user lock stabilizes the window definition. A claim can lock the Widget row without changing it.
    widget = billing_work.by_key(db, BillingWorkKind.WIDGET_ACTIVATION_CHECK, subscription_key)
    if widget is None:
        return
    try:
        window = WidgetActivationWindow.from_work(widget)
    except ValueError:
        return
    if window.purchase_id != purchase_id:
        return
    completion = window.completion
    if completion is not None and completion.reason != WidgetActivationCompletionReason.ACTIVATION_DETECTED:
        return
    if completion is None or reconciliation_due_at is None:
        belongs = hint.queued_at < window.deadline_at + CLOSING_GRACE
    else:
        belongs = reconciliation_due_at <= completion.at
    if not belongs:
        return
    # schedule_reconciliation already owns this row in the same transaction.
    job = billing_work.by_key(db, BillingWorkKind.SUBSCRIPTION_RECONCILIATION, subscription_key)
    if job is not None:
        link = FirstPrimaryAttempt(
            purchase_id=purchase_id,
            window=ActivationWindowKey.from_job(widget),
            work_item_id=hint.work_item_id,
            attempt=hint.attempt,
            queued_at=hint.queued_at,
            reconciliation_attempt=reconciliation_attempt,
        )
        job.payload_document = (
            ReconciliationQueuePayload.from_job(job).model_copy(update={"first_primary": link}).model_dump(mode="json")
        )
