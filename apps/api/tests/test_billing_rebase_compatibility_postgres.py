"""ANY-709 customer-lock semantics through ANY-715's real worker path."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.domains.billing import work
from app.domains.billing.work_contracts import WorkLane
from app.jobs.billing import BillingWorker
from app.models import BillingWorkItem, ExternalBillingCustomer, ExternalSubscription
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_subscription_reconciliation_postgres import (
    activate,
    anyio_backend as anyio_backend,
    scenario as scenario,
    snapshot,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("phase", ["claim", "apply"])
async def test_customer_lock_contention_reschedules_worker_without_applying_facts(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    before = snapshot(factory)
    client = sources.require_lbx()
    original = client.get_subscription
    holder = factory()
    transport.pool = None  # This other transaction deliberately owns a row lock.

    def hold_customer() -> None:
        holder.scalar(
            select(ExternalBillingCustomer)
            .where(ExternalBillingCustomer.customer_id == purchase.customer_id)
            .with_for_update()
        )

    async def locked_read(**kwargs: object) -> object:
        point = await original(**kwargs)
        hold_customer()
        return point

    if phase == "claim":
        hold_customer()
    else:
        monkeypatch.setattr(client, "get_subscription", locked_read)
    worker = BillingWorker(step1_settings(), factory, client)
    try:
        try:
            assert await worker.tick(WorkLane.URGENT)
        finally:
            holder.close()
            monkeypatch.setattr(client, "get_subscription", original)
        assert snapshot(factory) == before
        assert worker.last_progress_at is not None and worker.last_verified_subscription_at is None
        with factory() as db:
            queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
            assert queue.work_state == "pending" and queue.lease_owner is None
            assert queue.last_error_classification == "billing_busy"
            # Advance the finite retry/claim leases without waiting in real time.
            queue.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            sub = db.get(ExternalSubscription, before[0])
            if sub.reconciliation_lease_expires_at is not None:
                sub.reconciliation_lease_expires_at = queue.next_attempt_at
            db.commit()
        assert await worker.tick(WorkLane.URGENT)
        after = snapshot(factory)
        assert after[2:4] == ("allowed", "eligible") and after[4] is not None
    finally:
        await worker.aclose()
