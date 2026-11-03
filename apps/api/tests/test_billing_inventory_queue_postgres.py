"""Worker acknowledgement and inventory priority use actual persisted claims."""

from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.core.time import utc_now
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import service
from app.infrastructure import billing_worker_metrics as metrics
from app.infrastructure.persistence.billing_work import coalesce
from app.jobs.billing import BillingWorker
from app.models import BillingWorkItem
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    synthetic_prepare,
    job,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("kind", [recovery.RECOVERY, recovery.INVENTORY])
@pytest.mark.parametrize("stale", ["expired", "superseded"])
async def test_late_recovery_inventory_apply_never_reports_unacknowledged_progress(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    stale: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=kind == recovery.RECOVERY)
    if kind == recovery.INVENTORY:
        recovery.repair_batch(factory, config)
    before_purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    lane = WorkLane.URGENT if kind == recovery.RECOVERY else WorkLane.NORMAL
    client, read = sources.require_lbx(), sources.require_lbx().get_subscription

    async def late_read(**kwargs: object) -> object:
        result = await read(**kwargs)
        with factory() as db:
            row = db.scalars(
                select(BillingWorkItem).where(
                    BillingWorkItem.work_kind == kind, BillingWorkItem.work_state == "running"
                )
            ).one()
            if stale == "expired":
                row.lease_expires_at = utc_now() - timedelta(seconds=1)
            else:
                row.lease_owner = "successor-worker"
            db.commit()
        return result

    monkeypatch.setattr(client, "get_subscription", late_read)
    counter = metrics.ATTEMPTS.labels(lane=lane.value, outcome="completed")
    before, signal = counter._value.get(), metrics.PROGRESS._value.get()
    worker = BillingWorker(config, factory, client)
    try:
        with pytest.raises(BillingRefused, match="billing_work_stale"):
            await worker.tick(lane)
        assert counter._value.get() == before and metrics.PROGRESS._value.get() == signal
        assert worker.last_progress_at is None
        assert service.read_purchase(factory, purchase.user_id, purchase.id) == before_purchase
    finally:
        await worker.aclose()


@pytest.mark.parametrize("failure", ["incomplete", "conflict", "source_error"])
async def test_inventory_failure_uses_urgent_capacity_then_clean_pass_returns_to_normal(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], failure: str
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    synthetic_prepare(factory, transport, purchase, uncertain=False)
    recovery.repair_batch(factory, config)
    if failure == "conflict":
        transport.subscriptions.append({**transport.subscriptions[0], "subscription_id": 999})
    elif failure == "incomplete":
        transport.subscriptions[0]["state"] = None
    else:
        transport.customer["outer_id"], original_key = None, transport.customer["outer_id"]
    worker = BillingWorker(config, factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.NORMAL)
        queue = job(factory, recovery.INVENTORY, purchase.customer_id)
        assert queue.priority == 1 and queue.work_state == "pending"
        assert queue.last_error_classification == (
            "inventory_conflict" if failure == "conflict" else "inventory_incomplete"
        )
        assert queue.next_attempt_at <= queue.last_attempt_started_at + timedelta(minutes=5)
        # Park unrelated subscription work to inspect this customer's queue routing.
        with factory() as db:
            for other in db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_item_id != queue.work_item_id)):
                other.next_attempt_at = utc_now() + timedelta(days=1)
            db.get(BillingWorkItem, queue.work_item_id).next_attempt_at = utc_now() - timedelta(seconds=1)
            db.commit()
        assert work.claim_work(factory, config, WorkLane.NORMAL) is None
        if failure == "conflict":
            transport.subscriptions.pop()
        elif failure == "incomplete":
            transport.subscriptions[0]["state"] = 2
        else:
            transport.customer["outer_id"] = original_key
        assert await worker.tick(WorkLane.URGENT)
        queue = job(factory, recovery.INVENTORY, purchase.customer_id)
        assert queue.priority == 0 and queue.last_error_classification is None
        assert queue.next_attempt_at > utc_now() + timedelta(hours=4)
    finally:
        await worker.aclose()


async def test_clean_inventory_preserves_new_hint_urgency(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, _, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    synthetic_prepare(factory, transport, purchase, uncertain=False)
    recovery.repair_batch(factory, config)
    claim = work.claim_work(factory, config, WorkLane.NORMAL)
    assert claim is not None and claim.kind == recovery.INVENTORY
    with factory() as db:
        queue = db.get(BillingWorkItem, claim.id)
        coalesce(
            db,
            kind=recovery.INVENTORY,
            key=queue.coalescing_key,
            scope_kind=queue.scope_kind,
            reference=queue.scope_reference,
            due=utc_now(),
            priority=1,
            payload={},
            hint=True,
        )
        db.commit()
    recovery.apply_inventory(factory, claim, (), None)
    queue = job(factory, recovery.INVENTORY, purchase.customer_id)
    assert queue.priority == 1 and queue.enqueue_generation == claim.generation + 1
    assert queue.work_state == "pending" and queue.next_attempt_at <= utc_now()
