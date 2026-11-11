"""B10 production-shaped authority on real PostgreSQL, with intercepted sources.

CONFIGURED_SOURCE fixtures approve neither a real offer nor live LBX access.
"""

import asyncio
from calendar import monthrange
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from threading import Event, Lock
from uuid import UUID, uuid4

import httpx
import anyio
import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.composition import paid_reads, purchases
from app.composition.reconciliation import reconcile_subscription
from app.composition.sources import source_resources
from app.core.observability import request_id_context
from app.core.backend_consumers import BackendPermission
from apps.api.tests.support.backend_consumers import backend_consumer
from app.domains.billing import paid_access, paid_read, snapshot_router, work
from app.domains.billing.customers import lock_user
from app.domains.billing.paid_access import commit_paid_state
from app.domains.billing.paid_contracts import EffectiveAllowance
from app.domains.billing.work_contracts import WorkLane
from app.domains.identity.services.auth import as_utc
from app.http import backend_auth
from app.infrastructure.preflight import PreflightCleanupPending
from app.infrastructure.queries import billing_reconciliation
from app.main import create_app
from app.models import (
    AuthSession,
    BillingProductAccessScope,
    BillingWorkItem,
    BillingWorkState,
    ExternalSubscription,
    PurchasedAllowance,
)
from apps.api.tests.factories.paid_access import reader_identity
from apps.api.tests.factories.paid_runtime import paid_scenario as paid_scenario, paid_source as paid_source, reconcile
from apps.api.tests.factories.purchase_terms import reviewed_meaning
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.paid_contracts import validate_contract
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed
from apps.api.tests.test_any766_purchase_terms_postgres import configured_manifest, publish
from apps.api.tests.test_paid_access_read_postgres import billing_snapshot
from apps.api.tests.test_paid_access_rebase_postgres import run_inventory
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario, persisted

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
SERVICE = "synthetic-snapshot-service-" + "s" * 32
PREVIOUS = "synthetic-snapshot-previous-" + "p" * 32


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def production_scenario(
    migrated_database: object,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> AsyncIterator[tuple]:
    factory = postgres_session_factory
    seed(factory)
    transport = PurchaseTransport()
    transport.pool = factory.kw["bind"].pool
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, tzinfo=UTC))
    await publish(factory, transport, quantity=getattr(request, "param", 7))
    config = step1_settings(
        app_env="production",
        app_public_base_url="https://portal.example.test",
        cors_allow_origins=("https://portal.example.test",),
        kernel_base_url="https://kernel.example.test",
        kernel_mock_enabled=False,
        paid_access_clock_skew_seconds=5,
    )
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=configured_manifest())),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, documents, terms = await purchases.review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
        purchase = await purchases.confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="production-snapshot",
            meaning=reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms),
        )
        await purchases.advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        with factory() as db:
            sub = db.scalars(select(ExternalSubscription)).one()
            db.add(
                BillingProductAccessScope(
                    user_id=sub.user_id, product_id=sub.product_id, primary_subscription_id=sub.subscription_id
                )
            )
            identity = sub.subscription_id
            db.commit()
        transport.subscriptions[0].update(
            state=2,
            subscription_start_date="2026-10-01",
            subscription_instance_start_date="2026-01-31",
            last_tariffication_period_start="2026-10-31",
            last_tariffication_period_end="2026-11-29",
        )
        yield transport, sources, config, identity, purchase.user_id


