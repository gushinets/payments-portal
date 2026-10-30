"""Durable refusal handling, worker reporting and preserved subscription proof."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.time import utc_now
from app.domains.billing import work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.reconciliation import claim_reconciliation
from app.domains.billing.work_contracts import WorkLane
from app.infrastructure import billing_worker_metrics as metrics
from app.jobs import billing
from app.models import BillingWorkItem, ExternalSubscription
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_subscription_reconciliation_postgres import (
    activate,
    scenario as scenario,
    snapshot,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
LANE = WorkLane.URGENT


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def queue(factory: sessionmaker[Session]) -> BillingWorkItem:
    with factory() as db:
        return db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)).one()


def attempts() -> dict[str, float]:
    return {
        outcome: metrics.ATTEMPTS.labels(lane=LANE.value, outcome=outcome)._value.get()
        for outcome in ("completed", "refused", "failed")
    }


@pytest.fixture
async def refusing_worker(
    scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> AsyncIterator[billing.BillingWorker]:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    activate(transport)
    worker = billing.BillingWorker(step1_settings(), factory, sources.require_lbx())
    try:
        # First establish real matching proof and successful worker telemetry.
        assert await worker.tick(LANE)
        assert worker.last_verified_subscription_at is not None
        with factory() as db:
            row = db.get(BillingWorkItem, queue(factory).work_item_id)
            row.next_attempt_at = utc_now() - timedelta(seconds=1)
            row.priority = 1
            db.commit()
        # An overlapping reconciliation owns a live source lease. The next
        # worker attempt must refuse before HTTP and durably reschedule.
        claim_reconciliation(factory, worker.configuration, snapshot(factory)[0], io_timeout_seconds=60)
        yield worker
    finally:
        await worker.aclose()


@pytest.mark.parametrize(
    "code,new_hint",
    [
        ("subscription_reconciliation_busy", False),
        ("subscription_reconciliation_busy", True),
        ("subscription_not_found", False),
    ],
)
async def test_billing_worker_committed_refusal_is_progress_without_new_proof(
    refusing_worker: billing.BillingWorker,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    code: str,
    new_hint: bool,
) -> None:
    worker, factory = refusing_worker, postgres_session_factory
    original = billing.reconcile_subscription
    before_facts, before_queue = snapshot(factory), queue(factory)
    progress, verified = worker.last_progress_at, worker.last_verified_subscription_at
    counters, proof_signal = attempts(), metrics.LAST_PROOF._value.get()
    reports: list[Exception] = []
    hinted_due = None

    async def reconcile(*args: object, **kwargs: object) -> UUID:
        nonlocal hinted_due
        worker.stopping = True  # Bound the real loop to this one attempt.
        if new_hint:
            with factory() as db:
                work.enroll_subscription(db, db.get(ExternalSubscription, before_facts[0]), hint=True)
                db.commit()
            hinted_due = queue(factory).next_attempt_at
        if code == "subscription_not_found":
            raise BillingRefused(code, 404)
        return await original(*args, **kwargs)

    def report(error: Exception, **kwargs: object) -> None:
        reports.append(error)

    monkeypatch.setattr(billing, "reconcile_subscription", reconcile)
    monkeypatch.setattr(billing, "report_exception", report)
    await asyncio.wait_for(worker._loop(LANE), 10)

    row = queue(factory)
    assert row.work_state == ("invalid" if code == "subscription_not_found" else "pending")
    assert row.lease_owner is None and row.lease_expires_at is None
    assert row.attempt_count == before_queue.attempt_count + 1
    assert row.last_error_classification == (
        "subscription_provenance_unproven" if code == "subscription_not_found" else code
    )
    if new_hint:
        assert row.enqueue_generation == before_queue.enqueue_generation + 1
        assert row.next_attempt_at == hinted_due
    else:
        assert row.enqueue_generation == before_queue.enqueue_generation
        assert row.next_attempt_at >= row.last_attempt_started_at + timedelta(
            seconds=worker.configuration.billing_worker_io_timeout_seconds + 31
        )
        assert work.claim_work(factory, worker.configuration, LANE) is None
    assert snapshot(factory) == before_facts
    assert worker.failures == 0 and reports == []
    assert worker.last_progress_at > progress
    assert metrics.PROGRESS._value.get() == worker.last_progress_at.timestamp()
    assert worker.last_verified_subscription_at == verified
    assert metrics.LAST_PROOF._value.get() == proof_signal
    assert {key: value - counters[key] for key, value in attempts().items()} == {
        "completed": 0,
        "refused": 1,
        "failed": 0,
    }


@pytest.mark.parametrize("failure", ["new_owner", "expired", "commit_failed", "uncertain_commit"])
async def test_billing_worker_unacknowledged_refusal_remains_visible_as_failure(
    refusing_worker: billing.BillingWorker,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    worker, factory = refusing_worker, postgres_session_factory
    original = billing.reconcile_subscription
    commit = Session.commit
    before_facts = snapshot(factory)
    progress, verified = worker.last_progress_at, worker.last_verified_subscription_at
    counters = attempts()
    progress_signal, proof_signal = metrics.PROGRESS._value.get(), metrics.LAST_PROOF._value.get()
    reports: list[Exception] = []

    def fail_commit(db: Session) -> None:
        if failure == "uncertain_commit":
            commit(db)
        raise RuntimeError("retry commit acknowledgement failed")

    async def reconcile(*args: object, **kwargs: object) -> UUID:
        worker.stopping = True
        if failure in ("new_owner", "expired"):
            with factory() as db:
                row = db.get(BillingWorkItem, queue(factory).work_item_id)
                if failure == "new_owner":
                    row.lease_owner = "successor-worker"
                else:
                    row.lease_expires_at = utc_now() - timedelta(seconds=1)
                db.commit()
        else:
            # Install only after the queue claim committed. The source lease
            # refusal performs no commit, so this faults the retry transaction.
            scoped.setattr(Session, "commit", fail_commit)
        return await original(*args, **kwargs)

    def report(error: Exception, **kwargs: object) -> None:
        reports.append(error)

    with monkeypatch.context() as scoped:
        scoped.setattr(billing, "reconcile_subscription", reconcile)
        scoped.setattr(billing, "report_exception", report)
        await asyncio.wait_for(worker._loop(LANE), 10)

    row = queue(factory)
    if failure == "uncertain_commit":
        assert row.work_state == "pending" and row.lease_owner is None
        assert row.last_error_classification == "subscription_reconciliation_busy"
    else:
        assert row.work_state == "running"
        assert row.lease_owner is not None
        if failure == "new_owner":
            assert row.lease_owner == "successor-worker"
        elif failure == "expired":
            assert row.lease_expires_at < utc_now()
    assert snapshot(factory) == before_facts
    assert worker.failures == 1 and len(reports) == 1
    if failure in ("new_owner", "expired"):
        assert isinstance(reports[0], BillingRefused)
        assert reports[0].code == "subscription_reconciliation_busy"
    else:
        assert isinstance(reports[0], RuntimeError)
        assert str(reports[0]) == "retry commit acknowledgement failed"
    assert worker.last_progress_at == progress
    assert worker.last_verified_subscription_at == verified
    assert metrics.PROGRESS._value.get() == progress_signal
    assert metrics.LAST_PROOF._value.get() == proof_signal
    assert {key: value - counters[key] for key, value in attempts().items()} == {
        "completed": 0,
        "refused": 0,
        "failed": 1,
    }
