"""Owned cabinet inventory is local history, never source catalog or payment proof."""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import advance_purchase, confirm_purchase, review_purchase
from app.composition.sources import source_resources
from app.core.time import utc_now
from app.domains.catalog.link_publication import publish_product_link
from app.domains.purchases import financial, router as routes
from app.domains.purchases.contracts import LegalSelection, PurchaseMeaning
from app.http.dependencies import get_session_factory
from app.models import AuthSession, User
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.test_any709_review_fixes_postgres import add_second_period
from apps.api.tests.test_any709_step2_postgres import TOKEN
from apps.api.tests.test_any709_step3_postgres import accept, setup_purchase

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fixed_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


async def test_owned_inventory_paginates_without_sources_and_never_discloses_other_users(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    manifest = add_second_period(transport)
    publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(product_id="brief_decoder", period_id=9902)),
        expected_previous_revision=0,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    )
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest)),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        first = await accept(sources, factory)
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=first.id)
        link, offer, docs, _ = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="brief_decoder"
        )
        second = await confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="second-product",
            meaning=PurchaseMeaning(
                product_id="brief_decoder",
                revision_id=link.mapping_revision_id,
                expected_fingerprint=offer.fingerprint,
                documents=tuple(
                    LegalSelection(
                        document_version_id=doc.document_version_id, acceptance_text_hash=doc.acceptance_text_hash
                    )
                    for doc in docs
                ),
            ),
        )
    with factory() as db:
        other = User(
            id=uuid4(),
            tenant_id=config.instance_tenant_id,
            region=config.instance_region,
            email="other@example.com",
            email_normalized="other@example.com",
            email_verified_at=utc_now(),
        )
        db.add(other)
        db.flush()
        db.add(
            AuthSession(
                user_id=other.id,
                tenant_id=other.tenant_id,
                region=other.region,
                token_hash=hashlib.sha256(b"another-owner").hexdigest(),
                expires_at=utc_now() + timedelta(days=1),
            )
        )
        db.commit()
    monkeypatch.setattr(routes, "settings", config)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_session_factory] = lambda: factory
    # No source resources are installed: inventory and deep-link reads must remain local.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client:
        headers = {"Authorization": "Bearer " + TOKEN}
        page = await client.get("/api/purchase-intents?limit=1", headers=headers)
        assert page.status_code == 200 and page.headers["Cache-Control"] == "no-store"
        body = page.json()
        assert len(body["purchases"]) == 1 and body["next_cursor"]
        following = await client.get(
            "/api/purchase-intents", params={"after": body["next_cursor"], "limit": 1}, headers=headers
        )
        rows = body["purchases"] + following.json()["purchases"]
        assert {row["purchase_intent_id"] for row in rows} == {str(first.id), str(second.id)}
        assert {row["state"] for row in rows} == {"linked", "created"}
        assert {row["product_id"] for row in rows} == {"proposal_ai", "brief_decoder"}
        assert following.json()["next_cursor"] is None
        assert all(set(row) == {"purchase_intent_id", "product_id", "state", "created_at"} for row in rows)
        assert (
            await client.get("/api/purchase-intents", headers={"Authorization": "Bearer another-owner"})
        ).json() == {"purchases": [], "next_cursor": None}
        assert (
            await client.get(f"/api/purchase-intents/{first.id}", headers={"Authorization": "Bearer another-owner"})
        ).status_code == 404
        assert (await client.get("/api/purchase-intents")).status_code == 401
        for query in ("limit=0", "limit=101", "after=invalid"):
            assert (await client.get("/api/purchase-intents?" + query, headers=headers)).status_code == 422
        financial.changed_unsent_terms(factory, second)
        remaining = (await client.get("/api/purchase-intents", headers=headers)).json()["purchases"]
        assert [row["purchase_intent_id"] for row in remaining] == [str(first.id)]
        history = await client.get(f"/api/purchase-intents/{second.id}", headers=headers)
        assert history.json()["state"] == "failed_before_external_effect"
        assert history.json()["scope_held"] is False


async def test_unverified_account_cannot_read_inventory(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = postgres_session_factory
    setup_purchase(factory)
    with factory() as db:
        user = db.scalar(select(User))
        user.email_verified_at = None
        db.commit()
    monkeypatch.setattr(routes, "settings", step1_settings())
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_session_factory] = lambda: factory
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client:
        result = await client.get("/api/purchase-intents", headers={"Authorization": "Bearer " + TOKEN})
        assert result.status_code == 403 and result.json()["detail"]["code"] == "billing_email_verification_required"