@pytest.fixture
async def snapshot_client(
    postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    config = step1_settings(paid_access_clock_skew_seconds=5).model_copy(
        update={
            "app_env": "production",
            "backend_consumers": (
                backend_consumer(
                    backend_to_portal_current_secret=SERVICE,
                    backend_to_portal_previous_secret=PREVIOUS,
                    permissions=[BackendPermission.READ_SNAPSHOT],
                ),
            ),
        }
    )
    monkeypatch.setattr(snapshot_router, "settings", config)
    monkeypatch.setattr(backend_auth, "settings", config)
    app = create_app()
    # No source/worker dependency is installed in this HTTP application.
    async with (
        paid_reads.paid_read_resources(config, factory=postgres_session_factory) as reads,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client,
    ):
        app.state.paid_reads = reads
        yield client


def path(user_id: UUID) -> str:
    return f"/internal/v1/access-snapshots/{user_id}?tenant_id=anytoolai&region=ru"


def headers(token: str = SERVICE) -> dict[str, str]:
    return {"Authorization": "Bearer " + token, "X-Request-ID": "synthetic-snapshot"}


def test_snapshot_openapi_has_required_scope_and_exact_v2_component_fields() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/internal/v1/access-snapshots/{user_id}"]["get"]
    assert {(item["name"], item["in"]) for item in operation["parameters"] if item["required"]} == {
        ("user_id", "path"),
        ("tenant_id", "query"),
        ("region", "query"),
    }
    response = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert response == {"$ref": "#/components/schemas/AccessSnapshotResponse"}
    for status in (401, 403, 404, 422, 503):
        assert operation["responses"][str(status)]["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/BackendErrorResponse"
        }
    for name in ("AccessSnapshotResponse", "AccessSnapshotGrant", "AccessSnapshotAllowance"):
        component = schema["components"]["schemas"][name]
        assert set(component["required"]) == set(component["properties"])
        assert component["additionalProperties"] is False


async def test_snapshot_known_zero_auth_scope_rotation_and_read_only(
    migrated_database: object,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    with factory() as db:
        user, auth = reader_identity(TOKEN)
        foreign, foreign_auth = reader_identity("foreign", tenant="foreign")
        db.add_all([user, foreign])
        db.flush()
        db.add_all([auth, foreign_auth])
        db.commit()
        user_id, foreign_id = user.id, foreign.id
        auth_before = list(db.execute(select(AuthSession)).scalars())[0].last_seen_at
    before = billing_snapshot(factory)
    writes: list[str] = []

    def observe(conn: object, cursor: object, statement: str, *args: object) -> None:
        if statement.lstrip().split()[0].upper() in {"INSERT", "UPDATE", "DELETE"}:
            writes.append(statement)

    engine = factory.kw["bind"]
    event.listen(engine, "before_cursor_execute", observe)
    try:
        for credential in (SERVICE, PREVIOUS):
            response = await snapshot_client.get(path(user_id), headers=headers(credential))
            assert response.status_code == 200
            validate_contract("snapshot-v2", response.text)
            body = response.json()
            assert (body["access_revision"], body["grants"], body["allowances"]) == (0, [], [])
            assert body["user_id"] == str(user_id)
            assert response.headers["cache-control"] == "no-store"
        cases = [
            (path(user_id), {}, 401),
            (path(user_id), headers(TOKEN), 401),
            (path(user_id), [("Authorization", "Bearer " + SERVICE)] * 2, 401),
            (path(user_id), {**headers(), "Origin": "https://portal.example.test"}, 403),
            (path(user_id).replace("region=ru", "region=us"), headers(), 403),
            (path(user_id) + "&region=ru", headers(), 403),
            (path(user_id).split("?")[0], headers(), 422),
            (path(user_id) + "&extra=x", headers(), 422),
            (path(uuid4()), headers(), 404),
            (path(foreign_id), headers(), 404),
            (path(user_id).replace(str(user_id), "invalid-uuid"), headers(), 422),
        ]
        for url, authorization, expected in cases:
            result = await snapshot_client.get(url, headers=authorization)
            assert result.status_code == expected, result.text
            assert result.headers["cache-control"] == "no-store"
        monkeypatch.setattr(
            backend_auth,
            "settings",
            backend_auth.settings.model_copy(
                update={
                    "backend_consumers": (backend_consumer(backend_to_portal_current_secret=SERVICE, permissions=[]),)
                }
            ),
        )
        assert (await snapshot_client.get(path(user_id), headers=headers())).status_code == 403
        assert not writes
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert billing_snapshot(factory) == before
    with factory() as db:
        assert db.get(AuthSession, auth.id).last_seen_at == auth_before


@pytest.mark.parametrize("production_scenario", [0, 7, 2**53 - 1], indirect=True)
async def test_production_snapshot_revision_noop_block_and_same_cycle_recovery(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
) -> None:
    factory = postgres_session_factory
    scenario = production_scenario
    transport, _, _, _, user_id = scenario
    await reconcile(scenario, factory)
    first = await snapshot_client.get(path(user_id), headers=headers())
    assert first.status_code == 200
    validate_contract("snapshot-v2", first.text)
    body = first.json()
    assert body["access_revision"] == 1 and len(body["allowances"]) == 1
    allowance = body["allowances"][0]
    assert allowance["metric_key"] == "proposal_ai.generations" and allowance["unit"] == "generation"
    with factory() as db:
        row = db.scalars(select(PurchasedAllowance)).one()
        assert allowance["quantity"] == row.quantity
        assert row.terms_document["technical_terms"]["provenance"] == "CONFIGURED_SOURCE"
    await reconcile(scenario, factory)
    before = billing_snapshot(factory)
    transport.requests.clear()
    same = (await snapshot_client.get(path(user_id), headers=headers())).json()
    assert same["access_revision"] == 1 and same["allowances"] == body["allowances"]
    assert billing_snapshot(factory) == before and transport.requests == []
    transport.subscriptions[0]["current_blocking"] = 1
    await reconcile(scenario, factory)
    empty = (await snapshot_client.get(path(user_id), headers=headers())).json()
    assert (empty["access_revision"], empty["grants"], empty["allowances"]) == (2, [], [])
    transport.subscriptions[0]["current_blocking"] = 0
    await reconcile(scenario, factory)
    restored = (await snapshot_client.get(path(user_id), headers=headers())).json()
    assert restored["access_revision"] == 3 and restored["allowances"] == body["allowances"]


async def test_production_renewal_uses_original_quantity_after_publication(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
) -> None:
    scenario, factory = production_scenario, postgres_session_factory
    await reconcile(scenario, factory)
    first = (await snapshot_client.get(path(scenario[4]), headers=headers())).json()
    await publish(factory, scenario[0], quantity=8, previous=1)
    scenario[0].subscriptions[0].update(
        last_tariffication_period_start="2026-11-30", last_tariffication_period_end="2026-12-30"
    )
    await reconcile(scenario, factory)
    later = (await snapshot_client.get(path(scenario[4]), headers=headers())).json()
    assert later["access_revision"] == 2
    assert later["allowances"][0]["quantity"] == first["allowances"][0]["quantity"] == 7
    assert later["allowances"][0]["allowance_id"] != first["allowances"][0]["allowance_id"]


async def test_snapshot_envelope_db_clock_source_deadline_and_no_second_grant_adjustment(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, factory = production_scenario, postgres_session_factory
    end = datetime.now(UTC) + timedelta(hours=1)
    scenario[0].subscriptions[0]["subscription_end_date"] = end.isoformat()
    await reconcile(scenario, factory)
    with factory() as db:
        scope = db.scalars(select(BillingProductAccessScope)).one()
        effective = as_utc(scope.effective_access_until)
        assert effective == end - timedelta(seconds=5)
    for seconds, expected_ttl in ((1000, 295), (40, 35), (5, None), (0, None)):
        now = effective - timedelta(seconds=seconds)
        monkeypatch.setattr(paid_read, "database_now", lambda db: now)
        before = billing_snapshot(factory)
        result = await snapshot_client.get(path(scenario[4]), headers=headers())
        if expected_ttl is None:
            assert result.status_code == 503
        else:
            assert result.status_code == 200
            body = result.json()
            assert datetime.fromisoformat(body["grants"][0]["valid_until"]) == effective
            expires = datetime.fromisoformat(body["expires_at"])
            assert expires == now + timedelta(seconds=expected_ttl)
            assert datetime.fromisoformat(body["refresh_after"]) == min(now + timedelta(seconds=60), expires)
        assert billing_snapshot(factory) == before


async def test_snapshot_empty_ttl_and_missing_clock(
    migrated_database: object,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with postgres_session_factory() as db:
        user, auth = reader_identity(TOKEN)
        db.add(user)
        db.flush()
        db.add(auth)
        db.commit()
        identity = user.id
    now = datetime(2026, 11, 10, 5, tzinfo=UTC)
    monkeypatch.setattr(paid_read, "database_now", lambda db: now)
    body = (await snapshot_client.get(path(identity), headers=headers())).json()
    assert datetime.fromisoformat(body["expires_at"]) == now + timedelta(seconds=295)
    monkeypatch.setattr(
        snapshot_router,
        "settings",
        snapshot_router.settings.model_copy(update={"paid_access_clock_skew_seconds": None}),
    )
    assert (await snapshot_client.get(path(identity), headers=headers())).status_code == 503


@pytest.mark.parametrize("bound", ["source", "period"])
async def test_snapshot_effective_source_and_timestamp_period_bounds(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    bound: str,
) -> None:
    scenario, factory = production_scenario, postgres_session_factory
    if bound == "period":
        # A timestamp cycle ends shortly after the actual source read; dates
        # alone would provide no such UTC deadline.
        end = datetime.now(UTC) + timedelta(hours=1)
        month = (end.month - 2) % 12 + 1
        year = end.year - int(end.month == 1)
        start = end.replace(year=year, month=month, day=min(end.day, monthrange(year, month)[1]))
        scenario[0].subscriptions[0].update(
            subscription_instance_start_date=start.isoformat(),
            last_tariffication_period_start=start.isoformat(),
            last_tariffication_period_end=end.isoformat(),
        )
    await reconcile(scenario, factory)
    with factory() as db:
        sub = db.get(ExternalSubscription, scenario[3])
        assert as_utc(sub.projection_valid_until) - as_utc(sub.last_authoritative_read_at) <= timedelta(hours=6)
        deadline = (
            as_utc(sub.projection_valid_until) - timedelta(seconds=5)
            if bound == "source"
            else as_utc(db.scalars(select(PurchasedAllowance.period_end)).one())
        )
    monkeypatch.setattr(paid_read, "database_now", lambda db: deadline - timedelta(seconds=40))
    response = await snapshot_client.get(path(scenario[4]), headers=headers())
    assert response.status_code == 200
    assert datetime.fromisoformat(response.json()["expires_at"]) == deadline - timedelta(seconds=5)
    before = billing_snapshot(factory)
    monkeypatch.setattr(paid_read, "database_now", lambda db: deadline)
    assert (await snapshot_client.get(path(scenario[4]), headers=headers())).status_code == 503
    assert billing_snapshot(factory) == before


async def test_snapshot_waits_for_whole_user_commit_without_mixing_revision_and_contents(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
) -> None:
    scenario, factory = production_scenario, postgres_session_factory
    await reconcile(scenario, factory)
    entered, release = Event(), Event()

    def reduce() -> None:
        with factory() as db:
            user = lock_user(db, scenario[4])
            scope = db.scalars(select(BillingProductAccessScope)).one()
            scope.effective_access_until = datetime.now(UTC) - timedelta(seconds=1)
            entered.set()
            assert release.wait(5)
            commit_paid_state(db, user, None, datetime.now(UTC))
            db.commit()

    writer = asyncio.create_task(asyncio.to_thread(reduce))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        readers = [asyncio.create_task(snapshot_client.get(path(scenario[4]), headers=headers())) for _ in range(3)]
        await asyncio.sleep(0.05)
        assert all(not reader.done() for reader in readers)
        release.set()
        await writer
        for response in await asyncio.gather(*readers):
            assert response.status_code == 200
            body = response.json()
            assert (body["access_revision"], body["grants"], body["allowances"]) == (2, [], [])
    finally:
        release.set()
        await writer


async def test_simulation_never_becomes_production_metering_or_a_filtered_revision(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
) -> None:
    scenario, factory = paid_scenario, postgres_session_factory
    production = scenario[2].model_copy(update={"app_env": "production"})
    await reconcile(scenario, factory, config=production)
    body = (await snapshot_client.get(path(scenario[4]), headers=headers())).json()
    assert body["access_revision"] == 1 and body["grants"] and not body["allowances"]
    await reconcile(scenario, factory)  # Explicit development policy can issue its TEST-ONLY history.
    with factory() as db:
        allowance_id = db.scalars(select(PurchasedAllowance.allowance_id)).one()
    before = billing_snapshot(factory)
    refused = await snapshot_client.get(path(scenario[4]), headers=headers())
    assert refused.status_code == 503 and billing_snapshot(factory) == before
    assert work.repair_paid_deadlines(factory, production) == 1
    body = (await snapshot_client.get(path(scenario[4]), headers=headers())).json()
    assert body["access_revision"] == 3 and not body["allowances"] and body["grants"]
    await reconcile(scenario, factory)
    with factory() as db:
        assert db.scalars(select(PurchasedAllowance.allowance_id)).one() == allowance_id


@pytest.mark.parametrize("claimed_reread", ["none", "same_cycle", "grant_change"])
async def test_future_timestamp_bucket_waits_for_authoritative_reconciliation(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    claimed_reread: str,
) -> None:
    scenario, factory = production_scenario, postgres_session_factory
    start = datetime.now(UTC) + timedelta(minutes=2)
    month = start.month % 12 + 1
    year = start.year + int(month == 1)
    end = start.replace(year=year, month=month, day=min(start.day, monthrange(year, month)[1]))
    scenario[0].subscriptions[0].update(
        subscription_instance_start_date=start.isoformat(),
        last_tariffication_period_start=start.isoformat(),
        last_tariffication_period_end=end.isoformat(),
    )
    with factory() as db:
        for queued in db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)):
            queued.work_state = BillingWorkState.COMPLETED
        db.commit()
    await reconcile(scenario, factory)
    body = (await snapshot_client.get(path(scenario[4]), headers=headers())).json()
    assert body["access_revision"] == 1 and body["grants"] and not body["allowances"]
    with factory() as db:
        allowance = db.scalars(select(PurchasedAllowance)).one()
        identity, boundary = allowance.allowance_id, as_utc(allowance.period_start)
        queued = db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)).one()
        assert queued.next_attempt_at == boundary == start + timedelta(seconds=5)
    revision = 1
    if claimed_reread != "none":
        # A source hint triggers an early reread of the already issued future
        # cycle. Claim the real SQL queue row, excluding unrelated fixture work.
        with factory() as db:
            now = as_utc(billing_reconciliation.database_now(db))
            for queued in db.scalars(select(BillingWorkItem)):
                if queued.work_kind == work.RECONCILIATION:
                    queued.next_attempt_at = now
                    queued.priority = 1
                else:
                    queued.next_attempt_at = now + timedelta(days=1)
            db.commit()
        claim = work.claim_work(factory, scenario[2], WorkLane.URGENT)
        assert claim is not None and claim.kind == work.RECONCILIATION
        if claimed_reread == "grant_change":
            scenario[0].subscriptions[0]["subscription_end_date"] = (end + timedelta(hours=1)).isoformat()
            revision += 1
        await reconcile_subscription(
            scenario[1].require_lbx(),
            scenario[1].billing,
            scenario[2],
            factory=factory,
            subscription_id=scenario[3],
            work_claim=claim,
        )
        body = (await snapshot_client.get(path(scenario[4]), headers=headers())).json()
        assert body["access_revision"] == revision and body["grants"] and not body["allowances"]
        with factory() as db:
            queued = db.get(BillingWorkItem, claim.id)
            assert as_utc(queued.next_attempt_at) <= boundary
            assert queued.work_state == "pending" and queued.lease_owner is None
            assert queued.priority == 1 and queued.enqueue_generation > claim.generation
            assert db.scalars(select(PurchasedAllowance.allowance_id)).one() == identity
    # Time alone and the local writer cannot activate a saved future bucket.
    with factory() as db:
        commit_paid_state(db, lock_user(db, scenario[4]), None, boundary)
        db.commit()
    clock = billing_reconciliation.database_now
    delta = boundary - datetime.now(UTC) + timedelta(seconds=1)
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock(db) + delta)
    monkeypatch.setattr(paid_read, "database_now", lambda db: clock(db) + delta)
    await reconcile(scenario, factory)
    body = (await snapshot_client.get(path(scenario[4]), headers=headers())).json()
    assert body["access_revision"] == revision + 1 and body["allowances"][0]["allowance_id"] == str(identity)


