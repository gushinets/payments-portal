"""Final inventory failures preserve timely negatives without positive admission."""

from typing import Literal

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.errors import AppError
from app.domains.billing import background_recovery
from app.domains.billing.work_contracts import WorkLane
from app.infrastructure.preflight import PreflightBudget, PreflightCleanupPending, PreflightDeadlineExceeded
from app.integrations.lbx.errors import LbxResponseInvalid
from app.integrations.lbx.financial import Subscription
from app.jobs.billing import BillingWorker
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingWorkItem,
    ExternalSubscription,
    PurchasedAllowance,
)
from apps.api.tests.test_paid_access_postgres import effective, reconcile

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("failure", [None, LbxResponseInvalid, PreflightDeadlineExceeded, PreflightCleanupPending])
@pytest.mark.parametrize("state", ["unselected", "paid_positive", "paid_blocked", "paid_ended"])
async def test_final_inventory_failure_preserves_negative_without_admission_or_extension(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: type[AppError] | None,
    state: Literal["unselected", "paid_positive", "paid_blocked", "paid_ended"],
) -> None:
    factory = postgres_session_factory
    transport, sources, config, _, _ = paid_scenario
    await reconcile(
        paid_scenario,
        factory,
        config.model_copy(update={"paid_access_clock_skew_seconds": None}) if state == "unselected" else config,
    )
    before = effective(factory)
    with factory() as db:
        old_deadline = db.scalar(select(BillingProductAccessScope.effective_access_until))
    if state == "paid_blocked":
        transport.subscriptions[0]["current_blocking"] = 1
    elif state == "paid_ended":
        transport.subscriptions[0]["state"] = 3
    client = sources.require_lbx()
    original = client.discover_subscriptions
    calls = 0

    async def discover(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        nonlocal calls
        calls += 1
        if calls == 2 and failure is not None:
            raise failure()
        return await original(user_id=user_id, budget=budget)

    monkeypatch.setattr(client, "discover_subscriptions", discover)
    background_recovery.repair_batch(factory, config)
    worker = BillingWorker(config, factory, client)
    try:
        assert await worker.tick(WorkLane.NORMAL)
    finally:
        await worker.aclose()
    assert calls == 2
    with factory() as db:
        scope = db.scalars(select(BillingProductAccessScope)).one()
        queue = db.scalars(
            select(BillingWorkItem).where(BillingWorkItem.work_kind == background_recovery.INVENTORY)
        ).one()
        assert queue.work_state == "pending" and queue.lease_owner is None
        assert queue.last_error_classification == ("inventory_incomplete" if failure else None)
        count = db.scalar(select(func.count()).select_from(PurchasedAllowance))
        outbox = db.scalar(select(AccessInvalidationOutbox))
        if state in {"paid_blocked", "paid_ended"}:
            assert effective(factory) == (2, {"grants": [], "allowances": []})
            assert count == 1 and outbox.pending_revision == 2
            assert (scope.primary_subscription_id is None) == (state == "paid_ended")
        elif state == "paid_positive":
            assert effective(factory) == before
            assert count == 1 and outbox.pending_revision == 1
            if failure:
                assert scope.effective_access_until == old_deadline
            else:
                assert scope.effective_access_until >= old_deadline
        elif failure:
            assert effective(factory) == (0, {"grants": [], "allowances": []})
            assert scope.primary_subscription_id is None and count == 0 and outbox is None
        else:
            revision, document = effective(factory)
            assert revision == 1 and scope.primary_subscription_id is not None
            assert len(document["grants"]) == len(document["allowances"]) == count == 1
            assert document["allowances"][0]["quantity"] == 100 and outbox.pending_revision == 1


async def test_inventory_final_failure_still_rejects_stale_work_owner(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    transport, sources, config, _, _ = paid_scenario
    await reconcile(paid_scenario, factory)
    before = effective(factory)
    transport.subscriptions[0]["current_blocking"] = 1
    client = sources.require_lbx()
    original = client.discover_subscriptions
    calls = 0

    async def discover(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            with factory() as db:
                queue = db.scalars(
                    select(BillingWorkItem).where(BillingWorkItem.work_kind == background_recovery.INVENTORY)
                ).one()
                queue.lease_owner = "successor-owner"
                db.commit()
            raise LbxResponseInvalid()
        return await original(user_id=user_id, budget=budget)

    monkeypatch.setattr(client, "discover_subscriptions", discover)
    background_recovery.repair_batch(factory, config)
    worker = BillingWorker(config, factory, client)
    try:
        assert await worker.tick(WorkLane.NORMAL)
    finally:
        await worker.aclose()
    assert calls == 2 and effective(factory) == before
    with factory() as db:
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == 1
        assert db.scalar(select(ExternalSubscription.financial_access_status)).value == "allowed"


@pytest.mark.parametrize("deadline_check", [1, 2])
async def test_final_inventory_budget_check_cannot_drop_owned_negative(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    deadline_check: int,
) -> None:
    factory = postgres_session_factory
    transport, sources, config, _, _ = paid_scenario
    await reconcile(paid_scenario, factory)
    transport.subscriptions[0]["current_blocking"] = 1
    client = sources.require_lbx()
    original_discover = client.discover_subscriptions
    original_check = PreflightBudget.check
    calls, final_checks = 0, 0
    finished_final_read = False

    async def discover(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        nonlocal calls, finished_final_read
        calls += 1
        rows = await original_discover(user_id=user_id, budget=budget)
        if calls == 2:
            finished_final_read = True
        return rows

    def check(budget: PreflightBudget) -> None:
        nonlocal final_checks
        original_check(budget)
        if finished_final_read:
            final_checks += 1
            if final_checks == deadline_check:
                raise PreflightDeadlineExceeded()

    monkeypatch.setattr(client, "discover_subscriptions", discover)
    monkeypatch.setattr(PreflightBudget, "check", check)
    background_recovery.repair_batch(factory, config)
    worker = BillingWorker(config, factory, client)
    try:
        assert await worker.tick(WorkLane.NORMAL)
    finally:
        await worker.aclose()
    # Whether the budget expires after the read or stays valid through apply,
    # the timely owned block must produce the reducing revision.
    assert calls == 2
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    with factory() as db:
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == 2
