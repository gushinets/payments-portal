from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import event, select, text, update
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.composition.billing_background import inventory_customer
from app.composition.reconciliation import reconcile_subscription
from app.domains.billing import background_recovery, reconciliation as canonical_reconciliation, work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import lock_user
from app.domains.billing.discovery import apply_inventory, persist_discoveries
from app.domains.billing.inventory_history import (
    INVENTORY_RELATIONSHIP_SCHEMA,
    defer_inventory_relationship,
    retain_inventory_relationship,
    retained_subscription_relationships,
)
from app.domains.billing.reconciliation import apply_reconciliation
from app.domains.billing.reconciliation_contracts import ReadInterval, SubscriptionRelationship
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import service
from app.infrastructure.preflight import PreflightBudget
from app.infrastructure.queries import billing_reconciliation
from app.integrations.lbx.errors import LbxScopeForbidden, LbxUnavailable
from app.integrations.lbx.financial import Subscription
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalSubscription,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import background_scenario as background_scenario
from apps.api.tests.test_billing_scoped_inventory_postgres import (
    anyio_backend as anyio_backend,
    bound_point_relationship_scenario as bound_point_relationship_scenario,
    inventory,
)
from apps.api.tests.test_paid_access_rebase_postgres import claim_inventory, run_inventory
from apps.api.tests.test_paid_access_reconciliation_postgres import (
    Scenario,
    paid_source as paid_source,
    persisted,
    reconcile,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
@pytest.mark.parametrize("denied", [False, True], ids=["point-unavailable", "scope-denied"])
async def test_local_contention_does_not_lose_scope_refusal(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    denied: bool,
) -> None:
    transport, sources, first, second, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    transport.subscriptions[0]["tariff_id"] = 701
    first_id = service.linked_subscription_id(factory, first)
    second_id = service.linked_subscription_id(factory, second)
    read = sources.require_lbx().get_subscription

    async def unavailable(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxScopeForbidden() if denied else LbxUnavailable()
        return await read(subscription_id=subscription_id, budget=budget)

    seen = []

    async def delegate(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if fn is apply_reconciliation and args[1].subscription_id == first_id:
            seen.extend(args[2].reasons)
            with factory() as blocker:
                lock_user(blocker, first.user_id)
                with pytest.raises(BillingRefused, match="billing_busy") as error:
                    await run_in_threadpool(fn, *args, **kwargs)
                raise error.value
        return await run_in_threadpool(fn, *args, **kwargs)

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", unavailable)
    claim = claim_inventory(Scenario(factory, config, transport, sources, second_id))
    result = await inventory(sources, factory, first, claim=claim, delegate=delegate)
    assert ("subscription:lbx_scope_forbidden" in seen) == denied
    assert not result.complete
    apply_inventory(factory, claim, persist_discoveries(factory, claim, result), None, clock_skew_seconds=10)
    with factory() as db:
        primary = db.scalar(
            select(BillingProductAccessScope.primary_subscription_id).where(
                BillingProductAccessScope.product_id == second.accepted.selection.product_id
            )
        )
    assert primary == (None if denied else second_id)


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
@pytest.mark.parametrize("busy_attempts", [1, 2])
async def test_busy_relationship_write_retries_the_same_read_and_keeps_both_products_blocked(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    busy_attempts: int,
) -> None:
    transport, sources, first, second, third, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    third_id = service.linked_subscription_id(factory, third)
    scenario = Scenario(factory, config, transport, sources, third_id)
    claim = claim_inventory(scenario)
    intervals = []

    async def delegate(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if fn is retain_inventory_relationship and args[1].id == first.id:
            assert args[4].tariff_id == 702
            intervals.append(kwargs["interval"])
            if len(intervals) <= busy_attempts:
                with factory() as blocker:
                    lock_user(blocker, first.user_id)
                    with pytest.raises(BillingRefused, match="billing_busy") as error:
                        await run_in_threadpool(fn, *args, **kwargs)
                    raise error.value
        return await run_in_threadpool(fn, *args, **kwargs)

    result = await inventory(sources, factory, first, claim=claim, delegate=delegate)
    apply_inventory(factory, claim, persist_discoveries(factory, claim, result), None, clock_skew_seconds=10)
    with factory() as db:
        initial = {
            scope.product_id: scope.primary_subscription_id for scope in db.scalars(select(BillingProductAccessScope))
        }
    assert initial[second.accepted.selection.product_id] is None
    assert initial[third.accepted.selection.product_id] == third_id
    assert len(intervals) == 2 and intervals[0] == intervals[1]

    read = sources.require_lbx().get_subscription

    async def unavailable(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxUnavailable()
        return await read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", unavailable)
    await run_inventory(scenario)
    with factory() as db:
        after_retry = {
            scope.product_id: scope.primary_subscription_id for scope in db.scalars(select(BillingProductAccessScope))
        }
    assert after_retry == initial


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_retry_keeps_relationship_when_history_lock_also_refuses(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, first, second, third, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    third_id = service.linked_subscription_id(factory, third)
    scenario = Scenario(factory, config, transport, sources, third_id)
    clock = {"now": datetime.now(UTC)}
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock["now"])
    claim = claim_inventory(scenario)
    refusals = []

    with ExitStack() as locker:

        async def delegate(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            retention = fn is retain_inventory_relationship and args[1].id == first.id
            history = fn is retained_subscription_relationships and args[1].id == first.id
            if retention and not refusals:
                lock_user(locker.enter_context(factory()), first.user_id)
            if retention or history:
                with pytest.raises(BillingRefused, match="billing_busy") as error:
                    await run_in_threadpool(fn, *args, **kwargs)
                refusals.append(fn)
                raise error.value
            return await run_in_threadpool(fn, *args, **kwargs)

        async with sources.billing.operation(bound_scope=False) as budget:
            await inventory_customer(
                sources.require_lbx(),
                sources.billing,
                config,
                factory=factory,
                claim=claim,
                budget=budget,
                delegate=delegate,
            )
    assert refusals == [
        retain_inventory_relationship,
        retain_inventory_relationship,
        retained_subscription_relationships,
    ]
    with factory() as db:
        queued = db.get(BillingWorkItem, claim.id)
        assert queued.last_error_classification == "billing_busy"
        pending = queued.payload_document
        assert pending["deferred_relationships"][0]["point_relationship"]["tariff_id"] == 702

    read = sources.require_lbx().get_subscription
    refused_points = []

    async def unavailable(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            refused_points.append(subscription_id)
            raise LbxUnavailable()
        return await read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", unavailable)
    clock["now"] += timedelta(minutes=5)
    retry = claim_inventory(scenario)
    with factory() as db:
        assert db.get(BillingWorkItem, retry.id).payload_document == pending  # Re-enqueue must preserve the point.
    await run_inventory(scenario, retry)
    assert refused_points == [567]
    with factory() as db:
        scopes = {
            scope.product_id: scope.primary_subscription_id for scope in db.scalars(select(BillingProductAccessScope))
        }
        assert scopes[second.accepted.selection.product_id] is None
        assert scopes[third.accepted.selection.product_id] == third_id
        assert db.get(BillingWorkItem, retry.id).payload_document == {}


@pytest.mark.parametrize("bound_point_relationship_scenario", [False], indirect=True)
async def test_deferred_point_after_collection_blocks_only_implicated_products(
    bound_point_relationship_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, first, second, third, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    transport.subscriptions[0]["tariff_id"] = 701
    third_id = service.linked_subscription_id(factory, third)
    claim = claim_inventory(Scenario(factory, config, transport, sources, third_id))
    result = persist_discoveries(factory, claim, await inventory(sources, factory, first, claim=claim))
    assert result.complete and all(product.complete for product in result.products)
    history = next(item for item in result.point_history if item.purchase_id == first.id)
    with factory() as db:
        observed_at = billing_reconciliation.database_now(db)
    agreement = str(transport.subscriptions[0]["agreement_id"])
    defer_inventory_relationship(
        factory,
        first,
        history.subscription_id,
        history.fence,
        SubscriptionRelationship(agreement, 702),
        ReadInterval(observed_at, observed_at),
        None,
    )
    apply_inventory(factory, claim, result, None, clock_skew_seconds=10)
    with factory() as db:
        scopes = {
            scope.product_id: scope.primary_subscription_id for scope in db.scalars(select(BillingProductAccessScope))
        }
        assert scopes[second.accepted.selection.product_id] is None
        assert scopes[third.accepted.selection.product_id] == third_id
        assert db.get(BillingWorkItem, claim.id).payload_document["deferred_relationships"]


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_standalone_subscription_poll_defers_refused_relationship(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, first, second, third, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    first_id = service.linked_subscription_id(factory, first)
    third_id = service.linked_subscription_id(factory, third)
    scenario = Scenario(factory, config, transport, sources, third_id)
    clock = {"now": datetime.now(UTC)}
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock["now"])
    with factory() as db:
        db.execute(update(BillingWorkItem).values(next_attempt_at=clock["now"] + timedelta(days=1)))
        work.enroll_subscription(db, db.get(ExternalSubscription, first_id), hint=True)
        db.commit()
    claim = work.claim_work(factory, config, WorkLane.URGENT)
    assert claim is not None and claim.kind == work.RECONCILIATION and claim.reference == str(first_id)
    intervals = []

    with ExitStack() as locker:

        async def delegate(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
            if fn is retain_inventory_relationship:
                assert args[1].id == first.id and args[4].tariff_id == 702
                if not intervals:
                    lock_user(locker.enter_context(factory()), first.user_id)
                intervals.append(kwargs["interval"])
            return await run_in_threadpool(fn, *args, **kwargs)

        async with sources.billing.operation(bound_scope=False) as budget:
            with pytest.raises(BillingRefused, match="billing_busy"):
                await reconcile_subscription(
                    sources.require_lbx(),
                    sources.billing,
                    config,
                    factory=factory,
                    subscription_id=first_id,
                    work_claim=claim,
                    budget=budget,
                    delegate=delegate,
                )
            assert work.retry_work(factory, claim, error="billing_busy")
    assert len(intervals) == 2 and intervals[0] == intervals[1]

    read = sources.require_lbx().get_subscription
    refused_points = []

    async def unavailable(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            refused_points.append(subscription_id)
            raise LbxUnavailable()
        return await read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", unavailable)
    clock["now"] += timedelta(minutes=5)
    await run_inventory(scenario)
    assert refused_points == [567]
    with factory() as db:
        primaries = {
            scope.product_id: scope.primary_subscription_id for scope in db.scalars(select(BillingProductAccessScope))
        }
    assert primaries[third.accepted.selection.product_id] == third_id
    assert primaries[second.accepted.selection.product_id] is None


def latest_without_activation_bounds(scenario: Scenario, source_observation_id: UUID) -> UUID:
    """Seed the old v2 document shape without rewriting append-only evidence."""
    with scenario.factory() as db:
        legacy = db.scalar(
            text("""
                INSERT INTO billing_state_observations (
                    observation_id, observation_kind, external_billing_account_id, user_id, product_id,
                    access_scope_id, subscription_id, observed_at, evidence_schema_version, evidence_document,
                    completeness_classification, result_classification
                )
                SELECT gen_random_uuid(), observation_kind, external_billing_account_id, user_id, product_id,
                       access_scope_id, subscription_id, observed_at, evidence_schema_version,
                       evidence_document - 'activation_bounds', completeness_classification, result_classification
                  FROM billing_state_observations
                 WHERE observation_id = :source_observation_id
                RETURNING observation_id
            """),
            {"source_observation_id": source_observation_id},
        )
        assert legacy is not None
        db.get(ExternalSubscription, scenario.subscription_id).latest_observation_id = legacy
        db.commit()
        return legacy


@pytest.mark.parametrize("paid_source", ["annual_calendar_month"], indirect=True)
async def test_date_only_activation_history_bootstraps_outside_user_lock(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = paid_source
    clock = {"now": datetime(2026, 11, 30, 12, tzinfo=UTC)}
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock["now"])
    scenario.transport.subscriptions[0].update(
        subscription_start_date="2026-11-18 00:00:00",
        subscription_instance_start_date="2026-11-18 00:00:00",
        subscription_end_date="2027-11-17 23:59:59",
        subscription_instance_end_date="2027-11-17 23:59:59",
        last_tariffication_period_start="2026-11-01",
        last_tariffication_period_end="2027-10-31",
    )
    first = await reconcile(scenario)
    assert first.proof.complete and first.proof.calendar_complete
    assert first.proof.cycle.precision == "date"
    first_state = persisted(scenario.factory)[2:5]
    assert len(first_state[0][1]["allowances"]) == 1
    latest_without_activation_bounds(scenario, first.observation_id)
    engine = scenario.factory.kw["bind"]
    in_user_lock = set()
    lookups = []

    def before(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool) -> None:
        if "FROM users" in statement and "FOR UPDATE" in statement:
            in_user_lock.add(conn)
        if " ~ " in statement and "billing_state_observations" in statement:
            lookups.append(conn in in_user_lock)

    def done(conn: Any) -> None:
        in_user_lock.discard(conn)

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "commit", done)
    event.listen(engine, "rollback", done)
    try:
        clock["now"] += timedelta(minutes=15)
        await reconcile(scenario)
        bootstrap = tuple(lookups)
        lookups.clear()
        for _ in range(2):
            clock["now"] += timedelta(minutes=15)
            await reconcile(scenario)
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "commit", done)
        event.remove(engine, "rollback", done)
    assert bootstrap and not any(bootstrap)
    assert lookups == []
    assert persisted(scenario.factory)[2:5] == first_state


@pytest.mark.parametrize("paid_source", ["calendar_month"], indirect=True)
async def test_activation_basis_change_before_user_lock_refuses_apply(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = paid_source
    clock = {"now": datetime.now(UTC) + timedelta(minutes=1)}
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock["now"])
    first = await reconcile(scenario)
    before = persisted(scenario.factory)[2:5]
    load_basis = canonical_reconciliation.retained_activation_bounds
    changed = []

    def switch_basis(*args: Any, **kwargs: Any):
        bounds = load_basis(*args, **kwargs)
        changed.append(latest_without_activation_bounds(scenario, first.observation_id))
        return bounds

    monkeypatch.setattr(canonical_reconciliation, "retained_activation_bounds", switch_basis)
    clock["now"] += timedelta(minutes=15)
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        await reconcile(scenario)
    assert len(changed) == 1
    assert persisted(scenario.factory)[2:5] == before


@pytest.mark.parametrize("paid_source", ["annual_calendar_month"], indirect=True)
@pytest.mark.parametrize("partial", [False, True], ids=["date-only", "missing-instance-start"])
async def test_first_calendar_quota_waits_for_a_fresh_read_after_exact_activation(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch, partial: bool
) -> None:
    scenario = paid_source
    clock = {"now": datetime(2026, 12, 12, 12, tzinfo=UTC)}
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock["now"])
    point = scenario.transport.subscriptions[0]
    zoned = dict(
        subscription_start_date="2026-12-02T00:00:00+03:00",
        subscription_instance_start_date="2026-12-18T00:00:00+03:00",
        subscription_end_date="2027-12-17T23:59:59+03:00",
        subscription_instance_end_date="2027-12-17T23:59:59+03:00",
        last_tariffication_period_start="2026-12-01T00:00:00+03:00",
        last_tariffication_period_end="2027-12-01T00:00:00+03:00",
    )
    point.update(zoned)
    first = await reconcile(scenario)
    assert first.proof.complete
    before_activation = persisted(scenario.factory)
    assert before_activation[2][1]["allowances"] == [] and len(before_activation[4]) == 1
    activation = datetime(2026, 12, 17, 21, tzinfo=UTC)
    # A less precise but otherwise valid calendar read must not bypass the wait.
    if partial:
        del point["subscription_instance_start_date"]
    else:
        point.update(
            subscription_start_date="2026-12-02 00:00:00",
            subscription_instance_start_date="2026-12-18 00:00:00",
            subscription_end_date="2027-12-17 23:59:59",
            subscription_instance_end_date="2027-12-17 23:59:59",
            last_tariffication_period_start="2026-12-01",
            last_tariffication_period_end="2027-11-30",
        )
    clock["now"] = activation - timedelta(seconds=30)
    claim = work.claim_work(scenario.factory, scenario.config, WorkLane.URGENT)
    assert claim is not None and claim.kind == work.RECONCILIATION
    await reconcile_subscription(
        scenario.sources.require_lbx(),
        scenario.sources.billing,
        scenario.config,
        factory=scenario.factory,
        subscription_id=scenario.subscription_id,
        work_claim=claim,
    )
    assert persisted(scenario.factory)[2][1]["allowances"] == []
    with scenario.factory() as db:
        assert db.get(BillingWorkItem, claim.id).next_attempt_at == activation + timedelta(seconds=10)

    point.update(zoned)
    clock["now"] = activation + timedelta(seconds=10)
    await reconcile(scenario)
    issued = persisted(scenario.factory)
    assert len(issued[2][1]["allowances"]) == 1
    assert issued[4] == before_activation[4]
    for field, value in zoned.items():
        point[field] = datetime.fromisoformat(value).astimezone(UTC).isoformat()
    clock["now"] += timedelta(minutes=1)
    await reconcile(scenario)
    assert persisted(scenario.factory)[2:5] == issued[2:5]


@pytest.mark.parametrize("paid_source", ["annual_calendar_month"], indirect=True)
async def test_first_primary_uses_exact_calendar_from_existing_v2_observation(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = paid_source
    clock = {"now": datetime(2026, 12, 12, 12, tzinfo=UTC)}
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock["now"])
    with scenario.factory() as db:
        db.scalars(select(BillingProductAccessScope)).one().primary_subscription_id = None
        db.commit()
    point = scenario.transport.subscriptions[0]
    point.update(
        subscription_start_date="2026-12-02T00:00:00+03:00",
        subscription_instance_start_date="2026-12-18T00:00:00+03:00",
        subscription_end_date="2027-12-17T23:59:59+03:00",
        subscription_instance_end_date="2027-12-17T23:59:59+03:00",
        last_tariffication_period_start="2026-12-01T00:00:00+03:00",
        last_tariffication_period_end="2027-12-01T00:00:00+03:00",
    )
    first = await reconcile(scenario)
    legacy = latest_without_activation_bounds(scenario, first.observation_id)
    with scenario.factory() as db:
        document = db.get(BillingStateObservation, legacy).evidence_document
        assert "activation_bounds" not in document
        assert document["calendar"]["subscription_instance_start_date"] == "2026-12-18T00:00:00+03:00"
        db.execute(
            update(BillingWorkItem)
            .where(BillingWorkItem.work_kind != background_recovery.INVENTORY)
            .values(next_attempt_at=clock["now"] + timedelta(days=1))
        )
        background_recovery.hint_inventory(db, db.scalars(select(ExternalBillingCustomer)).one())
        db.commit()
    point.update(
        subscription_start_date="2026-12-02 00:00:00",
        subscription_instance_start_date="2026-12-18 00:00:00",
        subscription_end_date="2027-12-17 23:59:59",
        subscription_instance_end_date="2027-12-17 23:59:59",
        last_tariffication_period_start="2026-12-01",
        last_tariffication_period_end="2027-11-30",
    )
    clock["now"] += timedelta(minutes=2)
    claim = work.claim_work(scenario.factory, scenario.config, WorkLane.URGENT)
    assert claim and claim.kind == background_recovery.INVENTORY
    await run_inventory(scenario, claim)
    state = persisted(scenario.factory)
    assert state[1][0] == scenario.subscription_id
    assert state[2][1]["grants"] and state[2][1]["allowances"] == []


async def test_latest_authoritative_read_limits_history_before_compaction(paid_source: Scenario) -> None:
    scenario = paid_source
    source = await reconcile(scenario)
    assert source.proof.complete and source.proof.point_relationship is not None
    engine = scenario.factory.kw["bind"]
    queries = []

    def inspect_sql(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        if "UNION ALL" in statement and "point_relationship" in parameters.values():
            queries.append((statement, parameters))

    event.listen(engine, "before_cursor_execute", inspect_sql)
    try:
        history = retained_subscription_relationships(scenario.factory, source.purchase)
    finally:
        event.remove(engine, "before_cursor_execute", inspect_sql)
    assert history.relationships == (source.proof.point_relationship,)
    assert len(queries) == 1
    statement, parameters = queries[0]
    assert source.proof.read_started_at in parameters.values()
    assert statement.count("observed_at >=") == 2  # Both branches exclude the superseded history in SQL.


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_apply_reads_each_history_once_and_does_not_load_repeated_restrictions(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, first, _, third, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    client = sources.require_lbx()
    read = client.get_tariff

    async def unavailable_policy(*, tariff_id: int, budget: PreflightBudget) -> Any:
        if tariff_id == 701:
            raise LbxUnavailable()
        return await read(tariff_id=tariff_id, budget=budget)

    monkeypatch.setattr(client, "get_tariff", unavailable_policy)
    first_id = service.linked_subscription_id(factory, first)
    third_id = service.linked_subscription_id(factory, third)
    claim = claim_inventory(Scenario(factory, config, transport, sources, third_id))
    result = persist_discoveries(factory, claim, await inventory(sources, factory, first, claim=claim))
    with factory() as db:
        saved = db.scalar(
            select(BillingStateObservation).where(
                BillingStateObservation.subscription_id == first_id,
                BillingStateObservation.evidence_schema_version == INVENTORY_RELATIONSHIP_SCHEMA,
            )
        )
        assert saved is not None and saved.evidence_document["complete"] is False
        db.execute(
            text("""
                INSERT INTO billing_state_observations (
                    observation_id, observation_kind, external_billing_account_id, user_id, product_id,
                    access_scope_id, subscription_id, observed_at, evidence_schema_version, evidence_document,
                    completeness_classification, result_classification
                )
                SELECT gen_random_uuid(), o.observation_kind, o.external_billing_account_id, o.user_id, o.product_id,
                       o.access_scope_id, o.subscription_id, earlier.finished_at, o.evidence_schema_version,
                       jsonb_set(
                         jsonb_set(o.evidence_document, '{read_started_at}', to_jsonb(earlier.finished_at - interval '1 second')),
                         '{read_finished_at}', to_jsonb(earlier.finished_at)
                       ),
                       o.completeness_classification, o.result_classification
                  FROM billing_state_observations o
                 CROSS JOIN LATERAL (
                    SELECT o.observed_at - n * interval '150 seconds' AS finished_at
                      FROM generate_series(1, 10000) n
                 ) earlier
                 WHERE o.observation_id = :original
            """),
            {"original": saved.observation_id},
        )
        db.commit()

    reads = []
    loaded = []
    engine = factory.kw["bind"]

    def inspect_sql(conn: Any, cursor: Any, statement: str, parameters: Any, context: Any, executemany: bool) -> None:
        if "UNION ALL" in statement and isinstance(parameters, dict) and "point_relationship" in parameters.values():
            if first_id in parameters.values():
                reads.append(statement)

    def inspect_load(session: Session, row: object) -> None:
        if (
            isinstance(row, BillingStateObservation)
            and row.subscription_id == first_id
            and row.evidence_schema_version == INVENTORY_RELATIONSHIP_SCHEMA
        ):
            loaded.append(row.observation_id)

    event.listen(engine, "before_cursor_execute", inspect_sql)
    event.listen(factory, "loaded_as_persistent", inspect_load)
    try:
        apply_inventory(factory, claim, result, None, clock_skew_seconds=10)
    finally:
        event.remove(engine, "before_cursor_execute", inspect_sql)
        event.remove(factory, "loaded_as_persistent", inspect_load)
    with factory() as db:
        selected = db.scalar(
            select(BillingProductAccessScope.primary_subscription_id).where(
                BillingProductAccessScope.product_id == third.accepted.selection.product_id
            )
        )
    assert selected == third_id
    assert len(reads) == len(loaded) == 1