@pytest.mark.parametrize("apply_path", ["initial", "claimed_same_cycle", "primary_selection"])
@pytest.mark.parametrize("offset_seconds", [-1, 0, 1], ids=["before_start", "at_start", "after_start"])
async def test_excluded_start_survives_time_crossing_during_source_apply(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    apply_path: str,
    offset_seconds: int,
) -> None:
    scenario, factory = production_scenario, postgres_session_factory
    base = datetime.now(UTC)
    start = base + timedelta(seconds=1)
    month = start.month % 12 + 1
    year = start.year + int(month == 1)
    end = start.replace(year=year, month=month, day=min(start.day, monthrange(year, month)[1]))
    scenario[0].subscriptions[0].update(
        subscription_instance_start_date=start.isoformat(),
        last_tariffication_period_start=start.isoformat(),
        last_tariffication_period_end=end.isoformat(),
    )
    clock = [base]
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock[0])
    monkeypatch.setattr(paid_read, "database_now", lambda db: clock[0])
    with factory() as db:
        for queued in db.scalars(select(BillingWorkItem)):
            if queued.work_kind == work.RECONCILIATION:
                queued.work_state = BillingWorkState.COMPLETED
            else:
                queued.next_attempt_at = base + timedelta(days=1)
        if apply_path == "primary_selection":
            db.scalars(select(BillingProductAccessScope)).one().primary_subscription_id = None
        db.commit()
    claim = None
    if apply_path == "claimed_same_cycle":
        await reconcile(scenario, factory)
        with factory() as db:
            queued = db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)).one()
            queued.next_attempt_at = base
            queued.priority = 1
            db.commit()
        claim = work.claim_work(factory, scenario[2], WorkLane.URGENT)
        assert claim is not None and claim.kind == work.RECONCILIATION

    original = paid_access.materialize_allowance

    def delayed(*args: object, **kwargs: object) -> EffectiveAllowance:
        allowance = original(*args, **kwargs)
        assert allowance is not None and allowance.period_start is not None
        clock[0] = datetime.fromisoformat(allowance.period_start) + timedelta(seconds=offset_seconds)
        return allowance

    monkeypatch.setattr(paid_access, "materialize_allowance", delayed)
    if apply_path == "primary_selection":
        await run_inventory(Scenario(factory, scenario[2], scenario[0], scenario[1], scenario[3]))
    else:
        await reconcile_subscription(
            scenario[1].require_lbx(),
            scenario[1].billing,
            scenario[2],
            factory=factory,
            subscription_id=scenario[3],
            work_claim=claim,
        )
    body = (await snapshot_client.get(path(scenario[4]), headers=headers())).json()
    assert body["access_revision"] == 1 and body["grants"] and not body["allowances"]
    with factory() as db:
        allowance = db.scalars(select(PurchasedAllowance)).one()
        identity, boundary = allowance.allowance_id, as_utc(allowance.period_start)
        queued = db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)).one()
        assert as_utc(queued.next_attempt_at) <= boundary
        assert queued.priority == 1 and queued.work_state == "pending" and queued.lease_owner is None
        if offset_seconds >= 0:
            assert as_utc(queued.next_attempt_at) <= clock[0]
        if claim is not None:
            assert queued.enqueue_generation > claim.generation
    # Repair and snapshot reads cannot turn elapsed time into positive authority.
    assert work.repair_paid_deadlines(factory, scenario[2]) == 0
    assert (await snapshot_client.get(path(scenario[4]), headers=headers())).json() == body
    clock[0] = boundary + timedelta(seconds=2)
    monkeypatch.setattr(paid_access, "materialize_allowance", original)
    claim = work.claim_work(factory, scenario[2], WorkLane.URGENT)
    assert claim is not None and claim.kind == work.RECONCILIATION
    await reconcile_subscription(
        scenario[1].require_lbx(),
        scenario[1].billing,
        scenario[2],
        factory=factory,
        subscription_id=scenario[3],
        work_claim=claim,
    )
    body = (await snapshot_client.get(path(scenario[4]), headers=headers())).json()
    assert body["access_revision"] == 2 and body["allowances"][0]["allowance_id"] == str(identity)
    with factory() as db:
        queued = db.get(BillingWorkItem, claim.id)
        assert as_utc(queued.next_attempt_at) > clock[0]
        assert queued.priority == 0 and queued.enqueue_generation == claim.generation


