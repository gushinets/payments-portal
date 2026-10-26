"""Current catalog semantics: independent discovery, live selected offer, no-store."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
import time

import httpx
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import catalog as catalog_composition
from app.composition.sources import source_resources
from app.domains.catalog import router as catalog_http
from app.domains.catalog.link_publication import publish_product_link, LinkPublicationResult
from app.domains.catalog.product_link import ProductLinkDocument
from app.main import create_app
from apps.api.tests.support.any709_step1 import link_document, recording, step1_settings
from apps.api.tests.support.kernel import manifest_fixture
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording


pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def publish(factory: sessionmaker[Session], document: ProductLinkDocument) -> LinkPublicationResult:
    return publish_product_link(
        factory,
        evaluation=document,
        expected_previous_revision=0,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
    )


@pytest.fixture
async def client(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[httpx.AsyncClient, SelectedOfferRecording]]:
    source = recording()
    config = step1_settings()
    monkeypatch.setattr(catalog_http, "settings", config)
    monkeypatch.setattr(catalog_composition, "SessionLocal", postgres_session_factory)
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 26, tzinfo=UTC))
    app = create_app()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest_fixture())),
        lbx_transport=httpx.MockTransport(source.respond),
    ) as sources:
        app.state.sources = sources
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as http:
            yield http, source


async def test_any709_step1_discovery_is_not_limited_by_mapping_or_billing(
    client: tuple[httpx.AsyncClient, SelectedOfferRecording],
) -> None:
    http, source = client
    response = await http.get("/api/catalog/products")
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert response.json()["products"] == [
        {
            "product_id": "proposal_ai",
            "kernel_provenance": "SIMULATED",
            "availability": "DETAILS_REQUIRED",
            "availability_reason": None,
            "offer": None,
        }
    ]
    assert source.requests == []
    detail = await http.get("/api/catalog/products/proposal_ai")
    assert detail.json()["availability"] == "UNMAPPED" and detail.json()["offer"] is None
    assert source.requests == []
    missing = await http.get("/api/catalog/products/unknown")
    assert missing.status_code == 404 and missing.headers["cache-control"] == "no-store"


async def test_any709_step1_selected_detail_reads_live_exact_values_and_never_leaks_ids(
    client: tuple[httpx.AsyncClient, SelectedOfferRecording],
    postgres_session_factory: sessionmaker[Session],
) -> None:
    http, source = client
    stored = publish(postgres_session_factory, link_document()).stored
    first = await http.get("/api/catalog/products/proposal_ai")
    assert first.status_code == 200 and first.headers["cache-control"] == "no-store"
    body = first.json()
    assert body["kernel_provenance"] == "SIMULATED"
    assert body["offer"]["billing_provenance"] == "CONFIGURED_SOURCE"
    assert body["offer"]["money"]["recurring_amount"] == "100.01"
    assert body["offer"]["commercial_quantity"] == "1"
    assert body["offer"]["revision_id"] == str(stored.mapping_revision_id)
    assert source.counts == {"tariff": 2, "periods": 2, "services": 2, "prices": 2}
    for name in ("services", "prices"):
        source.replace(name, '"price":100.01', '"price":200.02')
    second = (await http.get("/api/catalog/products/proposal_ai")).json()
    assert second["offer"]["money"]["recurring_amount"] == "200.02"
    assert second["offer"]["revision_id"] == body["offer"]["revision_id"]
    for private in ("tariff_id", "price_id", "external_billing_account_id", "approvals", "password", "allowance"):
        assert private not in first.text


async def test_any709_step1_source_failures_and_unsupported_are_explicit_no_store(
    client: tuple[httpx.AsyncClient, SelectedOfferRecording],
    postgres_session_factory: sessionmaker[Session],
) -> None:
    http, source = client
    publish(postgres_session_factory, link_document())
    source.replace("services", '"periodic_service":1', '"periodic_service":0')
    unsupported = await http.get("/api/catalog/products/proposal_ai")
    assert unsupported.json()["availability"] == "OFFER_UNSUPPORTED"
    assert unsupported.json()["offer"] is None
    source.replace("services", '"periodic_service":0', '"periodic_service":1')
    source.replace("prices", '"code":200', '"code":500')
    failed = await http.get("/api/catalog/products/proposal_ai")
    assert failed.status_code == 503 and failed.headers["cache-control"] == "no-store"
    assert failed.json()["detail"]["code"] == "catalog_unavailable"


async def test_any709_step1_invalid_current_head_never_falls_back(
    client: tuple[httpx.AsyncClient, SelectedOfferRecording],
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.models import CommercialProductHead

    publish(postgres_session_factory, link_document())
    with postgres_session_factory() as db:
        head = db.get(CommercialProductHead, (link_document().scope.external_billing_account_id, "proposal_ai"))
        head.revision_number = 999
        db.commit()
    response = await client[0].get("/api/catalog/products/proposal_ai")
    assert response.status_code == 503 and response.headers["cache-control"] == "no-store"


async def test_any709_step1_database_failure_is_internal_and_never_cacheable(
    client: tuple[httpx.AsyncClient, SelectedOfferRecording],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sqlalchemy.exc import OperationalError

    def failed_database() -> Session:
        raise OperationalError("private query", {}, Exception("private database value"))

    monkeypatch.setattr(catalog_composition, "SessionLocal", failed_database)
    response = await client[0].get("/api/catalog/products/proposal_ai")
    assert response.status_code == 500 and response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": {"code": "internal_server_error"}}
    assert "private" not in response.text


def test_any709_step1_openapi_keeps_named_normalized_contracts() -> None:
    schema = create_app().openapi()
    assert schema["components"]["schemas"]["CatalogOffer"]["properties"]["commercial_quantity"]["type"] == "string"
    assert schema["components"]["schemas"]["CatalogMoney"]["properties"]["recurring_amount"]["type"] == "string"
    for path in ("/api/catalog/products", "/api/catalog/products/{product_id}"):
        assert "$ref" in schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
