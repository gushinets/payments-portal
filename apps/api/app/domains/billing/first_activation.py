"""First activation status and Widget reconciliation handoff."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy.orm import Session

from app.domains.billing.contracts import BillingRefused
from app.domains.billing.paid_contracts import EffectiveState
from app.domains.billing.paid_deadlines import effective_deadline
from app.domains.billing.work_contracts import WorkAttemptOutcome, WorkClaim
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.widget_activation_window import (
    CLOSING_GRACE,
    WidgetActivationCompletionReason,
    WidgetActivationWindow,
)
from app.infrastructure.queries import billing_reconciliation, billing_work
from app.models import (
    BillingProductAccessScope,
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


class WidgetInventoryWait(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    key: str
    owner: str
    generation: int


class WidgetReconciliationWakeup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    window: ActivationWindowKey
    generation: int
    running_attempt: ReconciliationAttempt | None
    original_due_at: AwareDatetime | None
    original_priority: int
    inventory_coverage: WidgetInventoryCoverage | None = Field(default=None, exclude_if=lambda value: value is None)
    inventory_wait: WidgetInventoryWait | None = Field(default=None, exclude_if=lambda value: value is None)
    source_wait_fence: int | None = Field(default=None, exclude_if=lambda value: value is None)

    def ordinary_schedule(self, due: datetime, priority: int) -> tuple[datetime, int]:
        if self.original_due_at is None:
            return due, priority
        return min(self.original_due_at, due), max(self.original_priority, priority)

    def ordinary_check_due(self, at: datetime | None) -> bool:
        return at is not None and self.original_due_at is not None and self.original_due_at <= as_utc(at)


class ReconciliationQueuePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    first_primary: FirstPrimaryAttempt | None = Field(default=None, exclude_if=lambda value: value is None)
    widget_wakeup: WidgetReconciliationWakeup | None = Field(default=None, exclude_if=lambda value: value is None)
    last_reclaimed_at: AwareDatetime | None = Field(default=None, exclude_if=lambda value: value is None)

    def wakeup_for_generation(self, generation: int) -> WidgetReconciliationWakeup | None:
        wakeup = self.widget_wakeup
        return wakeup if wakeup is not None and wakeup.generation == generation else None

    def wakeup_supersedes_attempt(self, job: BillingWorkItem) -> bool:
        wakeup = self.wakeup_for_generation(job.enqueue_generation)
        prior = wakeup.running_attempt if wakeup is not None else None
        return prior is not None and prior.generation < job.enqueue_generation and prior.number == job.attempt_count

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


def _widget_signal_at(
    db: Session, sub: ExternalSubscription, subscription_key: str, window_key: ActivationWindowKey
) -> datetime | None:
    widget = billing_work.by_key(db, BillingWorkKind.WIDGET_ACTIVATION_CHECK, subscription_key)
    if widget is None or ActivationWindowKey.from_job(widget) != window_key:
        return None
    try:
        window = WidgetActivationWindow.from_work(widget)
    except ValueError:
        return None
    completion = window.completion
    if (
        window.purchase_id != sub.purchase_intent_id
        or completion is None
        or completion.reason != WidgetActivationCompletionReason.ACTIVATION_DETECTED
    ):
        return None
    return completion.at


def _live_inventory_wait(
    inventory: BillingWorkItem | None, now: datetime, signal_at: datetime
) -> WidgetInventoryWait | None:
    if (
        inventory is None
        or not _inventory_is_running(inventory, now)
        or inventory.coalescing_key is None
        or inventory.lease_owner is None
        or as_utc(inventory.next_attempt_at) > signal_at
    ):
        return None
    return WidgetInventoryWait(
        key=inventory.coalescing_key, owner=inventory.lease_owner, generation=inventory.enqueue_generation
    )


def handle_widget_wakeup(
    db: Session,
    sub: ExternalSubscription,
    scope: BillingProductAccessScope,
    claim: WorkClaim,
    *,
    source_busy: bool,
) -> WorkAttemptOutcome | None:
    from app.domains.billing import work

    if source_busy:
        # A busy ordinary attempt keeps its source refusal without locking the queue.
        queued = ReconciliationQueuePayload.from_job(db.get(BillingWorkItem, claim.id))
        if queued.wakeup_for_generation(claim.generation) is None or scope.primary_subscription_id is not None:
            return None
    row = work.verify_claim(db, claim)
    subscription_key = work.key(sub)
    if claim.kind != work.RECONCILIATION or row.coalescing_key != subscription_key:
        raise BillingRefused("billing_work_stale", 409)
    payload = ReconciliationQueuePayload.from_job(row)
    wakeup = payload.wakeup_for_generation(row.enqueue_generation)
    if wakeup is None or row.enqueue_generation != claim.generation:
        return None
    now = as_utc(billing_reconciliation.database_now(db))
    if wakeup.ordinary_check_due(now):
        row.payload_document = payload.model_copy(update={"widget_wakeup": None}).model_dump(mode="json")
        return None
    signal_at = _widget_signal_at(db, sub, subscription_key, wakeup.window)
    if signal_at is None:
        return None

    covered = False
    if not source_busy:
        if scope.primary_subscription_id is None:
            covered = widget_wakeup_is_covered(db, sub, wakeup, payload.first_primary, now)
        elif scope.primary_subscription_id == sub.subscription_id and wakeup.original_due_at is not None:
            # Inventory can commit the first grant before the first worker pickup.
            deadline = effective_deadline(scope)
            covered = (
                deadline is not None
                and deadline > now
                and any(
                    grant.product_id == scope.product_id
                    for grant in EffectiveState.model_validate(scope.effective_access_document).grants
                )
            )
    if not covered:
        if scope.primary_subscription_id is not None:
            return None
        live_inventory = billing_work.by_key(db, BillingWorkKind.CUSTOMER_INVENTORY, inventory_key(sub))
        current_wait = _live_inventory_wait(live_inventory, now, signal_at)
        inventory_busy = current_wait is not None and wakeup.inventory_wait in (None, current_wait)
        if not source_busy and not inventory_busy:
            return None
        wakeup = wakeup.model_copy(
            update={
                "inventory_wait": current_wait if inventory_busy else wakeup.inventory_wait,
                "source_wait_fence": sub.reconciliation_fencing_token if source_busy else None,
            }
        )
        row.payload_document = payload.model_copy(update={"widget_wakeup": wakeup}).model_dump(mode="json")
        work.finish(db, row, claim, due=row.next_attempt_at, error=row.last_error_classification)
        return WorkAttemptOutcome.PARKED

    if wakeup.original_due_at is None:
        work.schedule_reconciliation(db, sub, claim, complete=True)
    else:
        work.finish(db, row, claim, due=wakeup.original_due_at, error=row.last_error_classification)
        row.priority = wakeup.original_priority
        row.payload_document = payload.model_copy(update={"widget_wakeup": None}).model_dump(mode="json")
    return WorkAttemptOutcome.COMPLETED


def retain_widget_schedule(
    db: Session, sub: ExternalSubscription, subscription_key: str, inventory_claim: WorkClaim | None, due: datetime
) -> bool:
    """Merge a future follow-up into the schedule suspended by a Widget wakeup."""
    # The locked read refreshes the ORM row, so flush any pending schedule updates first.
    db.flush()
    row = billing_work.by_key(db, BillingWorkKind.SUBSCRIPTION_RECONCILIATION, subscription_key, lock=True)
    if row is None or row.work_state not in (BillingWorkState.PENDING, BillingWorkState.RUNNING):
        return False
    payload = ReconciliationQueuePayload.from_job(row)
    wakeup = payload.wakeup_for_generation(row.enqueue_generation)
    if wakeup is None:
        return False
    signal_at = _widget_signal_at(db, sub, subscription_key, wakeup.window)
    now = as_utc(billing_reconciliation.database_now(db))
    if signal_at is None or wakeup.ordinary_check_due(now):
        return False
    inventory_wait = wakeup.inventory_wait
    if inventory_claim is not None:
        # Only the verified inventory claim can establish an inventory wait before worker pickup.
        observed = _live_inventory_wait(db.get(BillingWorkItem, inventory_claim.id), now, signal_at)
        expected = WidgetInventoryWait(
            key=inventory_key(sub), owner=inventory_claim.owner, generation=inventory_claim.generation
        )
        if observed == expected and inventory_wait in (None, observed):
            inventory_wait = observed
    regular_due, regular_priority = wakeup.ordinary_schedule(due, 1)
    wakeup = wakeup.model_copy(
        update={
            "original_due_at": regular_due,
            "original_priority": regular_priority,
            "inventory_wait": inventory_wait,
        }
    )
    row.next_attempt_at = min(as_utc(row.next_attempt_at), regular_due)
    row.payload_document = payload.model_copy(update={"widget_wakeup": wakeup}).model_dump(mode="json")
    return True


def _cabinet_inventory_link(
    window: WidgetActivationWindow,
    window_key: ActivationWindowKey,
    previous: FirstPrimaryAttempt | None,
    inventory: InventoryAttempt,
    reconciliation_window: ActivationWindowKey | None,
    reconciliation_attempt: ReconciliationAttempt | None,
) -> FirstPrimaryAttempt | None:
    completion = window.completion
    if completion is None or reconciliation_attempt is None:
        inventory_at = inventory.started_at if inventory.started_at is not None else inventory.queued_at
        belongs = inventory_at < window.deadline_at + CLOSING_GRACE
    else:
        belongs = reconciliation_window == window_key
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
    reconciliation_window: ActivationWindowKey | None,
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
            window, window_key, payload.first_primary, inventory, reconciliation_window, reconciliation_attempt
        )
    if link is not None or wakeup is not payload.widget_wakeup:
        job.payload_document = payload.model_copy(
            update={"first_primary": link if link is not None else payload.first_primary, "widget_wakeup": wakeup}
        ).model_dump(mode="json")
