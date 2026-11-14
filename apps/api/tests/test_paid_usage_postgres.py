"""Cabinet usage on disposable PostgreSQL; backend HTTP is synthetic."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
import asyncio

import httpx
import pytest
from sqlalchemy.engine import URL
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.paid_reads import paid_read_resources
from app.composition.paid_usage import paid_usage_resources, USAGE_CONCURRENCY, USAGE_MAX_WAITING
from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing import paid_router, usage_router
from app.domains.billing.contracts import BillingRefused
from app.main import create_app
from app.models import AuthSession, ExternalSubscription, PurchasedAllowance, User, UserStatus
from apps.api.tests.factories.paid_access import reader_identity
from apps.api.tests.factories.paid_runtime import reconcile, paid_scenario as paid_scenario, paid_source as paid_source
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer
from apps.api.tests.test_access_snapshot_postgres import production_scenario as production_scenario
from apps.api.tests.test_paid_access_read_postgres import billing_snapshot, headers
from apps.api.tests.test_any709_step2_postgres import TOKEN

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class UsageBackend:
    def __init__(self, factory: sessionmaker[Session]) -> None:
        self.factory = factory
        self.requests: list[httpx.Request] = []
        self.status = 200
        self.mismatch = False
        self.bad_product: str | None = None
        self.unobserved = False
        self.scope_mismatch = False
        self.assert_no_sql = True
        self.gate: asyncio.Event | None = None
        self.entered = asyncio.Event()

    async def respond(self, request: httpx.Request) -> httpx.Response:
        # Actual application selection transactions/locks are already closed.
        if self.assert_no_sql:
            assert self.factory.kw["bind"].pool.checkedout() == 0
        self.requests.append(request)
        self.entered.set()
        if self.gate is not None:
            await self.gate.wait()
        ids = request.url.params.get_list("allowance_id")
        with self.factory() as db:
            rows = {str(row.allowance_id): row for row in db.scalars(select(PurchasedAllowance))}
        items = []
        for identity in ids:
            row = rows[identity]
            if self.unobserved:
                items.append({"allowance_id": identity, "status": "unobserved"})
            else:
                items.append(
                    dict(
                        allowance_id=identity,
                        status="observed",
                        product_id=row.product_id,
                        metric_key="foreign.metric"
                        if self.mismatch or self.bad_product == row.product_id
                        else row.metric_key,
                        unit=row.unit,
                        quantity=row.quantity,
                        successful_used=2,
                        reserved=1,
                        remaining=max(row.quantity - 2, 0),
                        available=max(row.quantity - 3, 0),
                        read_at=datetime.now(UTC).isoformat(),
                    )
                )
        return httpx.Response(
            self.status,
            json=dict(
                schema_version=1,
                tenant_id="foreign" if self.scope_mismatch else "anytoolai",
                region="ru",
                user_id=request.url.path.rsplit("/", 1)[1],
                items=items,
            ),
        )


@pytest.fixture
async def cabinet(
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[httpx.AsyncClient, UsageBackend, Settings, object]]:
    config = step1_settings().model_copy(update={"backend_consumers": (backend_consumer(), second_consumer())})
    backend = UsageBackend(postgres_session_factory)
    app = create_app()
    monkeypatch.setattr(usage_router, "settings", config)
    monkeypatch.setattr(paid_router, "settings", config)
    async with (
        paid_read_resources(config, factory=postgres_session_factory) as local,
        paid_usage_resources(
            config, factory=postgres_session_factory, transport=httpx.MockTransport(backend.respond)
        ) as usage,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client,
    ):
        app.state.paid_reads = local
        app.state.paid_usage = usage
        yield client, backend, config, usage


async def test_identity_policy_empty_history_and_no_store(
    migrated_database: object,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
) -> None:
    factory = postgres_session_factory
    with factory() as db:
        for token, verified, tenant in (
            (TOKEN, True, "anytoolai"),
            ("unverified", False, "anytoolai"),
            ("foreign", True, "foreign"),
            ("inactive", True, "anytoolai"),
        ):
            user, session = reader_identity(token, verified=verified, tenant=tenant)
            if token == "inactive":
                user.status = UserStatus.INACTIVE
            db.add(user)
            db.flush()
            db.add(session)
        db.commit()
    client, backend, _, _ = cabinet
    for token, status in ((TOKEN, 200), ("unverified", 403), ("foreign", 401), ("inactive", 401), ("unknown", 401)):
        response = await client.get("/api/paid-usage?user_id=foreign&region=us", headers=headers(token))
        assert response.status_code == status, response.text
        assert response.headers["cache-control"] == "no-store"
        if status == 200:
            assert response.json() == {"access_revision": 0, "items": []}
    response = await client.get("/api/paid-usage")
    assert response.status_code == 401 and response.headers["cache-control"] == "no-store"
    assert backend.requests == []


@pytest.mark.parametrize("mode", ["observed", "unobserved", "tuple", "scope", "outage"])
async def test_actual_usage_scope_tuple_outage_and_read_only(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
    mode: str,
) -> None:
    factory = postgres_session_factory
    await reconcile(production_scenario, factory)
    client, backend, _, _ = cabinet
    backend.unobserved = mode == "unobserved"
    backend.mismatch = mode == "tuple"
    backend.scope_mismatch = mode == "scope"
    backend.status = 503 if mode == "outage" else 200
    before = billing_snapshot(factory)
    response = await client.get("/api/paid-usage", headers=headers())
    assert response.headers["cache-control"] == "no-store"
    assert response.status_code == (503 if mode in {"scope", "outage"} else 200), response.text
    assert billing_snapshot(factory) == before
    if response.status_code == 200:
        item = response.json()["items"][0]
        assert item["classification"] == "current" and item["quantity"] == 7
        assert item["status"] == {"observed": "observed", "unobserved": "unobserved", "tuple": "unavailable"}[mode]
        if mode == "observed":
            assert (item["successful_used"], item["reserved"], item["remaining"], item["available"]) == (2, 1, 5, 4)
            assert item["read_at"]
        else:
            assert not {"successful_used", "reserved", "remaining", "available", "read_at"} & item.keys()
    assert backend.requests[0].url.host == "kernel.example.test"


async def test_revision_change_during_http_refuses_mixed_result(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
) -> None:
    await reconcile(production_scenario, postgres_session_factory)
    client, backend, _, _ = cabinet
    backend.gate = asyncio.Event()
    task = asyncio.create_task(client.get("/api/paid-usage", headers=headers()))
    await backend.entered.wait()
    production_scenario[0].subscriptions[0]["current_blocking"] = 1
    await reconcile(production_scenario, postgres_session_factory)
    backend.gate.set()
    result = await task
    assert result.status_code == 503 and result.json()["detail"]["code"] == "paid_usage_state_changed"
    historical = await client.get("/api/paid-usage", headers=headers())
    assert historical.status_code == 200
    item = historical.json()["items"][0]
    assert item["classification"] == "historical" and item["successful_used"] == 2


async def test_new_cycle_replaces_current_identity_without_rewriting_history(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
) -> None:
    factory = postgres_session_factory
    await reconcile(production_scenario, factory)
    client, backend, _, _ = cabinet
    first = (await client.get("/api/paid-usage", headers=headers())).json()["items"][0]
    production_scenario[0].subscriptions[0].update(
        last_tariffication_period_start="2026-11-30", last_tariffication_period_end="2026-12-30"
    )
    await reconcile(production_scenario, factory)
    before = billing_snapshot(factory)
    second = (await client.get("/api/paid-usage", headers=headers())).json()["items"][0]
    assert second["allowance_id"] != first["allowance_id"] and second["classification"] == "current"
    assert len(before["purchased_allowances"]) == 2 and billing_snapshot(factory) == before
    assert backend.requests[-1].url.params.get_list("allowance_id") == [second["allowance_id"]]


@pytest.mark.parametrize("with_history", [True, False])
async def test_future_issuance_never_hides_eligible_history_even_after_start(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
    monkeypatch: pytest.MonkeyPatch,
    with_history: bool,
) -> None:
    from calendar import monthrange
    from app.domains.billing import paid_usage

    factory = postgres_session_factory
    start = datetime.now(UTC) + timedelta(minutes=2)

    def month(value: datetime, delta: int) -> datetime:
        index = value.year * 12 + value.month - 1 + delta
        year, m = divmod(index, 12)
        return value.replace(year=year, month=m + 1, day=min(value.day, monthrange(year, m + 1)[1]))

    previous, end = month(start, -1), month(start, 1)
    source = production_scenario[0].subscriptions[0]
    source.update(
        subscription_instance_start_date=previous.isoformat(),
        last_tariffication_period_start=previous.isoformat(),
        last_tariffication_period_end=start.isoformat(),
    )
    client, backend, _, _ = cabinet
    if with_history:
        await reconcile(production_scenario, factory)
        old = (await client.get("/api/paid-usage", headers=headers())).json()["items"][0]
    source.update(last_tariffication_period_start=start.isoformat(), last_tariffication_period_end=end.isoformat())
    await reconcile(production_scenario, factory)
    before = billing_snapshot(factory)
    assert len(before["purchased_allowances"]) == (2 if with_history else 1)
    for after_boundary in (False, True):
        if after_boundary:
            monkeypatch.setattr(paid_usage, "database_now", lambda db: start + timedelta(seconds=6))
        response = await client.get("/api/paid-usage", headers=headers())
        assert response.status_code == 200, response.text
        if with_history:
            item = response.json()["items"][0]
            assert item["allowance_id"] == old["allowance_id"] and item["classification"] == "historical"
            assert item["successful_used"] == 2
            assert backend.requests[-1].url.params.get_list("allowance_id") == [old["allowance_id"]]
        else:
            assert response.json()["items"] == [] and backend.requests == []
    assert billing_snapshot(factory) == before


@pytest.mark.parametrize("paid_scenario", [None], indirect=True)
async def test_simulated_history_is_excluded(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
) -> None:
    await reconcile(paid_scenario, postgres_session_factory)
    client, backend, _, _ = cabinet
    before = billing_snapshot(postgres_session_factory)
    result = await client.get("/api/paid-usage", headers=headers())
    assert result.status_code == 200 and result.json()["items"] == []
    assert not backend.requests and billing_snapshot(postgres_session_factory) == before


async def test_access_capacity_survives_usage_pressure_cancellation_and_timeout(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
) -> None:
    await reconcile(production_scenario, postgres_session_factory)
    client, backend, config, usage = cabinet
    backend.assert_no_sql = False
    backend.gate = asyncio.Event()
    tasks = [
        asyncio.create_task(client.get("/api/paid-usage", headers=headers()))
        for _ in range(USAGE_CONCURRENCY + USAGE_MAX_WAITING)
    ]
    try:
        await backend.entered.wait()
        for _ in range(100):
            if usage.admission.waiting_count == USAGE_MAX_WAITING:
                break
            await asyncio.sleep(0.005)
        assert usage.admission.active_count == USAGE_CONCURRENCY
        assert usage.admission.waiting_count == USAGE_MAX_WAITING
        saturated = await client.get("/api/paid-usage", headers=headers())
        assert saturated.status_code == 503 and saturated.headers["cache-control"] == "no-store"
        assert (await asyncio.wait_for(client.get("/api/paid-access", headers=headers()), 1)).status_code == 200
        tasks[0].cancel()
        await asyncio.gather(tasks[0], return_exceptions=True)
        assert (await asyncio.wait_for(client.get("/api/paid-access", headers=headers()), 1)).status_code == 200
    finally:
        backend.gate.set()
        await asyncio.gather(*tasks, return_exceptions=True)
    # Bound the complete remote read using the existing nonrenewable budget.
    config = config.model_copy(
        update={"preflight_total_timeout_seconds": 0.2, "preflight_cleanup_timeout_seconds": 0.05}
    )
    backend.gate = asyncio.Event()
    async with paid_usage_resources(
        config, factory=postgres_session_factory, transport=httpx.MockTransport(backend.respond)
    ) as bounded:
        with pytest.raises(BillingRefused, match="paid_usage_unavailable"):
            await bounded.read(config, TOKEN)
    assert (await client.get("/api/paid-access", headers=headers())).status_code == 200


@pytest.mark.parametrize("change", ["revoke", "inactive"])
async def test_parent_session_rechecked_after_http(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
    change: str,
) -> None:
    await reconcile(production_scenario, postgres_session_factory)
    client, backend, _, _ = cabinet
    backend.gate = asyncio.Event()
    task = asyncio.create_task(client.get("/api/paid-usage", headers=headers()))
    await backend.entered.wait()
    with postgres_session_factory() as db:
        if change == "revoke":
            db.scalar(select(AuthSession)).revoked_at = utc_now()
        else:
            db.scalar(select(User)).status = UserStatus.INACTIVE
        db.commit()
    backend.gate.set()
    result = await task
    assert result.status_code == 401 and result.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("bad_product", [None, "synthetic_summary"])
async def test_mixed_owners_are_routed_and_foreign_tuple_cannot_contaminate_other_item(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
    bad_product: str | None,
) -> None:
    from app.composition import purchases
    from app.composition.mapping_operator import fresh_link_evaluation
    from app.composition.sources import source_resources
    from app.domains.billing.paid_allowances import materialize_allowance
    from app.domains.catalog.link_publication import publish_product_link
    from apps.api.tests.factories.purchase_terms import reviewed_meaning
    from apps.api.tests.support.any709_step1 import link_selection
    from apps.api.tests.test_any766_technical_sources import source_settings, summary_manifest, summary_offer
    from apps.api.tests.test_any766_technical_sources_postgres import cycle
    from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording

    factory = postgres_session_factory
    await reconcile(production_scenario, factory)
    transport = production_scenario[0]
    # A different product needs a distinct synthetic commercial association.
    summary_recording = SelectedOfferRecording(tariff_id=702)
    summary_recording.bodies = {
        name: body.replace(b'"tariff_id":701', b'"tariff_id":702') for name, body in transport.offer.bodies.items()
    }
    config = source_settings()
    manifest = httpx.MockTransport(lambda request: httpx.Response(200, json=summary_manifest()))
    lbx = httpx.MockTransport(
        lambda request: (
            summary_recording.respond(request) if "/tariffs/702" in request.url.path else transport.respond(request)
        )
    )
    fresh = await fresh_link_evaluation(
        config,
        selection=link_selection(product_id="synthetic_summary", tariff_id=702),
        technical_offer=summary_offer(),
        principal="os-euid:29001",
        kernel_transport=manifest,
        lbx_transport=lbx,
    )
    publish_product_link(
        factory,
        evaluation=fresh.document,
        expected_previous_revision=0,
        deadline=fresh.deadline,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    )
    async with source_resources(config, kernel_transport=manifest, lbx_transport=lbx) as sources:
        link, offer, documents, terms = await purchases.review_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            product_id="synthetic_summary",
        )
        purchase = await purchases.confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="mixed-owner-usage",
            meaning=reviewed_meaning(
                "synthetic_summary", link.mapping_revision_id, offer.fingerprint, documents, terms
            ),
        )
        linked = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.product_id == "synthetic_summary"))
        summary = materialize_allowance(db, sub, linked.accepted, cycle(), skew_seconds=5)
        db.commit()
    client, backend, _, _ = cabinet
    backend.bad_product = bad_product
    before = billing_snapshot(factory)
    result = await client.get("/api/paid-usage", headers=headers())
    assert result.status_code == 200, result.text
    items = {item["product_id"]: item for item in result.json()["items"]}
    assert items["proposal_ai"]["status"] == "observed"
    assert items["synthetic_summary"]["classification"] == "historical"
    assert items["synthetic_summary"]["status"] == ("unavailable" if bad_product else "observed")
    consumers = {"kernel.example.test": backend_consumer(), "summary.example.test": second_consumer()}
    assert len(backend.requests) == 2
    for request in backend.requests:
        owner = consumers[request.url.host]
        assert request.headers["authorization"] == "Bearer " + owner.portal_to_backend_current_secret.get_secret_value()
        ids = request.url.params.get_list("allowance_id")
        assert (str(summary.allowance_id) in ids) == (owner.consumer_id == "synthetic-summary")
    assert billing_snapshot(factory) == before


async def test_legacy_history_without_terms_has_no_usage_item_or_backend_request(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
) -> None:
    factory = postgres_session_factory
    # Seed a retained predecessor row, which genuinely has no unit/terms.
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        db.add(
            PurchasedAllowance(
                subscription_id=sub.subscription_id,
                source_component_id="legacy",
                product_id=sub.product_id,
                metric_key="legacy.metric",
                quantity=42,
                cycle_schema_version="legacy-utc:v1",
                period_start=datetime.now(UTC) - timedelta(days=31),
                period_end=datetime.now(UTC) - timedelta(days=1),
            )
        )
        db.commit()
    before = billing_snapshot(factory)
    client, backend, _, _ = cabinet
    response = await client.get("/api/paid-usage", headers=headers())
    assert response.status_code == 200 and response.json()["items"] == []
    assert backend.requests == [] and billing_snapshot(factory) == before


def test_usage_openapi_uses_named_dtos_and_portal_authentication() -> None:
    schema = create_app().openapi()
    operation = schema["paths"]["/api/paid-usage"]["get"]
    assert operation["security"] == [{"PortalUserBearer": []}]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/PaidUsageResponse")


async def test_historical_selection_has_deterministic_created_at_and_identity_order(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
) -> None:
    from app.domains.billing.paid_allowances import materialize_allowance
    from app.domains.purchases.evidence import accepted
    from app.models import PurchaseIntent
    from apps.api.tests.test_any766_technical_sources_postgres import cycle

    factory = postgres_session_factory
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        purchase = accepted(db.get(PurchaseIntent, sub.purchase_intent_id))
        first = materialize_allowance(db, sub, purchase, cycle(), skew_seconds=5)
        later = materialize_allowance(
            db,
            sub,
            purchase,
            cycle().model_copy(
                update={
                    "start": "2026-11-30",
                    "end": "2026-12-30",
                }
            ),
            skew_seconds=5,
        )
        db.commit()
    with factory() as db:
        rows = list(db.scalars(select(PurchasedAllowance)))
        assert len(rows) == 2 and rows[0].created_at == rows[1].created_at
        expected = str(max(rows, key=lambda row: (row.created_at, row.allowance_id)).allowance_id)
        assert {str(row.allowance_id) for row in rows} == {first.allowance_id, later.allowance_id}
    before = billing_snapshot(factory)
    client, backend, _, _ = cabinet
    result = await client.get("/api/paid-usage", headers=headers())
    assert result.status_code == 200, result.text
    assert [item["allowance_id"] for item in result.json()["items"]] == [expected]
    assert backend.requests[0].url.params.get_list("allowance_id") == [expected]
    assert billing_snapshot(factory) == before


@pytest.mark.parametrize("writer", ["v1", "v2", "v2_missing_receipt"])
@pytest.mark.parametrize("equivalent_iso", [False, True])
async def test_activated_timestamp_history_survives_equivalent_iso(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    cabinet: tuple,
    equivalent_iso: bool,
    writer: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from calendar import monthrange
    from app.domains.identity.services.auth import as_utc
    from app.models import PaidAccessState

    if writer != "v2":
        from app.domains.billing import paid_access, reconciliation

        monkeypatch.setattr(paid_access, "retain_activations", lambda *args: None)
        if writer == "v1":
            monkeypatch.setattr(reconciliation, "RECONCILIATION_SCHEMA", "subscription-reconciliation:v1")
    factory = postgres_session_factory
    start = datetime.now(UTC) + timedelta(seconds=1)
    month_index = start.year * 12 + start.month
    year, month_zero = divmod(month_index, 12)
    end = start.replace(year=year, month=month_zero + 1, day=min(start.day, monthrange(year, month_zero + 1)[1]))
    source = production_scenario[0].subscriptions[0]
    source.update(
        subscription_instance_start_date=start.isoformat(),
        last_tariffication_period_start=start.isoformat(),
        last_tariffication_period_end=end.isoformat(),
    )
    await reconcile(production_scenario, factory)
    with factory() as db:
        allowance = db.scalars(select(PurchasedAllowance)).one()
        identity, original_calendar = allowance.allowance_id, allowance.calendar_document
        boundary = as_utc(allowance.period_start)
        assert db.scalar(select(PaidAccessState)).effective_state_document["allowances"] == []
    await asyncio.sleep(max(0, (boundary - datetime.now(UTC)).total_seconds()) + 0.05)
    if equivalent_iso:
        source.update(
            {
                key: source[key].replace("+00:00", "Z")
                for key in (
                    "subscription_instance_start_date",
                    "last_tariffication_period_start",
                    "last_tariffication_period_end",
                )
            }
        )
    await reconcile(production_scenario, factory)
    with factory() as db:
        assert db.scalar(select(PaidAccessState)).effective_state_document["allowances"][0]["allowance_id"] == str(
            identity
        )
        assert db.get(PurchasedAllowance, identity).calendar_document == original_calendar
    source["current_blocking"] = 1
    await reconcile(production_scenario, factory)
    if writer == "v1":
        from app.infrastructure.queries import paid_usage as usage_queries
        from app.models import BillingStateObservation

        original_candidates = usage_queries.legacy_activation_candidates

        def with_unresolved_calendar(*args, **kwargs):
            # Older complete commercial evidence may lack a proven calendar;
            # another retained candidate must still be considered.
            return [BillingStateObservation(evidence_document={"cycle": None}), *original_candidates(*args, **kwargs)]

        monkeypatch.setattr(usage_queries, "legacy_activation_candidates", with_unresolved_calendar)
    client, backend, _, _ = cabinet
    before = billing_snapshot(factory)
    response = await client.get("/api/paid-usage", headers=headers())
    assert response.status_code == 200, response.text
    if writer == "v2_missing_receipt":
        assert response.json()["items"] == []
        assert backend.requests == []
        assert billing_snapshot(factory) == before
        return
    assert [item["allowance_id"] for item in response.json()["items"]] == [str(identity)]
    assert response.json()["items"][0]["classification"] == "historical"
    assert backend.requests[-1].url.params.get_list("allowance_id") == [str(identity)]
    assert billing_snapshot(factory) == before


@pytest.mark.parametrize("transition", ["noop", "blocked", "expired", "rollback"])
async def test_upgrade_retains_previous_membership_before_reduction(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
) -> None:
    from app.domains.billing import paid_access, reconciliation
    from app.domains.identity.services.auth import as_utc
    from app.models import (
        BillingStateObservation,
        BillingStateObservationKind,
        BillingProductAccessScope,
        PaidAccessState,
    )
    from app.models import ExternalSubscriptionFinancialAccessStatus as Financial
    from app.infrastructure.queries.paid_usage import activation

    factory = postgres_session_factory
    # Simulate the pre-upgrade writer, without rewriting/deleting immutable rows.
    with monkeypatch.context() as old:
        old.setattr(paid_access, "retain_activations", lambda *args: None)
        old.setattr(reconciliation, "RECONCILIATION_SCHEMA", "subscription-reconciliation:v1")
        await reconcile(production_scenario, factory)
    with factory() as db:
        previous = db.scalar(select(PaidAccessState))
        old_revision, committed_at = previous.access_revision, as_utc(previous.committed_at)
        allowance = db.scalar(select(PurchasedAllowance))
        allowance_id = allowance.allowance_id
        original = (allowance.calendar_document, allowance.terms_document, allowance.created_at)
        assert activation(db, allowance_id) is None
    with factory() as db:
        user = db.scalar(select(User).with_for_update())
        scope = db.scalar(select(BillingProductAccessScope))
        now = datetime.now(UTC)
        if transition == "blocked":
            db.scalar(select(ExternalSubscription)).financial_access_status = Financial.BLOCKED
        elif transition == "expired":
            now = as_utc(scope.effective_access_until) + timedelta(seconds=1)
        result = paid_access.commit_paid_state(db, user, None, now)
        receipt = activation(db, allowance_id)
        assert receipt.resulting_access_revision == old_revision
        assert as_utc(receipt.effective_at) == committed_at
        assert as_utc(receipt.observed_at) == now
        assert result == old_revision + (transition in {"blocked", "expired"})
        if transition == "rollback":
            db.rollback()
        else:
            db.commit()
    with factory() as db:
        if transition == "rollback":
            assert activation(db, allowance_id) is None
            assert db.scalar(select(PaidAccessState)).access_revision == old_revision
        else:
            user = db.scalar(select(User).with_for_update())
            paid_access.commit_paid_state(db, user, None, now)
            db.commit()
            assert (
                len(
                    list(
                        db.scalars(
                            select(BillingStateObservation).where(
                                BillingStateObservation.observation_kind
                                == BillingStateObservationKind.ALLOWANCE_ACTIVATION
                            )
                        )
                    )
                )
                == 1
            )
        row = db.get(PurchasedAllowance, allowance_id)
        assert (row.calendar_document, row.terms_document, row.created_at) == original


async def test_activation_receipt_is_unique_immutable_and_blocks_downgrade(
    production_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    database_test_url: "URL",
) -> None:
    from alembic import command
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError, IntegrityError
    from apps.api.tests.support.postgres import alembic_test_config

    factory = postgres_session_factory
    await reconcile(production_scenario, factory)
    with factory() as db:
        with pytest.raises(IntegrityError):
            db.execute(
                text("""INSERT INTO billing_state_observations
              (observation_id, observation_kind, external_billing_account_id, user_id, product_id,
               access_scope_id, subscription_id, observed_at, effective_at, evidence_schema_version,
               evidence_document, completeness_classification, result_classification, resulting_access_revision)
              SELECT gen_random_uuid(), observation_kind, external_billing_account_id, user_id, product_id,
               access_scope_id, subscription_id, observed_at, effective_at, evidence_schema_version,
               evidence_document, completeness_classification, result_classification, resulting_access_revision
              FROM billing_state_observations WHERE observation_kind = 'allowance_activation'""")
            )
        db.rollback()
        with pytest.raises(DBAPIError):
            db.execute(
                text(
                    "UPDATE billing_state_observations SET evidence_document = '{}'::jsonb WHERE observation_kind = 'allowance_activation'"
                )
            )
        db.rollback()
        with pytest.raises(DBAPIError):
            db.execute(text("DELETE FROM billing_state_observations WHERE observation_kind = 'allowance_activation'"))
        db.rollback()
    with alembic_test_config(database_test_url) as config:
        with pytest.raises(RuntimeError, match="Activation/V2 evidence requires the new reader"):
            command.downgrade(config, "20261111_0011")
