"""Later inventory I/O and stale completion cannot undo committed owned negatives."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domains.billing.discovery import apply_inventory
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.discovery import persist_discoveries
from app.domains.billing.work_contracts import WorkClaim
from app.domains.purchases.inventory_contracts import InventoryStale
from app.infrastructure.preflight import PreflightBudget, PreflightCleanupPending, PreflightDeadlineExceeded
from app.integrations.lbx.errors import LbxResponseInvalid
from app.integrations.lbx.financial import Subscription
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind as ObservationKind,
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalSubscription,
    PurchasedAllowance,
)
from apps.api.tests.test_paid_access_rebase_postgres import (
    claim_inventory,
    collect,
    effective,
    inventory_scenario as inventory_scenario,
    paid_source as paid_source,
    run_inventory,
)
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario
from apps.api.tests.test_any709_subscription_inventory_postgres import add_external_subscription

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def assert_denied(scenario: Scenario, allowance_id: str) -> None:
    assert effective(scenario.factory) == (2, {"grants": [], "allowances": []})
    with scenario.factory() as db:
        assert db.get(ExternalSubscription, scenario.subscription_id).financial_access_status == "blocked"
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == 2
        allowance = db.scalars(select(PurchasedAllowance)).one()
        assert str(allowance.allowance_id) == allowance_id
        cause = db.scalars(
            select(BillingStateObservation).where(BillingStateObservation.resulting_access_revision == 2)
        ).one()
        assert cause.observation_kind == "authoritative_subscription_read"


@pytest.mark.parametrize("foreign_first", [False, True])
@pytest.mark.parametrize("failure", [LbxResponseInvalid, PreflightDeadlineExceeded, PreflightCleanupPending])
async def test_next_point_failure_sees_owned_block_already_committed(
    inventory_scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    foreign_first: bool,
    failure: type[Exception],
) -> None:
    scenario = inventory_scenario
    await run_inventory(scenario)
    allowance_id = effective(scenario.factory)[1]["allowances"][0]["allowance_id"]
    scenario.transport.subscriptions[0]["current_blocking"] = 1
    add_external_subscription(scenario.transport, 2)
    if foreign_first:
        scenario.transport.subscriptions.reverse()
    client = scenario.sources.require_lbx()
    read = client.get_subscription
    failed = False

    async def next_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        nonlocal failed
        if subscription_id == 9999:
            # This is the next point after the owned object's committed read/apply.
            assert_denied(scenario, allowance_id)
            failed = True
            raise failure()
        return await read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(client, "get_subscription", next_point)
    await run_inventory(scenario)
    assert failed
    assert_denied(scenario, allowance_id)


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("failure", [LbxResponseInvalid, PreflightDeadlineExceeded, PreflightCleanupPending])
async def test_final_list_failure_forbids_first_primary_and_preserves_owned_negative(
    inventory_scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    selected: bool,
    failure: type[Exception],
) -> None:
    scenario = inventory_scenario
    allowance_id = None
    if selected:
        await run_inventory(scenario)
        allowance_id = effective(scenario.factory)[1]["allowances"][0]["allowance_id"]
        scenario.transport.subscriptions[0]["current_blocking"] = 1
    client = scenario.sources.require_lbx()
    discover = client.discover_subscriptions
    calls = 0

    async def final_list(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            if selected:
                assert_denied(scenario, allowance_id)
            raise failure()
        return await discover(user_id=user_id, budget=budget)

    monkeypatch.setattr(client, "discover_subscriptions", final_list)
    await run_inventory(scenario)
    assert calls == 2
    if selected:
        assert_denied(scenario, allowance_id)
    else:
        assert effective(scenario.factory)[0] == 0
        with scenario.factory() as db:
            assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) is None
            assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0


@pytest.mark.parametrize("selected", [False, True])
async def test_membership_change_cannot_admit_primary_or_undo_owned_block(
    inventory_scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    selected: bool,
) -> None:
    scenario = inventory_scenario
    if selected:
        await run_inventory(scenario)
        allowance_id = effective(scenario.factory)[1]["allowances"][0]["allowance_id"]
        scenario.transport.subscriptions[0]["current_blocking"] = 1
    client = scenario.sources.require_lbx()
    discover = client.discover_subscriptions
    calls = 0

    async def changed(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            add_external_subscription(scenario.transport, 2)
        return await discover(user_id=user_id, budget=budget)

    monkeypatch.setattr(client, "discover_subscriptions", changed)
    await run_inventory(scenario)
    assert calls == 2
    if selected:
        assert_denied(scenario, allowance_id)
    else:
        assert effective(scenario.factory)[0] == 0
        with scenario.factory() as db:
            assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) is None


@pytest.mark.parametrize("selected", [False, True])
async def test_lost_inventory_claim_keeps_earlier_negative_and_cannot_select(
    inventory_scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    selected: bool,
) -> None:
    scenario = inventory_scenario
    if selected:
        await run_inventory(scenario)
        allowance_id = effective(scenario.factory)[1]["allowances"][0]["allowance_id"]
        scenario.transport.subscriptions[0]["current_blocking"] = 1
    claim = claim_inventory(scenario)
    client = scenario.sources.require_lbx()
    discover = client.discover_subscriptions
    calls = 0

    async def lost(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        nonlocal calls
        calls += 1
        if calls == 2:
            with scenario.factory() as db:
                db.get(BillingWorkItem, claim.id).lease_owner = "successor-owner"
                db.commit()
            raise LbxResponseInvalid()
        return await discover(user_id=user_id, budget=budget)

    monkeypatch.setattr(client, "discover_subscriptions", lost)
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        await run_inventory(scenario, claim)
    if selected:
        assert_denied(scenario, allowance_id)
    else:
        assert effective(scenario.factory)[0] == 0
        with scenario.factory() as db:
            assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) is None
    with scenario.factory() as db:
        assert db.get(BillingWorkItem, claim.id).lease_owner == "successor-owner"


async def test_new_hint_survives_and_invalidates_first_selection_generation(inventory_scenario: Scenario) -> None:
    scenario = inventory_scenario
    claim = claim_inventory(scenario)
    result = persist_discoveries(scenario.factory, claim, await collect(scenario, claim))
    with scenario.factory() as db:
        recovery.hint_inventory(db, db.scalar(select(ExternalBillingCustomer)))
        db.commit()
    with pytest.raises(InventoryStale):
        apply_inventory(scenario.factory, claim, result, None, clock_skew_seconds=10)
    assert work.retry_work(scenario.factory, claim, error="inventory_incomplete")
    assert effective(scenario.factory)[0] == 0
    with scenario.factory() as db:
        job = db.get(BillingWorkItem, claim.id)
        assert job.work_state == "pending" and job.priority == 1 and job.enqueue_generation > claim.generation


async def test_late_claim_failure_rolls_back_primary_allowance_revision_and_outbox(
    inventory_scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = inventory_scenario
    claim = claim_inventory(scenario)
    result = persist_discoveries(scenario.factory, claim, await collect(scenario, claim))
    calls = 0

    def stale_after_write(db: Session, current: WorkClaim) -> BillingWorkItem:
        nonlocal calls
        calls += 1
        assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) == scenario.subscription_id
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == 1
        raise BillingRefused("billing_work_stale", 409)

    monkeypatch.setattr(work, "verify_claim", stale_after_write)
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        apply_inventory(scenario.factory, claim, result, None, clock_skew_seconds=10)
    assert calls == 1 and effective(scenario.factory)[0] == 0
    with scenario.factory() as db:
        assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) is None
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillingStateObservation)
                .where(BillingStateObservation.observation_kind == ObservationKind.PRIMARY_SELECTION)
            )
            == 0
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillingStateObservation)
                .where(BillingStateObservation.evidence_schema_version == "target-product-discovery:v3")
            )
            == 1
        )


@pytest.mark.parametrize("foreign_first", [False, True])
async def test_immediate_next_point_after_owned_apply_can_fail_without_losing_block(
    inventory_scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    foreign_first: bool,
) -> None:
    scenario = inventory_scenario
    await run_inventory(scenario)
    allowance_id = effective(scenario.factory)[1]["allowances"][0]["allowance_id"]
    scenario.transport.subscriptions[0]["current_blocking"] = 1
    add_external_subscription(scenario.transport, 2)
    if foreign_first:
        scenario.transport.subscriptions.reverse()
    client = scenario.sources.require_lbx()
    read = client.get_user
    calls = 0

    async def immediate_next(**kwargs: object) -> object:
        nonlocal calls
        calls += 1
        if calls == 2:
            # The first user read belongs to owned reconciliation. This next
            # point starts only after its complete source/paid transaction.
            assert_denied(scenario, allowance_id)
            raise LbxResponseInvalid()
        return await read(**kwargs)

    monkeypatch.setattr(client, "get_user", immediate_next)
    await run_inventory(scenario)
    assert calls == 2
    assert_denied(scenario, allowance_id)
