"""Transport-independent embedded runner. PostgreSQL owns all durable work."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Mapping
from datetime import datetime
from functools import partial
from typing import Any, TypeVar
from uuid import UUID

import anyio

from app.composition.reconciliation import reconcile_subscription
from app.composition.billing_background import recover_operation, inventory_customer, apply_deadline
from app.domains.billing import background_recovery
from app.domains.billing import access_invalidation
from app.domains.billing import allowance_exhaustion
from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing import work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.work_contracts import WorkLane, WorkAttemptOutcome, InvalidationFailureCode, DeliveryLane
from app.domains.catalog.publication import SessionFactory
from app.infrastructure import billing_worker_metrics as metrics
from app.infrastructure.preflight import (
    PreflightAdmission,
    PreflightCleanupPending,
    PreflightPolicy,
    PreflightDeadlineExceeded,
)
from app.integrations.kernel.client import PlatformKernelClient, KernelInvalidationFailed
from app.infrastructure.sentry import Operation, report_exception
from app.integrations.lbx.client import LbxServerClient

T = TypeVar("T")
logger = logging.getLogger(__name__)


class BillingWorker:
    def __init__(
        self,
        configuration: Settings,
        factory: SessionFactory,
        client: LbxServerClient | None,
        *,
        delivery_clients: Mapping[str, PlatformKernelClient] | None = None,
    ) -> None:
        self.configuration = configuration
        self.factory = factory
        self.client = client
        self.delivery_clients = dict(delivery_clients or {})
        delivery_slots = tuple(
            (DeliveryLane(recipient_id), configuration.billing_worker_delivery_concurrency)
            for recipient_id in self.delivery_clients
        )
        self.admissions = {
            lane: PreflightAdmission(
                PreflightPolicy(
                    configuration.billing_worker_io_timeout_seconds,
                    configuration.preflight_cleanup_timeout_seconds,
                    count,
                    0,
                )
            )
            for lane, count in (
                (WorkLane.URGENT, configuration.billing_worker_urgent_concurrency),
                (WorkLane.NORMAL, configuration.billing_worker_normal_concurrency),
                *delivery_slots,
            )
        }
        # Independent bounded DB delegation; no request-scoped Session crosses
        # threads, and local deadlines cannot queue behind source DB work.
        self.db_limiters = {
            lane: anyio.CapacityLimiter(count)
            for lane, count in (
                (WorkLane.LOCAL, 1),
                (WorkLane.URGENT, configuration.billing_worker_urgent_concurrency),
                (WorkLane.NORMAL, configuration.billing_worker_normal_concurrency),
                *delivery_slots,
            )
        }
        self.db_tasks: dict[WorkLane | DeliveryLane, set[asyncio.Task[Any]]] = {
            lane: set() for lane in self.db_limiters
        }
        self.db_cleanup: set[asyncio.Task[Any]] = set()
        self.tasks: list[asyncio.Task[None]] = []
        self.stopping = False
        self.failed = False
        self.failures = 0
        self.last_progress_at: datetime | None = None
        self.last_verified_subscription_at: datetime | None = None
        self.last_scan_at: datetime | None = None
        self.pending = 0
        self.oldest_due_at: datetime | None = None
        self.invalid = 0
        self.enrolled_batches = 0

    async def db(self, lane: WorkLane | DeliveryLane, function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        # Shield the resource-owning framework task, not just its waiter. Native
        # asyncio cancellation must not release AnyIO's limiter while its thread
        # can still commit. The worker retains and drains that exact task.
        task = asyncio.create_task(
            anyio.to_thread.run_sync(partial(function, *args, **kwargs), limiter=self.db_limiters[lane])
        )
        self.db_tasks[lane].add(task)

        def completed(owner: asyncio.Task[T]) -> None:
            self.db_tasks[lane].discard(owner)
            self.db_cleanup.discard(owner)
            if not owner.cancelled():
                owner.exception()

        task.add_done_callback(completed)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.done():
                self.db_cleanup.add(task)
            raise

    async def start(self) -> None:
        if (
            self.tasks
            or self.stopping
            or any(self.db_tasks.values())
            or any(admission.active_count for admission in self.admissions.values())
        ):
            raise RuntimeError("billing worker cannot restart over existing resource owners")
        await self.db(WorkLane.LOCAL, work.ensure_sweep, self.factory, self.configuration)
        for lane, count in (
            (WorkLane.LOCAL, 1),
            (WorkLane.URGENT, self.configuration.billing_worker_urgent_concurrency),
            (WorkLane.NORMAL, self.configuration.billing_worker_normal_concurrency),
            *(
                (DeliveryLane(recipient_id), self.configuration.billing_worker_delivery_concurrency)
                for recipient_id in self.delivery_clients
            ),
        ):
            if lane in (WorkLane.URGENT, WorkLane.NORMAL) and self.client is None:
                continue
            for _ in range(count):
                task = asyncio.create_task(self._loop(lane), name=f"billing-{lane}")
                task.add_done_callback(self._done)
                self.tasks.append(task)

    def _done(self, task: asyncio.Task[None]) -> None:
        if not self.stopping:
            self.failed = True
            if not task.cancelled() and task.exception() is not None:
                report_exception(task.exception(), operation=Operation.BILLING_WORKER)

    async def tick(self, lane: WorkLane | DeliveryLane) -> bool:
        delivery_lane = lane if isinstance(lane, DeliveryLane) else None
        if lane in (WorkLane.URGENT, WorkLane.NORMAL) and self.client is None:
            return False
        if any(task in self.db_cleanup for task in self.db_tasks[lane]):
            return False  # An interrupted DB owner may still be committing.
        attempt_outcome = WorkAttemptOutcome.COMPLETED
        if lane == WorkLane.LOCAL:
            claim = await self.db(lane, work.claim_work, self.factory, self.configuration, lane)
            if claim is None:
                return False
            if claim.kind == work.SWEEP:
                # One committed batch per tick allows due expiry between batches.
                paid = await self.db(lane, work.repair_paid_deadlines, self.factory, self.configuration)
                delivery = await self.db(lane, access_invalidation.repair_delivery, self.factory, self.configuration)
                count = await self.db(lane, work.enroll_batch, self.factory, self.configuration)
                repaired = (
                    await self.db(lane, background_recovery.repair_batch, self.factory, self.configuration)
                    if self.client is not None
                    else 0
                )
                count = max(count, repaired, paid, delivery)
                self.enrolled_batches += int(count > 0)
                await self.db(
                    lane,
                    work.finish_sweep,
                    self.factory,
                    claim,
                    more=count == self.configuration.billing_worker_scan_batch_size,
                )
            elif claim.kind == background_recovery.DEADLINE:
                await apply_deadline(self.factory, claim, delegate=partial(self.db, lane))
            elif claim.kind == allowance_exhaustion.KIND:
                await self.db(lane, allowance_exhaustion.process_exhaustion, self.factory, claim)
            else:
                await self.db(lane, work.expire_trust, self.factory, claim)
        else:
            admission = self.admissions[lane]
            if admission.active_count >= admission.policy.max_active:
                return False  # Unfinished cleanup still occupies its actual slot.
            async with admission.operation(bound_scope=False) as budget:
                claim = await self.db(
                    lane,
                    work.claim_work,
                    self.factory,
                    self.configuration,
                    WorkLane.DELIVERY if delivery_lane else lane,
                    recipient_id=delivery_lane.recipient_id if delivery_lane else None,
                )
                if claim is None:
                    return False
                try:
                    if claim.kind == access_invalidation.KIND:
                        sent = await self.db(
                            lane, access_invalidation.capture_delivery, self.factory, self.configuration, claim
                        )
                        if sent is not None:
                            error: InvalidationFailureCode | None = None
                            permanent = False
                            try:
                                await self.delivery_clients[sent.recipient_id].send_invalidation(sent, budget=budget)
                            except KernelInvalidationFailed as failure:
                                error, permanent = failure.code, failure.permanent
                            except PreflightDeadlineExceeded:
                                error = InvalidationFailureCode.TIMEOUT
                            await self.db(
                                lane,
                                access_invalidation.apply_delivery,
                                self.factory,
                                claim,
                                sent,
                                error=error,
                                permanent=permanent,
                            )
                            if permanent:
                                logger.error("Backend invalidation delivery parked recipient=%s", sent.recipient_id)
                                report_exception(
                                    KernelInvalidationFailed(error, permanent=True), operation=Operation.BILLING_WORKER
                                )
                            attempt_outcome = (
                                WorkAttemptOutcome.PARKED
                                if permanent
                                else WorkAttemptOutcome.RETRY
                                if error
                                else WorkAttemptOutcome.COMPLETED
                            )
                    elif claim.kind == background_recovery.RECOVERY:
                        await recover_operation(
                            self.client,
                            admission,
                            self.configuration,
                            factory=self.factory,
                            claim=claim,
                            budget=budget,
                            delegate=partial(self.db, lane),
                        )
                    elif claim.kind == background_recovery.INVENTORY:
                        await inventory_customer(
                            self.client,
                            admission,
                            self.configuration,
                            factory=self.factory,
                            claim=claim,
                            budget=budget,
                            delegate=partial(self.db, lane),
                        )
                    else:
                        result = await reconcile_subscription(
                            self.client,
                            admission,
                            self.configuration,
                            factory=self.factory,
                            subscription_id=UUID(claim.reference),
                            work_claim=claim,
                            budget=budget,
                            delegate=partial(self.db, lane),
                        )
                        outcome, observed_at = await self.db(
                            lane, work.reconciliation_outcome, self.factory, result.observation_id
                        )
                        metrics.PROOFS.labels(outcome=outcome).inc()
                        if outcome == "verified":
                            self.last_verified_subscription_at = max(
                                self.last_verified_subscription_at or observed_at, observed_at
                            )
                            metrics.LAST_PROOF.set(self.last_verified_subscription_at.timestamp())
                except BillingRefused as error:
                    if error.code == "billing_work_stale":
                        raise
                    saved = await self.db(
                        lane,
                        work.retry_work,
                        self.factory,
                        claim,
                        invalid=claim.kind == work.RECONCILIATION
                        and error.code
                        in {
                            "subscription_not_found",
                            "subscription_provenance_unproven",
                            "purchase_history_unproven",
                            "purchase_consent_unproven",
                            "purchase_scope_released",
                        },
                        error=error.code,
                    )
                    if not saved:
                        raise
                    attempt_outcome = WorkAttemptOutcome.REFUSED
        self.last_progress_at = utc_now()
        metrics.PROGRESS.set(self.last_progress_at.timestamp())
        metrics.ATTEMPTS.labels(lane=lane.value, outcome=attempt_outcome).inc()
        return True

    async def _loop(self, lane: WorkLane | DeliveryLane) -> None:
        while not self.stopping:
            try:
                progressed = await self.tick(lane)
                if lane == WorkLane.LOCAL:
                    self.pending, self.oldest_due_at, self.invalid = await self.db(
                        lane, work.inspect_backlog, self.factory, self.configuration
                    )
                    self.last_scan_at = utc_now()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                self.failures += 1
                metrics.ATTEMPTS.labels(lane=lane.value, outcome=WorkAttemptOutcome.FAILED).inc()
                # Safe constant message; the reporting adapter strips raw errors.
                logger.warning("Billing worker attempt failed", extra={"structured": {"lane": lane.value}})
                report_exception(error, operation=Operation.BILLING_WORKER)
                progressed = False
            for label in (WorkLane.URGENT, WorkLane.NORMAL, WorkLane.DELIVERY):
                slots = [key for key in self.admissions if key.value == label.value]
                metrics.SLOTS.labels(lane=label.value).set(sum(self.admissions[key].active_count for key in slots))
                metrics.CLEANUP.labels(lane=label.value).set(
                    sum(
                        self.admissions[key].cleanup_pending_count
                        + sum(task in self.db_cleanup for task in self.db_tasks[key])
                        for key in slots
                    )
                )
            metrics.CLEANUP.labels(lane=WorkLane.LOCAL.value).set(
                sum(task in self.db_cleanup for task in self.db_tasks[WorkLane.LOCAL])
            )
            metrics.BACKLOG.set(self.pending)
            metrics.INVALID.set(self.invalid)
            metrics.LAG.set(max(0, utc_now().timestamp() - self.oldest_due_at.timestamp()) if self.oldest_due_at else 0)
            await asyncio.sleep(0 if progressed else 1)

    @property
    def cleanup_pending(self) -> int:
        return len(self.db_cleanup) + sum(admission.cleanup_pending_count for admission in self.admissions.values())

    @property
    def ready(self) -> bool:
        return (
            not self.failed
            and not self.stopping
            and self.last_scan_at is not None
            and (utc_now() - self.last_scan_at).total_seconds() < 120
        )

    @property
    def healthy(self) -> bool:
        return self.ready and self.cleanup_pending == 0

    async def aclose(self) -> None:
        self.stopping = True
        if self.tasks:
            _, pending = await asyncio.wait(self.tasks, timeout=self.configuration.billing_worker_io_timeout_seconds)
            for task in pending:
                task.cancel()
            if pending:
                _, still_pending = await asyncio.wait(
                    pending, timeout=self.configuration.preflight_cleanup_timeout_seconds
                )
                if still_pending:
                    self.failed = True
                    raise PreflightCleanupPending()
        db_owners = set().union(*self.db_tasks.values())
        if db_owners:
            _, pending_db = await asyncio.wait(db_owners, timeout=self.configuration.preflight_cleanup_timeout_seconds)
            if pending_db:
                self.failed = True
                raise PreflightCleanupPending()
        results = await asyncio.gather(
            *(admission.aclose() for admission in self.admissions.values()), return_exceptions=True
        )
        if any(isinstance(result, BaseException) for result in results):
            self.failed = True
            raise PreflightCleanupPending()