@pytest.mark.parametrize("future", [False, True])
async def test_production_paid_commit_rolls_back_allowance_revision_and_queue(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    future: bool,
) -> None:
    scenario, factory = production_scenario, postgres_session_factory
    if future:
        year = datetime.now(UTC).year + 1
        scenario[0].subscriptions[0].update(
            subscription_instance_start_date=f"{year}-01-01T12:00:00Z",
            last_tariffication_period_start=f"{year}-01-01T12:00:00Z",
            last_tariffication_period_end=f"{year}-02-01T12:00:00Z",
        )
    before = persisted(factory)

    def fail(db: Session, *args: object, **kwargs: object) -> int:
        commit_paid_state(db, *args, **kwargs)
        db.flush()
        raise RuntimeError("synthetic paid commit failure")

    monkeypatch.setattr("app.domains.billing.reconciliation.commit_paid_state", fail)
    with pytest.raises(RuntimeError, match="synthetic paid commit failure"):
        await reconcile(scenario, factory)
    assert persisted(factory) == before


async def test_snapshot_resamples_time_after_local_query_and_translates_storage_failure(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.queries import paid_read as queries

    scenario, factory = production_scenario, postgres_session_factory
    await reconcile(scenario, factory)
    before = billing_snapshot(factory)
    with factory() as db:
        deadline = as_utc(db.scalars(select(BillingProductAccessScope.effective_access_until)).one())
    original = queries.allowances
    completed = Event()

    def delayed(db: Session, identities: list[UUID]) -> list[PurchasedAllowance]:
        result = original(db, identities)
        completed.set()
        return result

    with monkeypatch.context() as patch:
        patch.setattr(queries, "allowances", delayed)
        patch.setattr(
            paid_read, "database_now", lambda db: deadline if completed.is_set() else deadline - timedelta(seconds=1)
        )
        assert (await snapshot_client.get(path(scenario[4]), headers=headers())).status_code == 503

    def unavailable(*args: object) -> object:
        raise OperationalError("synthetic secret storage detail", {}, Exception("synthetic secret"))

    monkeypatch.setattr(queries, "allowances", unavailable)
    refused = await snapshot_client.get(path(scenario[4]), headers=headers())
    assert refused.status_code == 503 and "synthetic secret" not in refused.text
    assert refused.headers["cache-control"] == "no-store" and billing_snapshot(factory) == before


async def test_snapshot_overload_and_cancellation_keep_resource_ownership(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario, factory = production_scenario, postgres_session_factory
    await reconcile(scenario, factory)
    config = scenario[2].model_copy(
        update={
            "database_url": factory.kw["bind"].url.render_as_string(hide_password=False),
            "preflight_cleanup_timeout_seconds": 0.03,
        }
    )
    original = paid_reads.read_access_snapshot
    release, mutex = Event(), Lock()
    started = asyncio.Event()
    loop = asyncio.get_running_loop()
    entered = 0

    def held(*args: object, **kwargs: object) -> paid_read.SnapshotRead:
        nonlocal entered
        assert request_id_context.get() == "synthetic-snapshot-capacity"
        with mutex:
            entered += 1
            if entered == paid_reads.PAID_READ_CONCURRENCY:
                loop.call_soon_threadsafe(started.set)
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(paid_reads, "read_access_snapshot", held)
    monkeypatch.setattr(snapshot_router, "settings", config)
    service_config = config.model_copy(
        update={
            "backend_consumers": (
                backend_consumer(
                    backend_to_portal_current_secret=SERVICE, permissions=[BackendPermission.READ_SNAPSHOT]
                ),
            ),
        }
    )
    monkeypatch.setattr(backend_auth, "settings", service_config)
    app = create_app()
    tasks = []
    async with (
        paid_reads.paid_read_resources(config) as reads,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client,
    ):
        app.state.paid_reads = reads
        try:
            maximum = paid_reads.PAID_READ_CONCURRENCY + paid_reads.PAID_READ_MAX_WAITING
            authorization = {**headers(), "X-Request-ID": "synthetic-snapshot-capacity"}
            tasks = [asyncio.create_task(client.get(path(scenario[4]), headers=authorization)) for _ in range(maximum)]
            await asyncio.wait_for(started.wait(), 5)
            async with asyncio.timeout(5):
                while len(reads.tasks) < maximum:
                    await asyncio.sleep(0.01)
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
            refused = await client.get(path(scenario[4]), headers=authorization)
            assert refused.status_code == 503 and refused.headers["cache-control"] == "no-store"
            assert len(reads.tasks) == maximum and reads.engine.pool.checkedout() == 0
            with pytest.raises(PreflightCleanupPending):
                await reads.aclose()
            release.set()
            assert all(result.status_code == 200 for result in await asyncio.gather(*tasks[1:]))
            await reads.aclose()
            assert not reads.tasks and reads.engine is None
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)


async def test_snapshot_authentication_and_read_survive_shared_thread_saturation(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    snapshot_client: httpx.AsyncClient,
) -> None:
    scenario, factory = production_scenario, postgres_session_factory
    await reconcile(scenario, factory)
    shared = anyio.to_thread.current_default_thread_limiter()
    release = Event()

    def held() -> None:
        assert release.wait(10)

    tasks = [asyncio.create_task(anyio.to_thread.run_sync(held)) for _ in range(int(shared.total_tokens))]
    try:
        async with asyncio.timeout(5):
            while shared.borrowed_tokens != shared.total_tokens:
                await asyncio.sleep(0.01)
        result = await asyncio.wait_for(snapshot_client.get(path(scenario[4]), headers=headers()), 2)
        assert result.status_code == 200 and result.json()["access_revision"] == 1
        assert all(not task.done() for task in tasks)
    finally:
        release.set()
        await asyncio.gather(*tasks)
