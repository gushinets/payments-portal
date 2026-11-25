"""First activation status and Widget reconciliation handoff."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.domains.billing.work_contracts import WorkClaim
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


class InventorySourceProof(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generation: int
    subscription_fence: int


@dataclass(frozen=True)
class InventoryAttempt:
    work_item_id: UUID
    attempt: int
    queued_at: datetime
    source_proof: InventorySourceProof | None = None
    started_at: datetime | None = None

    @classmethod
    def from_claim(cls, row: BillingWorkItem, claim: WorkClaim, subscription_fence: int) -> "InventoryAttempt | None":
        if row.enqueue_generation != claim.generation:
            return None
        return cls(
            work_item_id=row.work_item_id,
            attempt=row.attempt_count,
            # The queue keeps this due time while a worker owns the attempt.
            queued_at=as_utc(row.next_attempt_at),
            source_proof=InventorySourceProof(generation=claim.generation, subscription_fence=subscription_fence),
            started_at=claim.started_at,
        )


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
    inventory_proof: InventorySourceProof | None = Field(default=None, exclude_if=lambda value: value is None)

    def phase(self, inventory: BillingWorkItem | None, now: datetime) -> BillingWorkState | None:
        if inventory is None or inventory.work_item_id != self.work_item_id:
            return None
        if self.inventory_proof is not None and inventory.enqueue_generation != self.inventory_proof.generation:
            return None
        if inventory.attempt_count == self.attempt:
            if _inventory_is_running(inventory, now):
                return BillingWorkState.RUNNING
        elif inventory.attempt_count + 1 == self.attempt and inventory.work_state in (
            BillingWorkState.PENDING,
            BillingWorkState.RUNNING,
        ):
            # An older inventory claim can still be running when hint_inventory advances its generation.
            return BillingWorkState.PENDING
        return None


class WidgetInventoryCoverage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    work_item_id: UUID
    attempt: int
    source: InventorySourceProof


class WidgetReconciliationWakeup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window: ActivationWindowKey
    generation: int
    running_attempt: ReconciliationAttempt | None
    original_due_at: AwareDatetime | None
    original_priority: int
    inventory_coverage: WidgetInventoryCoverage | None = Field(default=None, exclude_if=lambda value: value is None)


class ReconciliationQueuePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    first_primary: FirstPrimaryAttempt | None = Field(default=None, exclude_if=lambda value: value is None)
    widget_wakeup: WidgetReconciliationWakeup | None = Field(default=None, exclude_if=lambda value: value is None)
    last_reclaimed_at: AwareDatetime | None = Field(default=None, exclude_if=lambda value: value is None)

    def was_reclaimed_since(self, handoff_at: datetime) -> bool:
        return self.last_reclaimed_at is not None and self.last_reclaimed_at >= handoff_at

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


def _inventory_is_running(inventory: BillingWorkItem, now: datetime) -> bool:
    return (
        inventory.work_state == BillingWorkState.RUNNING
        and inventory.lease_expires_at is not None
        and as_utc(inventory.lease_expires_at) > now
    )


def _reusable_subscription_source(db: Session, subscription: ExternalSubscription, now: datetime) -> bool:
    return (
        subscription.commercial_access_status == Commercial.ELIGIBLE
        and subscription.lifecycle_status == Lifecycle.ACTIVE
        and subscription.financial_access_status == Financial.ALLOWED
        and as_utc(subscription.projection_valid_until) > now
        and not billing_reconciliation.open_reviews(db, subscription.subscription_id)
    )


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
        or not _reusable_subscription_source(db, subscription, now)
    ):
        return False
    if (
        link.inventory_proof is not None
        and subscription.reconciliation_fencing_token != link.inventory_proof.subscription_fence
    ):
        return False
    inventory = billing_work.by_key(db, BillingWorkKind.CUSTOMER_INVENTORY, inventory_key(subscription))
    return link.phase(inventory, now) is not None


def _reusable_widget_inventory(
    db: Session,
    subscription: ExternalSubscription,
    coverage: WidgetInventoryCoverage,
    now: datetime,
) -> bool:
    if (
        subscription.reconciliation_fencing_token != coverage.source.subscription_fence
        or not _reusable_subscription_source(db, subscription, now)
    ):
        return False
    inventory = billing_work.by_key(db, BillingWorkKind.CUSTOMER_INVENTORY, inventory_key(subscription))
    return (
        inventory is not None
        and (inventory.work_item_id, inventory.attempt_count, inventory.enqueue_generation)
        == (coverage.work_item_id, coverage.attempt, coverage.source.generation)
        and _inventory_is_running(inventory, now)
    )


def widget_wakeup_is_covered(
    db: Session,
    subscription: ExternalSubscription,
    wakeup: WidgetReconciliationWakeup,
    first_primary: FirstPrimaryAttempt | None,
    now: datetime,
) -> bool:
    if (
        wakeup.running_attempt is None
        and wakeup.original_due_at is not None
        and wakeup.inventory_coverage is not None
        and _reusable_widget_inventory(db, subscription, wakeup.inventory_coverage, now)
    ):
        return True
    return (
        first_primary is not None
        and (wakeup.running_attempt is None or first_primary.reconciliation_attempt == wakeup.running_attempt)
        and reusable_first_primary(db, subscription, first_primary, wakeup.window, now)
    )


def _cabinet_inventory_link(
    window: WidgetActivationWindow,
    window_key: ActivationWindowKey,
    previous: FirstPrimaryAttempt | None,
    inventory: InventoryAttempt,
    reconciliation_due_at: datetime | None,
    reconciliation_attempt: ReconciliationAttempt | None,
) -> FirstPrimaryAttempt | None:
    completion = window.completion
    if completion is None or reconciliation_due_at is None:
        inventory_at = inventory.started_at if inventory.started_at is not None else inventory.queued_at
        belongs = inventory_at < window.deadline_at + CLOSING_GRACE
    else:
        belongs = reconciliation_due_at <= completion.at
    if not belongs:
        return None
    if inventory.source_proof is not None:
        if previous is not None and (previous.window, previous.work_item_id) != (window_key, inventory.work_item_id):
            previous = None
        if previous is not None and previous.attempt == inventory.attempt:
            # Preserve the reconciliation that queued this attempt for covered Widget wakeups.
            reconciliation_attempt = previous.reconciliation_attempt
        elif completion is not None and (
            inventory.queued_at > completion.at or (previous is not None and previous.attempt < inventory.attempt)
        ):
            # A reclaimed job can retain its original due time after the linked attempt expires.
            return None
    return FirstPrimaryAttempt(
        purchase_id=window.purchase_id,
        window=window_key,
        work_item_id=inventory.work_item_id,
        attempt=inventory.attempt,
        queued_at=inventory.queued_at,
        reconciliation_attempt=reconciliation_attempt,
        inventory_proof=inventory.source_proof,
    )


def record_first_activation_inventory(
    db: Session,
    *,
    subscription_key: str,
    purchase_id: UUID,
    inventory: InventoryAttempt,
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
    # schedule_reconciliation already owns this row in the same transaction.
    job = billing_work.by_key(db, BillingWorkKind.SUBSCRIPTION_RECONCILIATION, subscription_key)
    if job is None:
        return
    payload = ReconciliationQueuePayload.from_job(job)
    window_key = ActivationWindowKey.from_job(widget)
    wakeup = payload.widget_wakeup
    # Inventory that was already due can cover a pending Widget wakeup even if the cabinet's linked attempt ended.
    if (
        wakeup is not None
        and wakeup.window == window_key
        and wakeup.generation == job.enqueue_generation
        and wakeup.running_attempt is None
        and wakeup.original_due_at is not None
        and completion is not None
        and inventory.queued_at <= completion.at
        and inventory.source_proof is not None
    ):
        coverage = WidgetInventoryCoverage(
            work_item_id=inventory.work_item_id,
            attempt=inventory.attempt,
            source=inventory.source_proof,
        )
        wakeup = wakeup.model_copy(update={"inventory_coverage": coverage})
    link = None
    if reconciliation_attempt is None or completion is None or not payload.was_reclaimed_since(completion.at):
        link = _cabinet_inventory_link(
            window, window_key, payload.first_primary, inventory, reconciliation_due_at, reconciliation_attempt
        )
    if link is not None or wakeup is not payload.widget_wakeup:
        job.payload_document = payload.model_copy(
            update={"first_primary": link if link is not None else payload.first_primary, "widget_wakeup": wakeup}
        ).model_dump(mode="json")
