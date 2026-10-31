"""Current catalog semantics: independent discovery, live selected offer, no-store."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
import time
import threading

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import catalog as catalog_composition
from app.composition.sources import source_resources
from app.domains.catalog import router as catalog_http
from app.domains.catalog.link_publication import publish_product_link, LinkPublicationResult
from app.domains.catalog.product_link import ProductLinkDocument
from app.domains.catalog.commercial_offer import OfferRefusalKind, SelectedOfferRefused, SelectedOfferSourceFailed
from app.main import create_app
from app.http.dependencies import get_session_factory
from apps.api.tests.support.any709_step1 import link_document, recording, step1_settings
from apps.api.tests.support.kernel import manifest_fixture, resign
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
def application(postgres_session_factory: sessionmaker[Session]) -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: postgres_session_factory
    return app


@pytest.fixture
async def client(
    migrated_database: Engine,
    application: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[httpx.AsyncClient, SelectedOfferRecording]]:
    source = recording()
    config = step1_settings()
    monkeypatch.setattr(catalog_http, "settings", config)
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 26, tzinfo=UTC))
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest_fixture())),
        lbx_transport=httpx.MockTransport(lambda request: source.respond(request)),
    ) as sources:
        application.state.sources = sources
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://portal.test"
        ) as http:
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


@pytest.mark.parametrize(
    "failure,expected_status,availability",
    [
        (SelectedOfferSourceFailed("temporary_failure"), 503, None),
        (SelectedOfferRefused(OfferRefusalKind.INCOMPLETE, "lbx_missing_field"), 200, "OFFER_INCOMPLETE"),
        (SelectedOfferRefused(OfferRefusalKind.NOT_SELLABLE, "lbx_unsupported_profile"), 200, "OFFER_UNSUPPORTED"),
    ],
)
async def test_catalog_failure_category_uses_type_instead_of_reason_prefix(
    client: tuple[httpx.AsyncClient, SelectedOfferRecording],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: SelectedOfferRefused,
    expected_status: int,
    availability: str | None,
) -> None:
    publish(postgres_session_factory, link_document())

    async def refused(*args: object, **kwargs: object) -> None:
        raise failure

    monkeypatch.setattr(catalog_composition, "read_current_offer", refused)
    response = await client[0].get("/api/catalog/products/proposal_ai")
    assert response.status_code == expected_status and response.headers["cache-control"] == "no-store"
    if availability is None:
        assert response.json()["detail"]["reason"] == failure.code
    else:
        assert response.json()["availability"] == availability and response.json()["offer"] is None


async def test_catalog_uses_injected_worker_owned_session_and_closes_it_before_http(
    client: tuple[httpx.AsyncClient, SelectedOfferRecording],
    application: FastAPI,
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    publish(postgres_session_factory, link_document())
    caller_thread = threading.get_ident()
    active: set[int] = set()
    sessions: list[Session] = []

    class OwnedSession(Session):
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.owner_thread = threading.get_ident()
            assert self.owner_thread != caller_thread
            super().__init__(*args, **kwargs)
            sessions.append(self)
            active.add(id(self))

        def close(self) -> None:
            assert threading.get_ident() == self.owner_thread
            super().close()
            active.discard(id(self))

    factory = sessionmaker(bind=migrated_database, class_=OwnedSession, autoflush=False)
    application.dependency_overrides[get_session_factory] = lambda: factory
    respond = client[1].respond

    def no_session_during_http(request: httpx.Request) -> httpx.Response:
        assert not active
        return respond(request)

    monkeypatch.setattr(client[1], "respond", no_session_during_http)
    response = await client[0].get("/api/catalog/products/proposal_ai")
    assert response.status_code == 200
    assert response.json()["availability"] == "CURRENT_OFFER"
    assert len(sessions) == 1 and not active


@pytest.mark.parametrize("source_available", [True, False])
async def test_catalog_empty_source_is_distinct_from_source_failure_and_unknown_product(
    application: FastAPI, monkeypatch: pytest.MonkeyPatch, source_available: bool
) -> None:
    config = step1_settings(lbx_widget_signing_secret="", lbx_seller_organization_id="")
    monkeypatch.setattr(catalog_http, "settings", config)
    manifest = manifest_fixture()
    manifest["products"], manifest["usage_metrics"] = [], []
    manifest = resign(manifest)
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(
            lambda request: httpx.Response(200, json=manifest) if source_available else httpx.Response(503)
        ),
    ) as sources:
        application.state.sources = sources
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application), base_url="http://portal.test"
        ) as http:
            listing = await http.get("/api/catalog/products")
            detail = await http.get("/api/catalog/products/unknown")
    assert listing.headers["cache-control"] == detail.headers["cache-control"] == "no-store"
    if source_available:
        assert listing.status_code == 200 and listing.json() == {"products": []}
        assert detail.status_code == 404 and detail.json()["detail"]["code"] == "catalog_product_not_found"
    else:
        assert listing.status_code == detail.status_code == 503
        assert listing.json()["detail"]["code"] == "catalog_unavailable"


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
    application: FastAPI,
) -> None:
    from sqlalchemy.exc import OperationalError

    def failed_database() -> Session:
        raise OperationalError("private query", {}, Exception("private database value"))

    application.dependency_overrides[get_session_factory] = lambda: failed_database
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
