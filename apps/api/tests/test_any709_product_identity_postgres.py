"""Published source product identity must remain usable through purchase and Widget."""

from __future__ import annotations
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

import asyncio
import time
from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from app.composition.mapping_operator import fresh_link_evaluation
from app.composition.sources import source_resources
from app.domains.billing import router as billing_routes
from app.domains.catalog import router as catalog_routes
from app.domains.catalog.link_publication import publish_product_link
from app.domains.purchases import router as purchase_routes
from app.http.dependencies import get_session_factory
from apps.api.tests.support.any709_step1 import link_selection, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.kernel import manifest_fixture, resign
from apps.api.tests.test_any709_step2_postgres import seed, TOKEN

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("length", [256, 257, 1024])
def test_published_source_product_reaches_payment_widget(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    length: int,
) -> None:
    factory = postgres_session_factory
    config = step1_settings()
    seed(factory)
    product_id = "p" * length
    manifest = manifest_fixture()
    for item in manifest["products"]:
        if item["product_id"] == "proposal_ai":
            item["product_id"] = product_id
    for item in manifest["usage_metrics"]:
        if item["product_id"] == "proposal_ai":
            item["product_id"] = product_id
    manifest = resign(manifest)
    transport = PurchaseTransport()
    kernel = httpx.MockTransport(lambda request: httpx.Response(200, json=manifest))
    lbx = httpx.MockTransport(transport.respond)
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, tzinfo=UTC))
    monkeypatch.setattr(billing_routes, "settings", config)
    monkeypatch.setattr(catalog_routes, "settings", config)
    monkeypatch.setattr(purchase_routes, "settings", config)
    app = FastAPI()
    app.include_router(billing_routes.router)
    app.include_router(catalog_routes.router)
    app.include_router(purchase_routes.router)
    app.dependency_overrides[get_session_factory] = lambda: factory

    async def scenario() -> None:
        fresh = await fresh_link_evaluation(
            config,
            selection=link_selection(product_id=product_id),
            principal="os-euid:29001",
            kernel_transport=kernel,
            lbx_transport=lbx,
        )
        publish_product_link(
            factory,
            evaluation=fresh.document,
            expected_previous_revision=0,
            deadline=time.monotonic() + 10,
            lock_timeout_seconds=1,
            provider_origin=config.lbx_provider_origin,
        )
        async with source_resources(config, kernel_transport=kernel, lbx_transport=lbx) as sources:
            app.state.sources = sources
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://portal.test",
                headers={"Authorization": "Bearer " + TOKEN},
            ) as client:
                catalog = await client.get("/api/catalog/products/" + product_id)
                assert catalog.status_code == 200, catalog.text
                assert catalog.json()["availability"] == "CURRENT_OFFER"
                current = await client.get("/api/purchase-intents/current", params={"product_id": product_id})
                reviewed = await client.post("/api/purchases/review", json={"product_id": product_id})
                # A source-valid and successfully published product must use the
                # same identifier contract at the purchase HTTP boundary.
                assert (current.status_code, reviewed.status_code) == (200, 200), (
                    current.status_code,
                    reviewed.status_code,
                    current.json().get("detail"),
                    reviewed.json().get("detail"),
                )
                meaning = reviewed.json()
                confirmed = await client.post(
                    "/api/purchase-intents",
                    headers={"Idempotency-Key": "long-id"},
                    json={
                        "product_id": product_id,
                        "revision_id": meaning["revision_id"],
                        "expected_fingerprint": meaning["expected_fingerprint"],
                        "documents": [
                            {
                                "document_version_id": doc["document_version_id"],
                                "acceptance_text_hash": doc["acceptance_text_hash"],
                            }
                            for doc in meaning["documents"]
                        ],
                    },
                )
                assert confirmed.status_code == 200, confirmed.text
                purchase_id = confirmed.json()["purchase_intent_id"]
                advanced = await client.post("/api/purchase-intents/" + purchase_id + "/advance")
                assert advanced.status_code == 200, advanced.text
                assert advanced.json()["state"] == "linked"
                widget = await client.post("/api/billing/widget-bootstrap", json={"purchase_intent_id": purchase_id})
                assert widget.status_code == 200, widget.text
                assert widget.json()["disablePayments"] is False
                assert confirmed.json()["paid_access_granted"] is False
                after = await client.get("/api/purchase-intents/current", params={"product_id": product_id})
                assert after.status_code == 200 and after.json()["purchase"]["product_id"] == product_id
                invalid = "p" * 1025
                for path, body in [
                    ("/api/purchases/review", {"product_id": invalid}),
                    (
                        "/api/purchase-intents",
                        {
                            "product_id": invalid,
                            "revision_id": meaning["revision_id"],
                            "expected_fingerprint": meaning["expected_fingerprint"],
                            "documents": [
                                {
                                    "document_version_id": doc["document_version_id"],
                                    "acceptance_text_hash": doc["acceptance_text_hash"],
                                }
                                for doc in meaning["documents"]
                            ],
                        },
                    ),
                ]:
                    refused = await client.post(path, json=body)
                    assert refused.status_code == 422
                    assert any(
                        error["loc"][-1] == "product_id" and error["type"] == "string_too_long"
                        for error in refused.json()["detail"]
                    )
                refused = await client.get("/api/purchase-intents/current", params={"product_id": invalid})
                assert refused.status_code == 422
                assert any(
                    error["loc"][-1] == "product_id" and error["type"] == "string_too_long"
                    for error in refused.json()["detail"]
                )

    asyncio.run(scenario())
