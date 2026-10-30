"""Real PostgreSQL user-lock contention with synthetic source/HTTP boundaries."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import review_purchase
from app.composition.sources import source_resources
from app.domains.purchases import router as purchase_routes
from app.domains.purchases.contracts import LegalSelection, PurchaseMeaning
from app.http.dependencies import get_session_factory
from app.main import create_app
from app.models import BillingPurchaseScopeHold, ExternalCreateOperation, LegalAcceptanceEvent, PurchaseIntent, User
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
async def test_same_key_confirmation_during_user_lock_preserves_one_acceptance(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
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
            link, offer, documents, _ = await review_purchase(
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
                holder.scalar(select(User).with_for_update())
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
