"""Real PostgreSQL user-lock contention with synthetic source/HTTP boundaries."""

from __future__ import annotations

import asyncio
from contextvars import ContextVar
from datetime import UTC, datetime
from threading import Event

import httpx
import pytest
from sqlalchemy import event, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import review_purchase
from app.composition.sources import source_resources
from app.domains.purchases import router as purchase_routes
from app.domains.billing import router as billing_routes
from app.domains.purchases.contracts import LegalSelection, PurchaseMeaning
from app.http.dependencies import get_session_factory
from app.main import create_app
from app.models import (
    BillingPurchaseScopeHold,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    LegalAcceptanceEvent,
    PurchaseIntent,
    User,
)
from app.infrastructure.persistence.billing_connections import lock_connection_scope
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step2_postgres import TOKEN
from apps.api.tests.test_any709_step3_postgres import accept, setup_purchase

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fixed_billing_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize("lock_kind", ["user", "origin"])
async def test_same_key_confirmation_during_user_lock_preserves_one_acceptance(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
    lock_kind: str,
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    # The holder is intentionally another request's transaction, not source I/O's.
    transport.pool = None
    config = step1_settings()
    monkeypatch.setattr(purchase_routes, "settings", config)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: factory
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        app.state.sources = sources
        original = await accept(sources, factory) if existing else None
        if original is not None:
            meaning = original.accepted.meaning
        else:
            link, offer, documents, _terms = await review_purchase(
                sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
            )
            meaning = PurchaseMeaning(
                product_id="proposal_ai",
                revision_id=link.mapping_revision_id,
                expected_fingerprint=offer.fingerprint,
                documents=tuple(
                    LegalSelection(
                        document_version_id=document.document_version_id,
                        acceptance_text_hash=document.acceptance_text_hash,
                    )
                    for document in documents
                ),
            )
        headers = {"Authorization": "Bearer " + TOKEN, "Idempotency-Key": "one-request", "X-Request-ID": "lock-test"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://portal.test"
        ) as client:
            before = len(transport.requests)
            with factory() as holder:
                if lock_kind == "user":
                    holder.scalar(select(User).with_for_update())
                else:
                    lock_connection_scope(
                        holder,
                        tenant_id=config.instance_tenant_id,
                        region=config.instance_region,
                        provider_origin=config.lbx_provider_origin,
                    )
                response = await client.post(
                    "/api/purchase-intents", json=meaning.model_dump(mode="json"), headers=headers
                )
                assert response.headers["cache-control"] == "no-store"
                if original is not None:
                    assert response.status_code == 200
                    assert response.json()["purchase_intent_id"] == str(original.id)
                    assert response.json()["accepted"]["expected_fingerprint"] == meaning.expected_fingerprint
                    changed = meaning.model_copy(update={"expected_fingerprint": "sha256:" + "0" * 64})
                    conflict = await client.post(
                        "/api/purchase-intents", json=changed.model_dump(mode="json"), headers=headers
                    )
                    assert conflict.status_code == 409
                    assert conflict.json()["detail"]["code"] == "purchase_idempotency_conflict"
                    assert len(transport.requests) == before
                else:
                    assert response.status_code == 503
                    assert response.json()["detail"] == {"code": "billing_busy", "request_id": "lock-test"}
                    with factory() as observer:
                        for model in (
                            ExternalBillingCustomer,
                            PurchaseIntent,
                            BillingPurchaseScopeHold,
                            LegalAcceptanceEvent,
                            ExternalCreateOperation,
                        ):
                            assert observer.scalar(select(func.count()).select_from(model)) == 0
            # A separate explicit retry retains the key and meaning after rollback/release.
            resumed = await client.post("/api/purchase-intents", json=meaning.model_dump(mode="json"), headers=headers)
            assert resumed.status_code == 200
            replay = await client.post("/api/purchase-intents", json=meaning.model_dump(mode="json"), headers=headers)
            assert replay.status_code == 200 and replay.json() == resumed.json()
            if original is not None:
                assert resumed.json()["purchase_intent_id"] == str(original.id)
            assert not any(request.method == "POST" for request in transport.requests)
    with factory() as db:
        for model in (PurchaseIntent, BillingPurchaseScopeHold, LegalAcceptanceEvent):
            assert db.scalar(select(func.count()).select_from(model)) == 1
        assert db.scalar(select(func.count()).select_from(ExternalCreateOperation)) == 3


@pytest.mark.parametrize(
    ("key", "change_fingerprint", "expected_error"),
    [
        pytest.param("one-request", False, None, id="same-key-same-terms"),
        pytest.param("one-request", True, "purchase_idempotency_conflict", id="same-key-changed-terms"),
        pytest.param("other-request", False, "purchase_scope_occupied", id="different-key"),
    ],
)
async def test_confirm_key_and_scope_across_commit(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    change_fingerprint: bool,
    expected_error: str | None,
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    # The competing confirmation may read sources while the observer holds a DB connection.
    transport.pool = None
    config = step1_settings()
    monkeypatch.setattr(purchase_routes, "settings", config)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: factory
    observer_request = ContextVar("observer_request", default=False)
    loop = asyncio.get_running_loop()
    before_scope_read, resume = asyncio.Event(), Event()

    def pause_scope_read(conn: object, cursor: object, statement: str, *args: object) -> None:
        if (
            observer_request.get()
            and not resume.is_set()
            and statement.lstrip().startswith("SELECT")
            and "billing_purchase_scope_holds" in statement
        ):
            # The old path already looked up the key. The combined SELECT reads both after the commit.
            loop.call_soon_threadsafe(before_scope_read.set)
            assert resume.wait(10), "competing confirmation did not finish"

    async with (
        source_resources(
            config,
            kernel_transport=httpx.MockTransport(transport.kernel),
            lbx_transport=httpx.MockTransport(transport.respond),
        ) as sources,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client,
    ):
        app.state.sources = sources
        link, offer, documents, terms = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
        meaning = PurchaseMeaning(
            product_id="proposal_ai",
            revision_id=link.mapping_revision_id,
            expected_fingerprint=offer.fingerprint,
            expected_technical_terms_digest=terms.confirmation_digest() if terms else None,
            documents=tuple(
                LegalSelection(
                    document_version_id=document.document_version_id,
                    acceptance_text_hash=document.acceptance_text_hash,
                )
                for document in documents
            ),
        )
        observer_meaning = meaning
        if change_fingerprint:
            observer_meaning = meaning.model_copy(update={"expected_fingerprint": "sha256:" + "0" * 64})
        headers = {"Authorization": "Bearer " + TOKEN}

        async def observe_confirmation() -> httpx.Response:
            marker = observer_request.set(True)
            try:
                return await client.post(
                    "/api/purchase-intents",
                    json=observer_meaning.model_dump(mode="json"),
                    headers={**headers, "Idempotency-Key": key},
                )
            finally:
                observer_request.reset(marker)

        event.listen(migrated_database, "before_cursor_execute", pause_scope_read)
        try:
            observer = asyncio.create_task(observe_confirmation())
            try:
                await asyncio.wait_for(before_scope_read.wait(), timeout=10)
                saved = await client.post(
                    "/api/purchase-intents",
                    json=meaning.model_dump(mode="json"),
                    headers={**headers, "Idempotency-Key": "one-request"},
                )
                assert saved.status_code == 200, saved.text
            finally:
                resume.set()
                replay = await observer
        finally:
            event.remove(migrated_database, "before_cursor_execute", pause_scope_read)

    if expected_error is None:
        assert replay.status_code == 200, replay.text
        assert replay.json()["purchase_intent_id"] == saved.json()["purchase_intent_id"]
    else:
        assert replay.status_code == 409, replay.text
        assert replay.json()["detail"]["code"] == expected_error
    with factory() as db:
        for model in (PurchaseIntent, BillingPurchaseScopeHold, LegalAcceptanceEvent):
            assert db.scalar(select(func.count()).select_from(model)) == 1
    for path in ("/users", "/agreements", "/subscriptions"):
        assert transport.creates(path) == 0


async def test_widget_origin_contention_returns_safe_busy_then_reopens(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    transport.pool = None  # The holder below deliberately owns a separate DB unit.
    monkeypatch.setattr(billing_routes, "settings", config)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: factory
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        app.state.sources = sources
        headers = {"Authorization": "Bearer " + TOKEN, "X-Request-ID": "origin-widget-test"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://portal.test"
        ) as client:
            with factory() as holder:
                lock_connection_scope(
                    holder,
                    tenant_id=config.instance_tenant_id,
                    region=config.instance_region,
                    provider_origin=config.lbx_provider_origin,
                )
                busy = await client.post("/api/billing/widget-bootstrap", json={}, headers=headers)
                assert busy.status_code == 503 and busy.headers["cache-control"] == "no-store"
                assert busy.json()["detail"] == {"code": "billing_busy", "request_id": "origin-widget-test"}
                assert not transport.requests
                with factory() as db:
                    for model in (ExternalBillingCustomer, ExternalCreateOperation, PurchaseIntent):
                        assert db.scalar(select(func.count()).select_from(model)) == 0
            transport.pool = migrated_database.pool
            opened = await client.post("/api/billing/widget-bootstrap", json={}, headers=headers)
            reopened = await client.post("/api/billing/widget-bootstrap", json={}, headers=headers)
            assert opened.status_code == reopened.status_code == 200
            assert opened.json()["presentation"] == reopened.json()["presentation"] == "account"
            assert transport.creates("/users") == 1
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
