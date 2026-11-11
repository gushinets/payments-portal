"""Durable hint ACK/isolation on real PostgreSQL; configured sources are synthetic."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import Any
from app.core.settings import Settings
from app.domains.catalog.publication import SessionFactory
from sqlalchemy.engine import Engine, URL
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.composition.allowance_usage import allowance_backend
from app.composition import purchases
from app.composition.mapping_operator import fresh_link_evaluation
from app.composition.sources import source_resources
from app.core.backend_consumers import BackendPermission
from app.domains.billing import allowance_exhaustion as exhaustion, work
from app.domains.billing.paid_allowances import materialize_allowance
from app.domains.billing.work_contracts import WorkLane
from app.domains.catalog.link_publication import publish_product_link
from app.http import backend_auth
from app.http.dependencies import get_session_factory
from app.jobs.billing import BillingWorker
from app.main import create_app
from app.models import BillingWorkItem, BillingWorkKind, BillingWorkState, ExternalSubscription, PurchasedAllowance
from apps.api.tests.factories.paid_runtime import reconcile
from apps.api.tests.factories.purchase_terms import reviewed_meaning
from apps.api.tests.support.any709_step1 import link_selection
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer
from apps.api.tests.test_access_snapshot_postgres import production_scenario as production_scenario
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed
from apps.api.tests.test_any766_technical_sources import source_settings, summary_manifest, summary_offer
from apps.api.tests.test_any766_technical_sources_postgres import cycle
from apps.api.tests.test_paid_access_read_postgres import billing_snapshot

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
PATH = "/internal/v1/allowance-exhaustions"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def receiver(
    postgres_session_factory: SessionFactory, monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[httpx.AsyncClient, Settings]]:
    kernel = backend_consumer(permissions=[BackendPermission.WRITE_EXHAUSTION])
    summary = second_consumer(permissions=[BackendPermission.WRITE_EXHAUSTION])
    config = source_settings(backend_consumers=(kernel, summary))
    monkeypatch.setattr(backend_auth, "settings", config)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: postgres_session_factory
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://portal.test") as client:
        yield client, config


def headers(consumer: Any) -> dict[str, str]:
    return {"Authorization": "Bearer " + consumer.backend_to_portal_current_secret.get_secret_value()}


def payload(factory: SessionFactory) -> dict[str, Any]:
    with factory() as db:
        allowance, sub = db.execute(
            select(PurchasedAllowance, ExternalSubscription).join(
                ExternalSubscription, ExternalSubscription.subscription_id == PurchasedAllowance.subscription_id
            )
        ).one()
        return dict(
            schema_version=1,
            event_type="allowance_exhausted",
            tenant_id="anytoolai",
            region="ru",
            user_id=str(sub.user_id),
            allowance_id=str(allowance.allowance_id),
            product_id=allowance.product_id,
            metric_key=allowance.metric_key,
            unit=allowance.unit,
            quantity=allowance.quantity,
            occurred_at=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )


def hint(factory: SessionFactory) -> BillingWorkItem | None:
    with factory() as db:
        return db.scalar(
            select(BillingWorkItem).where(BillingWorkItem.work_kind == BillingWorkKind.ALLOWANCE_EXHAUSTION)
        )


async def test_commit_ack_duplicate_after_completion_never_revives_or_mutates(
    production_scenario: tuple, receiver: tuple, postgres_session_factory: SessionFactory
) -> None:
    factory = postgres_session_factory
    await reconcile(production_scenario, factory)
    client, config = receiver
    body = payload(factory)
    before = billing_snapshot(factory)
    first = await client.post(PATH, json=body, headers=headers(config.backend_consumers[0]))
    assert first.status_code == 204 and first.headers["Cache-Control"] == "no-store"
    stored = hint(factory)
    assert stored.payload_document == body
    worker = BillingWorker(config, factory, None)
    try:
        # Local processing does not need LBX or make any external call.
        assert await worker.tick(WorkLane.LOCAL)
    finally:
        await worker.aclose()
    done = hint(factory)
    assert done.work_state == BillingWorkState.COMPLETED
    after = billing_snapshot(factory)
    for table in before:
        if table != "billing_work_items":
            assert after[table] == before[table], table
    with factory() as db:
        reconciliation = db.scalar(
            select(BillingWorkItem).where(BillingWorkItem.work_kind == BillingWorkKind.SUBSCRIPTION_RECONCILIATION)
        )
        assert reconciliation is not None
    changed = {**body, "occurred_at": (datetime.now(UTC) + timedelta(seconds=1)).isoformat()}
    assert (await client.post(PATH, json=changed, headers=headers(config.backend_consumers[0]))).status_code == 204
    assert hint(factory).payload_document == body
    from alembic import command
    from apps.api.tests.support.postgres import alembic_test_config

    with alembic_test_config(factory.kw["bind"].url) as migration:
        with pytest.raises(RuntimeError, match="Exhaustion history downgrade is unsafe"):
            command.downgrade(migration, "20261111_0010")
    assert hint(factory).work_state == BillingWorkState.COMPLETED
    assert hint(factory).enqueue_generation == done.enqueue_generation


@pytest.mark.parametrize(
    "field,value,status",
    [
        ("quantity", 900, 409),
        ("unit", "foreign", 409),
        ("metric_key", "foreign.metric", 409),
        ("allowance_id", str(uuid4()), 409),
        ("user_id", str(uuid4()), 409),
        ("product_id", "foreign", 403),
        ("region", "foreign", 403),
        ("schema_version", True, 422),
        ("quantity", True, 422),
        ("quantity", 1.5, 422),
        ("quantity", 2**53, 422),
        ("occurred_at", "2026-11-11T05:00:00+03:00", 422),
        ("event_type", "unknown", 422),
    ],
)
async def test_full_tuple_scope_and_shape_refusal(
    production_scenario: tuple,
    receiver: tuple,
    postgres_session_factory: SessionFactory,
    field: str,
    value: object,
    status: int,
) -> None:
    factory = postgres_session_factory
    await reconcile(production_scenario, factory)
    client, config = receiver
    body = {**payload(factory), field: value}
    response = await client.post(PATH, json=body, headers=headers(config.backend_consumers[0]))
    assert response.status_code == status, response.text
    assert response.headers["Cache-Control"] == "no-store" and hint(factory) is None


async def test_auth_permissions_browser_and_wrong_owner_refusal(
    production_scenario: tuple,
    receiver: tuple,
    postgres_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    await reconcile(production_scenario, factory)
    client, config = receiver
    body = payload(factory)
    assert (await client.post(PATH, json=body)).status_code == 401
    kernel, summary = config.backend_consumers
    assert (
        await client.post(PATH, json=body, headers={**headers(kernel), "Origin": "https://browser.test"})
    ).status_code == 403
    # Giving a foreign principal policy access cannot transfer the persisted bucket owner.
    summary = summary.model_copy(update={"allowed_products": frozenset({body["product_id"]})})
    monkeypatch.setattr(backend_auth, "settings", config.model_copy(update={"backend_consumers": (summary,)}))
    assert (await client.post(PATH, json=body, headers=headers(summary))).status_code == 403
    kernel = kernel.model_copy(update={"permissions": frozenset()})
    monkeypatch.setattr(backend_auth, "settings", config.model_copy(update={"backend_consumers": (kernel,)}))
    assert (await client.post(PATH, json=body, headers=headers(kernel))).status_code == 403
    assert hint(factory) is None


async def test_failed_commit_is_not_acknowledged_and_retry_is_durable(
    production_scenario: tuple,
    receiver: tuple,
    postgres_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    await reconcile(production_scenario, factory)
    client, config = receiver
    body = payload(factory)
    original = Session.commit

    def fail_commit(self) -> None:
        raise OperationalError("commit", {}, RuntimeError("synthetic commit failure"))

    monkeypatch.setattr(Session, "commit", fail_commit)
    result = await client.post(PATH, json=body, headers=headers(config.backend_consumers[0]))
    assert result.status_code == 503 and hint(factory) is None
    monkeypatch.setattr(Session, "commit", original)
    assert (await client.post(PATH, json=body, headers=headers(config.backend_consumers[0]))).status_code == 204
    assert hint(factory).work_state == BillingWorkState.PENDING


async def test_concurrent_delivery_is_one_immutable_hint(
    production_scenario: tuple, receiver: tuple, postgres_session_factory: SessionFactory
) -> None:
    factory = postgres_session_factory
    await reconcile(production_scenario, factory)
    client, config = receiver
    body = payload(factory)
    replies = await asyncio.gather(
        *(client.post(PATH, json=body, headers=headers(config.backend_consumers[0])) for _ in range(6))
    )
    assert [r.status_code for r in replies] == [204] * 6
    with factory() as db:
        assert len(list(db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == exhaustion.KIND)))) == 1
    assert hint(factory).payload_document == body and hint(factory).enqueue_generation == 0


async def test_old_cycle_hint_is_accepted_without_touching_new_cycle(
    production_scenario: tuple, receiver: tuple, postgres_session_factory: SessionFactory
) -> None:
    factory = postgres_session_factory
    await reconcile(production_scenario, factory)
    body = payload(factory)
    transport = production_scenario[0]
    transport.subscriptions[0].update(
        last_tariffication_period_start="2026-11-30", last_tariffication_period_end="2026-12-30"
    )
    await reconcile(production_scenario, factory)
    client, config = receiver
    assert (await client.post(PATH, json=body, headers=headers(config.backend_consumers[0]))).status_code == 204
    before = billing_snapshot(factory)
    claim = work.claim_work(factory, config, WorkLane.LOCAL)
    assert claim.kind == exhaustion.KIND
    exhaustion.process_exhaustion(factory, claim)
    after = billing_snapshot(factory)
    for table in before:
        if table != "billing_work_items":
            assert after[table] == before[table]
    before_queue = {r["work_item_id"]: r for r in before["billing_work_items"] if r["work_kind"] != exhaustion.KIND}
    after_queue = {r["work_item_id"]: r for r in after["billing_work_items"] if r["work_kind"] != exhaustion.KIND}
    assert after_queue == before_queue
    assert hint(factory).work_state == BillingWorkState.COMPLETED


async def test_authenticated_synthetic_backend_owns_its_issued_allowance(
    migrated_database: Engine,
    receiver: tuple,
    postgres_session_factory: SessionFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    seed(factory)
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, tzinfo=UTC))
    transport = PurchaseTransport()
    config = source_settings()
    manifest = httpx.MockTransport(lambda request: httpx.Response(200, json=summary_manifest()))
    lbx = httpx.MockTransport(transport.respond)
    fresh = await fresh_link_evaluation(
        config,
        selection=link_selection(product_id="synthetic_summary"),
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
            sources, config, factory=factory, token=TOKEN, product_id="synthetic_summary"
        )
        purchase = await purchases.confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="summary-exhaustion",
            meaning=reviewed_meaning(
                "synthetic_summary", link.mapping_revision_id, offer.fingerprint, documents, terms
            ),
        )
        linked = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        materialize_allowance(db, sub, linked.accepted, cycle(), skew_seconds=5)
        db.commit()
    body = payload(factory)
    with factory() as db:
        assert allowance_backend(config, db.scalar(select(PurchasedAllowance))).consumer_id == "synthetic-summary"
    client, receiver_config = receiver
    kernel, summary = receiver_config.backend_consumers
    before = billing_snapshot(factory)
    assert (await client.post(PATH, json=body, headers=headers(kernel))).status_code == 403
    assert (await client.post(PATH, json=body, headers=headers(summary))).status_code == 204
    assert hint(factory).payload_document == body
    assert body["quantity"] == 13
    claim = work.claim_work(factory, receiver_config, WorkLane.LOCAL)
    exhaustion.process_exhaustion(factory, claim)
    assert hint(factory).work_state == BillingWorkState.COMPLETED
    after = billing_snapshot(factory)
    for table in before:
        if table != "billing_work_items":
            assert before[table] == after[table]


def test_openapi_describes_actual_security_and_errors() -> None:
    schema = create_app().openapi()
    operation = schema["paths"][PATH]["post"]
    assert operation["security"] == [{"BackendServiceBearer": []}]
    assert {"204", "401", "403", "409", "422", "503"} <= operation["responses"].keys()


@pytest.mark.parametrize("paid_terms_scenario", ["proposal_ai"], indirect=True)
async def test_historical_kernel_terms_keep_original_owner_and_bytes(
    paid_terms_scenario: Any, receiver: tuple, postgres_session_factory: SessionFactory
) -> None:
    factory = postgres_session_factory
    with factory() as db:
        sub = db.get(ExternalSubscription, paid_terms_scenario.subscription_id)
        issued = materialize_allowance(db, sub, paid_terms_scenario.accepted, cycle(), skew_seconds=5)
        db.commit()
    body = payload(factory)
    with factory() as db:
        row = db.get(PurchasedAllowance, issued.allowance_id)
        assert allowance_backend(receiver[1], row).consumer_id == "platform-kernel"
        before = row.terms_document
    client, config = receiver
    assert (await client.post(PATH, json=body, headers=headers(config.backend_consumers[0]))).status_code == 204
    with factory() as db:
        assert db.get(PurchasedAllowance, issued.allowance_id).terms_document == before


def test_forward_work_index_migration_preserves_populated_history(
    postgres_engine: Engine, database_test_url: URL
) -> None:
    from alembic import command
    from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema
    from sqlalchemy import text

    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as migration:
        command.upgrade(migration, "20261111_0010")
        with postgres_engine.begin() as connection:
            connection.execute(
                text("""
                INSERT INTO billing_work_items
                (work_item_id, work_kind, scope_kind, scope_reference, coalescing_key,
                 payload_schema_version, payload_document, next_attempt_at, work_state)
                VALUES (:id, 'subscription_reconciliation', 'subscription', 'retained', 'retained',
                        'billing-work:v1', '{}', now(), 'completed')
            """),
                {"id": uuid4()},
            )
            before = connection.execute(text("SELECT * FROM billing_work_items")).mappings().all()
        command.upgrade(migration, "head")
        with postgres_engine.connect() as connection:
            assert connection.execute(text("SELECT * FROM billing_work_items")).mappings().all() == before
            index = connection.scalar(
                text("SELECT indexdef FROM pg_indexes WHERE indexname = 'uq_billing_work_items_recurring'")
            )
            assert "allowance_exhaustion" in index
