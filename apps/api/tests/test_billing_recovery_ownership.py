"""Real worker cancellation/dispatch with synthetic already-bound DB results."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from functools import partial
from threading import Event
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.composition import purchase_recovery, reconciliation
from app.composition.sources import SourceResources
from app.domains.billing.reconciliation_contracts import ReconciliationResult, ReconciliationSubject, SubscriptionProof
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases.contracts import FinancialOperation
from app.infrastructure.preflight import PreflightCleanupPending
from app.integrations.lbx.reconciliation import normalize_subscription
from app.jobs.billing import BillingWorker
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from apps.api.tests.factories.reconciliation import (
    agreement_factory,
    subject_factory,
    subscription_factory,
    tariff_factory,
    user_factory,
)
from apps.api.tests.support.any709_step1 import step1_settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    "phase", ["lookup", "claim", "clock", "apply", None], ids=["lookup", "claim", "clock", "apply", "success"]
)
async def test_concurrent_binding_keeps_worker_db_ownership(monkeypatch: pytest.MonkeyPatch, phase: str | None) -> None:
    entered, release, finished = Event(), Event(), Event()
    configuration = step1_settings(billing_worker_io_timeout_seconds=0.5, preflight_cleanup_timeout_seconds=0.01)
    worker = BillingWorker(configuration, lambda: None, object())
    lane = WorkLane.URGENT
    subject = subject_factory()
    agreement = FinancialOperation(
        uuid4(), Kind.AGREEMENT, State.BOUND, "original-agreement", uuid4(), "456", None, None
    )
    operation = FinancialOperation(
        uuid4(), Kind.SUBSCRIPTION, State.UNKNOWN, "original-subscription", uuid4(), None, None, None
    )
    purchase = replace(subject.purchase, operations=(agreement, operation))
    current = replace(purchase, operations=(agreement, replace(operation, state=State.BOUND, bound_id="567")))
    subject = replace(subject, purchase=current)
    proof = normalize_subscription(
        subject,
        configuration,
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=subscription_factory(),
    )

    def boundary[T](name: str, value: T) -> T:
        if name == phase:
            entered.set()
            try:
                assert release.wait(5), "DB unit was not released"
            finally:
                finished.set()
        return value

    def lookup(*args: Any, **kwargs: Any) -> UUID:
        return boundary("lookup", subject.subscription_id)

    def claim(*args: Any, **kwargs: Any) -> ReconciliationSubject:
        return boundary("claim", subject)

    def clock(*args: Any, **kwargs: Any) -> datetime:
        return boundary("clock", datetime.now(UTC))

    def apply(*args: Any, **kwargs: Any) -> ReconciliationResult:
        return boundary("apply", ReconciliationResult(uuid4(), subject, proof, current))

    async def read(*args: Any, **kwargs: Any) -> SubscriptionProof:
        return proof

    # Another participant bound the original while this recovery was opening.
    monkeypatch.setattr(purchase_recovery.financial, "original_request", lambda *a, **k: False)
    monkeypatch.setattr(purchase_recovery.service, "read_purchase", lambda *a, **k: current)
    monkeypatch.setattr(reconciliation.service, "linked_subscription_id", lookup)
    monkeypatch.setattr(reconciliation, "claim_reconciliation", claim)
    monkeypatch.setattr(reconciliation, "read_source_time", clock)
    monkeypatch.setattr(reconciliation, "read_subscription_proof", read)
    monkeypatch.setattr(reconciliation, "apply_reconciliation", apply)
    admission = worker.admissions[lane]
    sources = SourceResources(admission, None, object(), billing=admission)

    async def attempt() -> None:
        async with admission.operation(bound_scope=False) as budget:
            assert await purchase_recovery.recover_one(
                sources,
                configuration,
                purchase,
                operation,
                subject.customer,
                worker.factory,
                budget=budget,
                delegate=partial(worker.db, lane),
            )

    task = asyncio.create_task(attempt())
    worker.tasks.append(task)
    try:
        async with asyncio.timeout(3):
            while not (entered.is_set() if phase else task.done()):
                await asyncio.sleep(0.005)
        if phase is None:
            await task
            await worker.aclose()
            assert worker.cleanup_pending == worker.db_limiters[lane].borrowed_tokens == 0
        else:
            with pytest.raises(PreflightCleanupPending):
                await worker.aclose()
            assert task.cancelled() and not finished.is_set()
            assert worker.failed and worker.cleanup_pending == 1
            assert len(worker.db_tasks[lane]) == worker.db_limiters[lane].borrowed_tokens == 1
    finally:
        release.set()
        if not task.done():
            task.cancel()
        async with asyncio.timeout(3):
            while (entered.is_set() and not finished.is_set()) or worker.db_tasks[lane]:
                await asyncio.sleep(0.005)
        await asyncio.gather(task, return_exceptions=True)
        await worker.aclose()
