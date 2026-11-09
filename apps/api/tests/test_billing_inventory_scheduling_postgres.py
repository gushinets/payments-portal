"""Customer inventory urgency is a lane guarantee as well as a due-time bound."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.domains.billing.discovery import apply_inventory
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import service
from app.domains.purchases.inventory_contracts import InventoryResult
from app.infrastructure.persistence.billing_work import coalesce
from app.jobs.billing import BillingWorker
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    job,
    due,
    synthetic_prepare,
)
from apps.api.tests.test_any709_subscription_inventory_postgres import add_external_subscription

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("reason", ["incomplete", "conflict"])
async def test_inventory_moves_from_normal_to_urgent_with_bounded_due_time(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    reason: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    recovery.repair_batch(factory, config)
    if reason == "incomplete":
        transport.hide.add("/subscriptions")
        # Empty complete inventory is valid; an explicit failing point makes
        # this pass incomplete instead of inventing an absence conflict.
        transport.subscriptions[0]["services"] = None
    else:
        add_external_subscription(transport, -2)
    worker = BillingWorker(config, factory, sources.require_lbx())
    try:
        started = datetime.now(UTC)
        assert await worker.tick(WorkLane.NORMAL)
        row = job(factory, recovery.INVENTORY, purchase.customer_id)
        assert row.priority == 1 and row.work_state == "pending"
        assert started < row.next_attempt_at <= started + timedelta(seconds=work.URGENT_SECONDS)
        assert row.last_error_classification == "inventory_" + reason
        due(factory, recovery.INVENTORY, purchase.customer_id)
        assert not await worker.tick(WorkLane.NORMAL)
        assert await worker.tick(WorkLane.URGENT)
        assert job(factory, recovery.INVENTORY, purchase.customer_id).attempt_count == 2
    finally:
        await worker.aclose()


@pytest.mark.parametrize("new_hint", [False, True])
async def test_clean_inventory_preserves_new_generation_and_only_otherwise_demotes(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    new_hint: bool,
) -> None:
    _, _, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    recovery.repair_batch(factory, config)
    claim = work.claim_work(factory, config, WorkLane.NORMAL)
    assert claim and claim.kind == recovery.INVENTORY
    customer = service.customer_for_purchase(factory, config, purchase)
    result = InventoryResult(customer, (purchase,), (), (), True)
    if new_hint:
        with factory() as db:
            coalesce(
                db,
                kind=recovery.INVENTORY,
                key=f"{purchase.account_id}:{purchase.customer_id}",
                scope_kind="customer",
                reference=str(purchase.customer_id),
                due=datetime.now(UTC),
                priority=1,
                payload={},
                hint=True,
            )
            db.commit()
    apply_inventory(factory, claim, result, None)
    row = job(factory, recovery.INVENTORY, purchase.customer_id)
    assert row.priority == int(new_hint) and row.lease_owner is None
    if new_hint:
        assert row.enqueue_generation == claim.generation + 1
        assert row.next_attempt_at <= datetime.now(UTC)
    else:
        assert datetime.now(UTC) + timedelta(hours=4) < row.next_attempt_at <= datetime.now(UTC) + timedelta(hours=6)
