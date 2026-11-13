"""Authenticated local reads against ordinary paid writers and real PostgreSQL."""

import asyncio
from collections.abc import AsyncIterator
from datetime import date, timedelta
from threading import Event
from time import monotonic
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.paid_reads import paid_read_resources
from app.core.time import utc_now
from app.core.database import Base
from app.domains.billing import paid_router as routes, paid_read
from app.domains.billing.customers import lock_user
from app.domains.billing.paid_access import commit_paid_state
from app.domains.billing.paid_contracts import EFFECTIVE_SCHEMA, EffectiveAllowance, EffectiveState, PaidGrant
from app.domains.billing.paid_cycles import CalendarEvidence, CalendarPrecision
from app.domains.catalog.link_publication import publish_product_link
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.technical_terms import bind_test_terms
from app.main import create_app
from app.models import (
    BillingProductAccessScope,
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState,
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    PaidAccessState,
    PurchasedAllowance,
)
from apps.api.tests.factories.paid_access import reader_identity
from apps.api.tests.factories.purchase_terms import technical_manifest, test_terms_source as terms_source
from apps.api.tests.support.any709_step1 import link_document, step1_settings
from apps.api.tests.test_any709_step2_postgres import TOKEN
from apps.api.tests.factories.paid_runtime import (
    paid_source as paid_source,
    paid_scenario as paid_scenario,
    reconcile,
    effective,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
BOUNDED_READER_TOKEN = "synthetic-bounded-reader"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def paid_client(
    postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app()
    monkeypatch.setattr(routes, "settings", step1_settings())
    # Only the local reader is composed: no LBX/Kernel/worker resources.
    async with (
        paid_read_resources(step1_settings(), factory=postgres_session_factory) as reads,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client,
    ):
        app.state.paid_reads = reads
        yield client


def billing_snapshot(factory: sessionmaker[Session]) -> dict:
    with factory() as db:
        return {
            name: sorted((dict(row) for row in db.execute(select(table)).mappings()), key=repr)
            for name, table in Base.metadata.tables.items()
            if name.startswith(("billing_", "external_", "paid_", "purchased_", "purchase_", "access_", "manual_"))
        }


def headers(token: str = TOKEN) -> dict[str, str]:
    return {"Authorization": "Bearer " + token, "X-Request-ID": "synthetic-paid-read"}


async def test_paid_read_implicit_zero_authentication_scope_and_email_policy(
    migrated_database: object,
    postgres_session_factory: sessionmaker[Session],
    paid_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    with factory() as db:
        for token, verified, tenant, region in (
            (TOKEN, True, "anytoolai", "ru"),
            ("unverified", False, "anytoolai", "ru"),
            ("foreign-tenant", True, "another", "ru"),
        ):
            user, session = reader_identity(token, verified=verified, tenant=tenant, region=region)
            db.add(user)
            db.flush()
            db.add(session)
        user, expired = reader_identity("expired")
        expired.expires_at = utc_now() - timedelta(seconds=1)
        db.add(user)
        db.flush()
        db.add(expired)
        user, revoked = reader_identity("revoked")
        revoked.revoked_at = utc_now()
        db.add(user)
        db.flush()
        db.add(revoked)
        db.commit()
    before = billing_snapshot(factory)
    response = await paid_client.get("/api/paid-access?user_id=ignored&region=us", headers=headers())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-request-id"] == "synthetic-paid-read"
    body = response.json()
    assert (body["access_revision"], body["grants"], body["allowances"], body["products"]) == (0, [], [], [])
    assert body["evidence_complete"] and body["committed_at"] is None
    for token in ("invalid", "foreign-tenant", "expired", "revoked"):
        refused = await paid_client.get("/api/paid-access", headers=headers(token))
        assert refused.status_code == 401 and refused.headers["cache-control"] == "no-store"
    assert (await paid_client.get("/api/paid-access")).status_code == 401
    assert (await paid_client.get("/api/paid-access", headers=headers("unverified"))).status_code == 403
    monkeypatch.setattr(routes, "settings", step1_settings().model_copy(update={"instance_region": "us"}))
    assert (await paid_client.get("/api/paid-access", headers=headers())).status_code == 401
    assert billing_snapshot(factory) == before


async def test_paid_read_preparation_paid_negative_and_unknown_remain_distinct_and_read_only(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    paid_client: httpx.AsyncClient,
) -> None:
    factory = postgres_session_factory
    transport = paid_scenario[0]
    body = (await paid_client.get("/api/paid-access", headers=headers())).json()
    assert body["access_revision"] == 0 and body["products"][0]["status"] == "unavailable"
    await reconcile(paid_scenario, factory)
    before = billing_snapshot(factory)
    transport.requests.clear()
    results = await asyncio.gather(*(paid_client.get("/api/paid-access", headers=headers()) for _ in range(4)))
    assert all(result.status_code == 200 for result in results)
    body = results[0].json()
    assert body["access_revision"] == 1 and body["products"][0]["status"] == "confirmed"
    assert body["grants"] == effective(factory)[1]["grants"]
    allowance = body["allowances"][0]
    assert set(allowance) == {"allowance_id", "product_id", "metric_key", "unit", "quantity", "provenance"}
    assert allowance["quantity"] == 100 and allowance["provenance"] == "SIMULATED"
    assert body["effective_until"] and body["products"][0]["observed_at"]
    assert billing_snapshot(factory) == before and transport.requests == []
    with factory() as db:
        user, session = reader_identity("other-owner")
        db.add(user)
        db.flush()
        db.add(session)
        db.commit()
    isolated = (await paid_client.get("/api/paid-access", headers=headers("other-owner"))).json()
    assert isolated["access_revision"] == 0 and isolated["products"] == []
    transport.subscriptions[0]["total_price"] = None
    await reconcile(paid_scenario, factory)
    unknown = (await paid_client.get("/api/paid-access", headers=headers())).json()
    assert unknown["grants"] == body["grants"] and unknown["access_revision"] == 1
    transport.subscriptions[0]["current_blocking"] = 1
    await reconcile(paid_scenario, factory)
    before = billing_snapshot(factory)
    denied = (await paid_client.get("/api/paid-access", headers=headers())).json()
    assert denied["access_revision"] == 2 and denied["grants"] == denied["allowances"] == []
    assert denied["products"][0]["status"] == "no_paid_access"
    assert billing_snapshot(factory) == before


async def test_paid_read_overdue_deadline_refuses_without_repair_or_document_filtering(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    paid_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    with factory() as db:
        deadline = as_utc(db.scalar(select(BillingProductAccessScope.effective_access_until)))
    before = billing_snapshot(factory)
    monkeypatch.setattr(paid_read, "database_now", lambda db: deadline)
    result = await paid_client.get("/api/paid-access", headers=headers())
    assert result.status_code == 503 and result.headers["cache-control"] == "no-store"
    assert result.json()["detail"]["code"] == "paid_access_deadline_pending"
    assert billing_snapshot(factory) == before and effective(factory)[0] == 1


async def test_paid_read_does_not_mix_inflight_revision_document_and_deadline(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    paid_client: httpx.AsyncClient,
) -> None:
    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    locked, release = Event(), Event()

    def reduce() -> None:
        with factory() as db:
            user = lock_user(db, paid_scenario[4])
            scope = db.scalar(select(BillingProductAccessScope))
            scope.effective_access_until = utc_now() - timedelta(seconds=1)
            locked.set()
            assert release.wait(5)
            commit_paid_state(db, user, None, utc_now())
            db.commit()

    writer = asyncio.create_task(asyncio.to_thread(reduce))
    try:
        assert await asyncio.to_thread(locked.wait, 5)
        readers = [asyncio.create_task(paid_client.get("/api/paid-access", headers=headers())) for _ in range(3)]
        await asyncio.sleep(0.05)
        release.set()
        await writer
        for response in await asyncio.gather(*readers):
            assert response.status_code == 200
            body = response.json()
            assert body["access_revision"] == 2 and body["grants"] == body["allowances"] == []
    finally:
        release.set()
        await writer


@pytest.fixture
def bounded_reader_state(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> EffectiveState:
    """Persist reader inputs only; other tests retain purchase/reconciliation wiring."""
    factory = postgres_session_factory
    link = publish_product_link(
        factory,
        evaluation=link_document(),
        expected_previous_revision=0,
        deadline=monotonic() + 5,
        lock_timeout_seconds=1,
    ).stored
    account = link.document.scope.external_billing_account_id
    terms = bind_test_terms(
        terms_source(),
        technical_manifest(),
        account_id=account,
        revision_id=link.mapping_revision_id,
        selection=link.document.selection,
        commercial_fingerprint="sha256:" + "2" * 64,
    )
    cycle = CalendarEvidence(
        precision=CalendarPrecision.DATE, start="2026-10-31", end="2026-11-29", anchor="2026-01-31"
    )
    now = utc_now()
    with factory() as db:
        user, session = reader_identity(BOUNDED_READER_TOKEN)
        db.add(user)
        db.flush()
        db.add(session)
        customer = ExternalBillingCustomer(
            user_id=user.id,
            external_billing_account_id=account,
            billing_customer_key="synthetic-bounded-customer",
            binding_state=ExternalBillingCustomerBindingState.BOUND,
            provider_customer_id="123",
        )
        db.add(customer)
        db.flush()
        subscription = ExternalSubscription(
            user_id=user.id,
            customer_id=customer.customer_id,
            external_billing_account_id=account,
            product_id=terms.offer.product_id,
            mapping_revision_id=link.mapping_revision_id,
            external_subscription_id="567",
            lifecycle_status=Lifecycle.ACTIVE,
            financial_access_status=Financial.ALLOWED,
            commercial_access_status=Commercial.ELIGIBLE,
            last_authoritative_read_at=now,
            projection_valid_until=now + timedelta(days=1),
        )
        db.add(subscription)
        db.flush()
        allowance_id = uuid4()
        allowance = EffectiveAllowance(
            allowance_id=str(allowance_id),
            product_id=terms.offer.product_id,
            metric_key=terms.offer.metric_key,
            unit=terms.offer.unit,
            quantity=terms.offer.quantity,
            cycle=cycle,
        )
        document = EffectiveState(grants=(PaidGrant(product_id=terms.offer.product_id),), allowances=(allowance,))
        db.add(
            PurchasedAllowance(
                allowance_id=allowance_id,
                subscription_id=subscription.subscription_id,
                source_component_id=str(terms.selection.tariff_service_id),
                product_id=allowance.product_id,
                metric_key=allowance.metric_key,
                quantity=allowance.quantity,
                unit=allowance.unit,
                cycle_schema_version="calendar:v1",
                provider_cycle_key=f"date:{cycle.start}:{cycle.end}",
                cycle_date_start=date.fromisoformat(cycle.start),
                cycle_date_end=date.fromisoformat(cycle.end),
                calendar_document=cycle.model_dump(mode="json"),
                terms_document={"technical_terms": terms.model_dump(mode="json")},
            )
        )
        db.add(
            PaidAccessState(
                user_id=user.id,
                tenant_id=user.tenant_id,
                region=user.region,
                access_revision=1,
                effective_state_schema_version=EFFECTIVE_SCHEMA,
                effective_state_document=document.model_dump(mode="json"),
                committed_at=now,
            )
        )
        db.add(
            BillingProductAccessScope(
                user_id=user.id,
                product_id=terms.offer.product_id,
                primary_subscription_id=subscription.subscription_id,
                effective_access_document=document.model_dump(mode="json"),
                effective_access_until=now + timedelta(days=1),
            )
        )
        # Put the paid product beyond the display cap to detect accidental
        # filtering of the independent complete grant/allowance contents.
        db.add_all(
            BillingProductAccessScope(user_id=user.id, product_id=f"aaa_synthetic_{index:03}") for index in range(101)
        )
        db.commit()
    return document


async def test_paid_read_bounds_display_evidence_without_truncating_effective_contents(
    bounded_reader_state: EffectiveState,
    postgres_session_factory: sessionmaker[Session],
    paid_client: httpx.AsyncClient,
) -> None:
    factory = postgres_session_factory
    before = billing_snapshot(factory)
    response = await paid_client.get("/api/paid-access", headers=headers(BOUNDED_READER_TOKEN))
    assert response.status_code == 200
    body = response.json()
    assert len(body["products"]) == 100 and not body["evidence_complete"]
    assert body["access_revision"] == 1
    assert bounded_reader_state.grants[0].product_id not in {item["product_id"] for item in body["products"]}
    assert body["grants"] == effective(factory)[1]["grants"] == bounded_reader_state.model_dump(mode="json")["grants"]
    assert len(body["allowances"]) == 1
    assert body["allowances"] == [
        {**item.model_dump(exclude={"cycle", "period_start", "period_end"}), "provenance": "SIMULATED"}
        for item in bounded_reader_state.allowances
    ]
    assert billing_snapshot(factory) == before


async def test_paid_read_available_while_real_http_normal_and_sale_sources_are_saturated(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    paid_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    from app.composition.billing_worker import billing_worker_resources
    from app.composition.sources import source_resources
    from app.domains.billing.work_contracts import WorkLane
    from app.jobs.billing import BillingWorker

    await reconcile(paid_scenario, postgres_session_factory)
    release, normal_held, sale_held = asyncio.Event(), asyncio.Event(), asyncio.Event()
    handlers: set[asyncio.Task] = set()

    async def handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        owner = asyncio.current_task()
        handlers.add(owner)
        try:
            request = await reader.readuntil(b"\r\n\r\n")
            path = request.split(b" ", 2)[1].decode("ascii")
            if path.endswith("/auth"):
                data = {"token": "synthetic-read-capacity-token", "expires_in": 600}
            else:
                identity = int(path.rsplit("/", 1)[1])
                (normal_held if identity == 101 else sale_held).set()
                await release.wait()
                data = {"user_id": identity, "outer_id": "synthetic-held-source"}
            body = json.dumps({"code": 200, "response": data}).encode()
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nConnection: close\r\nContent-Length: "
                + str(len(body)).encode()
                + b"\r\n\r\n"
                + body
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
            handlers.discard(owner)

    async def no_start(self: BillingWorker) -> None:
        pass

    monkeypatch.setattr(BillingWorker, "start", no_start)
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    config = paid_scenario[2].model_copy(
        update={
            "lbx_base_url": f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}",
            "billing_worker_enabled": True,
            "billing_worker_normal_concurrency": 1,
            "preflight_max_active": 1,
            "lbx_read_timeout_seconds": 10,
        }
    )
    try:
        async with (
            server,
            source_resources(config) as sales,
            billing_worker_resources(config, factory=postgres_session_factory) as worker,
        ):

            async def read_sale() -> None:
                async with sales.billing.operation(bound_scope=False) as budget:
                    await sales.require_lbx().get_user(user_id=777, budget=budget)

            async def read_normal() -> None:
                async with worker.admissions[WorkLane.NORMAL].operation(bound_scope=False) as budget:
                    await worker.client.get_user(user_id=101, budget=budget)

            tasks = [asyncio.create_task(read_sale()), asyncio.create_task(read_normal())]
            try:
                await asyncio.wait_for(normal_held.wait(), 5)
                await asyncio.wait_for(sale_held.wait(), 5)
                result = await asyncio.wait_for(paid_client.get("/api/paid-access", headers=headers()), 1)
                assert result.status_code == 200 and result.json()["access_revision"] == 1
                assert not release.is_set() and all(not task.done() for task in tasks)
            finally:
                release.set()
                await asyncio.gather(*tasks)
    finally:
        release.set()
        server.close()
        await server.wait_closed()
        if handlers:
            await asyncio.gather(*handlers)


async def test_paid_read_deadline_crossing_during_local_queries_refuses_without_writes(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    paid_client: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.queries import paid_read as queries
    from app.models import PurchasedAllowance
    from uuid import UUID

    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    with factory() as db:
        deadline = as_utc(db.scalar(select(BillingProductAccessScope.effective_access_until)))
    before = billing_snapshot(factory)
    finished = Event()
    original = queries.allowances

    def allowance_read(db: Session, identities: list[UUID]) -> list[PurchasedAllowance]:
        rows = original(db, identities)
        finished.set()  # The saved deadline passed while this local read waited.
        return rows

    monkeypatch.setattr(queries, "allowances", allowance_read)
    monkeypatch.setattr(
        paid_read, "database_now", lambda db: deadline if finished.is_set() else deadline - timedelta(seconds=1)
    )
    response = await paid_client.get("/api/paid-access", headers=headers())
    assert response.status_code == 503 and response.json()["detail"]["code"] == "paid_access_deadline_pending"
    assert billing_snapshot(factory) == before
