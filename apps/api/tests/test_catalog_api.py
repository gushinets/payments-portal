"""Stored preview regressions; all source inputs are explicitly SIMULATED."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from decimal import Decimal
from typing import NoReturn

import pytest
import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.composition.mapping_operator import FreshMappingEvaluation
from app.core.database import get_db
from app.core.settings import AppEnv
from app.domains.catalog.commercial_offer import commercial_digest
from app.domains.catalog import router as catalog_http
from app.domains.catalog.publication import StoredMapping, publish_mapping
from app.infrastructure.preflight import PreflightAdmission, PreflightPolicy
from app.integrations.kernel.client import PlatformKernelClient
from app.integrations.lbx.client import LbxServerClient
from app.main import create_app
from app.models import CommercialMappingRevision
from apps.api.tests.support.commercial_mappings import SIMULATED_UID, fresh_fixture, operator_settings, reviewed_fixture
from apps.api.tests.support.kernel import manifest_fixture, resign
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording, simulated_inputs, simulated_selection


pytestmark = [pytest.mark.postgres, pytest.mark.anyio, pytest.mark.usefixtures("mapping_clock")]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def publish(factory: sessionmaker[Session], fresh: FreshMappingEvaluation, *, previous: int = 0) -> StoredMapping:
    return publish_mapping(
        factory,
        evaluation=fresh.document,
        expected_previous_revision=previous,
        deadline=fresh.deadline,
        evidence_valid_until=fresh.evidence_valid_until,
        lock_timeout_seconds=0.2,
        allow_simulated=True,
    ).stored


@pytest.fixture
async def stored(migrated_database: Engine, postgres_session_factory: sessionmaker[Session]) -> StoredMapping:
    return publish(postgres_session_factory, await fresh_fixture(await reviewed_fixture()))


@pytest.fixture
def client(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    def catalog_db() -> Iterator[Session]:
        with postgres_session_factory() as db:
            yield db

    app = create_app()
    app.dependency_overrides[get_db] = catalog_db
    # No source credentials, approval files, OS principal or preflight resource
    # is needed by browse. Do not start source resources through app lifespan.
    monkeypatch.setattr(catalog_http, "settings", operator_settings(kernel_base_url="", kernel_service_token=""))
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


async def test_anonymous_list_detail_exact_terms_and_safe_schema(client: TestClient, stored: StoredMapping) -> None:
    response = client.get("/api/catalog/products")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "authorization" not in response.request.headers
    product = response.json()["products"][0]
    assert product["product_id"] == "proposal_ai"
    assert product["availability"] == "SIMULATED_PREVIEW"
    offer = product["offer"]
    money = stored.document.material.terms.money
    assert offer["money"] == {
        "recurring_amount": format(money.recurring_amount, ".2f"),
        "connection_amount": format(money.connection_amount, ".2f"),
        "currency": "RUB",
        "decimal_places": 2,
        "units": "major",
    }
    assert offer["allowance"] == {"quantity": "25", "unit": "generation", "metric_key": "proposal_ai.test_generations"}
    assert offer["period"]["unit"] == "month"
    assert offer["revision_id"] == str(stored.mapping_revision_id)
    assert offer["publication_state"] == offer["evidence_mode"] == "SIMULATED"
    detail = client.get("/api/catalog/products/proposal_ai")
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "no-store"
    assert detail.json() == product
    assert set(offer) == {
        "offer_id",
        "revision_id",
        "revision_number",
        "evidence_mode",
        "publication_state",
        "money",
        "period",
        "allowance",
        "terms",
    }
    for private in ("external_billing_account_id", "selected_evidence", "approvals", "publisher", "manifest", "secret"):
        assert private not in response.text


async def test_empty_unknown_product_and_unconfigured_catalog_are_distinct(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.get("/api/catalog/products").json() == {"products": []}
    response = client.get("/api/catalog/products/not-a-product")
    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": {"code": "catalog_product_not_found"}}
    assert client.get("/api/catalog/products/opaque%2Fid%20%3F%23").json() == {
        "detail": {"code": "catalog_product_not_found"}
    }
    monkeypatch.setattr(
        catalog_http,
        "settings",
        operator_settings(kernel_base_url="", kernel_service_token="", mapping_account_id=""),
    )
    for path in ("/api/catalog/products", "/api/catalog/products/proposal_ai"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"detail": {"code": "catalog_unavailable"}}


async def test_latest_revision_is_selected_with_stable_public_offer_identity(
    client: TestClient, stored: StoredMapping, postgres_session_factory: sessionmaker[Session]
) -> None:
    first = client.get("/api/catalog/products/proposal_ai").json()["offer"]
    latest = publish(
        postgres_session_factory,
        await fresh_fixture(await reviewed_fixture(allowance=30, revision="SIMULATED:v2")),
        previous=1,
    )
    second = client.get("/api/catalog/products/proposal_ai").json()["offer"]
    assert second["offer_id"] == first["offer_id"]
    assert second["revision_id"] == str(latest.mapping_revision_id) != first["revision_id"]
    assert second["revision_number"] == 2
    assert second["allowance"]["quantity"] == "30"


async def test_production_excludes_persisted_simulation_after_config_switch(
    client: TestClient, stored: StoredMapping, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.get("/api/catalog/products").json()["products"]
    # No URL/configuration change can upgrade stored evidence into real approval.
    monkeypatch.setattr(catalog_http, "settings", operator_settings(kernel_base_url="https://different-source.example"))
    assert client.get("/api/catalog/products/proposal_ai").json()["evidence_mode"] == "SIMULATED"
    # Production still forbids provisional Kernel sources. Exercise catalog
    # filtering with a valid DB-only configuration, without bypassing validators.
    monkeypatch.setattr(
        catalog_http,
        "settings",
        operator_settings(
            app_env=AppEnv.PRODUCTION,
            app_public_base_url="https://portal.example.com",
            cors_allow_origins=("https://portal.example.com",),
            kernel_base_url="",
            kernel_service_token="",
            lbx_base_url="",
            lbx_external_billing_account_id="",
            lbx_server_username="",
            lbx_server_password="",
        ),
    )
    assert client.get("/api/catalog/products").json() == {"products": []}
    assert client.get("/api/catalog/products/proposal_ai").status_code == 404


@pytest.mark.parametrize("invalid", ["schema", "mode", "tenant", "region", "scale", "allowance"])
async def test_invalid_latest_is_unavailable_without_old_revision_fallback(
    client: TestClient, stored: StoredMapping, postgres_session_factory: sessionmaker[Session], invalid: str
) -> None:
    document = stored.document.model_dump(mode="json")
    if invalid == "schema":
        document["schema_version"] = "unsupported"
    elif invalid == "mode":
        document["evidence_mode"] = "UNKNOWN"
    elif invalid in {"tenant", "region"}:
        document["material"]["scope"]["tenant_id" if invalid == "tenant" else "region"] = "foreign"
    elif invalid == "scale":
        document["material"]["terms"]["money"]["decimal_places"] = None
    else:
        document["material"]["technical"]["allowance"] = True
    with postgres_session_factory() as db:
        original = db.get(CommercialMappingRevision, stored.mapping_revision_id)
        assert original is not None
        # Negative storage fixture only; all valid rows use real publication.
        db.add(
            CommercialMappingRevision(
                external_billing_account_id=original.external_billing_account_id,
                billing_offer_id=original.billing_offer_id,
                revision_number=2,
                manifest_version=original.manifest_version,
                catalog_digest=original.catalog_digest,
                mapping_schema_version=original.mapping_schema_version,
                mapping_document=document,
                published_at=original.published_at,
                published_by_principal=original.published_by_principal,
            )
        )
        db.commit()
    for path in ("/api/catalog/products", "/api/catalog/products/proposal_ai"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert response.json() == {"detail": {"code": "catalog_unavailable"}}


async def test_other_accounts_are_excluded_before_evidence_validation(
    client: TestClient,
    stored: StoredMapping,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with postgres_session_factory() as db:
        db.add(
            CommercialMappingRevision(
                external_billing_account_id="SIMULATED:foreign-account",
                billing_offer_id="foreign",
                revision_number=1,
                manifest_version="unknown",
                catalog_digest="unknown",
                mapping_schema_version="unsupported",
                mapping_document={},
                published_at=stored.document.published_at,
                published_by_principal="os-euid:999",
            )
        )
        db.commit()
    assert len(client.get("/api/catalog/products").json()["products"]) == 1
    monkeypatch.setattr(
        catalog_http,
        "settings",
        operator_settings(kernel_base_url="", kernel_service_token="", mapping_account_id="SIMULATED:empty-account"),
    )
    assert client.get("/api/catalog/products").json() == {"products": []}


async def test_distinct_offer_heads_for_same_product_are_ambiguous(
    client: TestClient, stored: StoredMapping, postgres_session_factory: sessionmaker[Session]
) -> None:
    # A second effective-date selection for the same component/period remains
    # the SAME offer; changing the component creates a distinct eligible head.
    recording = SelectedOfferRecording()
    recording.replace("services", '"tariff_service_id":1001', '"tariff_service_id":1002')
    selection = simulated_selection().model_copy(update={"tariff_service_id": 1002})
    inputs = simulated_inputs()
    assert inputs.policy is not None
    inputs = inputs.model_copy(update={"policy": inputs.policy.model_copy(update={"tariff_service_id": 1002})})

    # Reuse the recording's documented transport at the second selected path.
    class SecondServiceRecording(SelectedOfferRecording):
        def respond(self, request: httpx.Request) -> httpx.Response:
            if "/services/1002/prices" in request.url.path:
                request = httpx.Request(
                    "GET",
                    request.url.copy_with(path=request.url.path.replace("1002/prices", "1001/prices")),
                    headers=request.headers,
                )
            return super().respond(request)

    second = SecondServiceRecording()
    second.bodies = recording.bodies
    reviewed = await reviewed_fixture(recording=second, selection=selection, source_inputs=inputs)
    publish(postgres_session_factory, await fresh_fixture(reviewed, recording=second, source_inputs=inputs))
    response = client.get("/api/catalog/products/proposal_ai")
    assert response.status_code == 200
    assert response.json() == {
        "product_id": "proposal_ai",
        "evidence_mode": "SIMULATED",
        "availability": "UNAVAILABLE_AMBIGUOUS_OFFERS",
        "offer": None,
    }
    # Rebind only the second offer in a separately reviewed revision. Product
    # grouping/order must use the latest head, not its historical product ID.
    reviewed = await reviewed_fixture(
        recording=second, selection=selection, source_inputs=inputs, revision="SIMULATED:rebind-v2"
    )
    technical = reviewed.proposal.technical.model_copy(
        update={
            "product_id": "client_update_writer",
            "metric_key": "client_update_writer.test_generations",
        }
    )
    material = reviewed.approval.material.model_copy(update={"technical": technical})
    reviewed = replace(
        reviewed,
        proposal=reviewed.proposal.model_copy(update={"technical": technical}),
        approval=reviewed.approval.model_copy(
            update={
                "material": material,
                "approved_material_hash": commercial_digest(material.canonical_json()),
            }
        ),
    )
    manifest = manifest_fixture()
    next(product for product in manifest["products"] if product["product_id"] == "client_update_writer")["enabled"] = (
        True
    )
    manifest["usage_metrics"].append(
        {
            "product_id": technical.product_id,
            "metric_key": technical.metric_key,
            "unit": "generation",
            "enabled": True,
        }
    )
    publish(
        postgres_session_factory,
        await fresh_fixture(reviewed, recording=second, source_inputs=inputs, manifest=resign(manifest)),
        previous=1,
    )
    products = client.get("/api/catalog/products").json()["products"]
    assert [product["product_id"] for product in products] == ["client_update_writer", "proposal_ai"]
    assert all(product["availability"] == "SIMULATED_PREVIEW" for product in products)


async def test_no_source_initialization_or_admission_wait_on_browse(
    client: TestClient, stored: StoredMapping, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: object, **kwargs: object) -> NoReturn:
        raise AssertionError("catalog must not initialize or call sources")

    monkeypatch.setattr(PlatformKernelClient, "__init__", forbidden)
    monkeypatch.setattr(PlatformKernelClient, "fetch_manifest", forbidden)
    monkeypatch.setattr(LbxServerClient, "__init__", forbidden)
    monkeypatch.setattr(LbxServerClient, "get_tariff", forbidden)
    owner = PreflightAdmission(
        PreflightPolicy(total_timeout_seconds=2, cleanup_timeout_seconds=0.2, max_active=1, max_waiting=0)
    )
    client.app.state.sources = owner
    try:
        async with owner.operation():
            assert client.get("/api/catalog/products").status_code == 200
            assert client.get("/api/catalog/products/proposal_ai").status_code == 200
    finally:
        await owner.aclose()


async def test_database_failure_never_returns_fixture_terms(
    client: TestClient, stored: StoredMapping, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failed_db() -> Iterator[Session]:
        raise OperationalError("private query", {}, RuntimeError("private DB failure"))
        yield  # pragma: no cover

    client.app.dependency_overrides[get_db] = failed_db
    response = client.get("/api/catalog/products")
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_server_error"}}
    assert "private" not in response.text


def test_schema_requires_exact_strings_and_strict_positive_allowance() -> None:
    with pytest.raises(ValidationError):
        catalog_http.CatalogMoney(recurring_amount=0.1, connection_amount="0.00", currency="RUB", decimal_places=2)
    with pytest.raises(ValidationError):
        catalog_http.CatalogMoney(recurring_amount="0.001", connection_amount="0.00", currency="RUB", decimal_places=2)
    for invalid in (True, 0, -1, 1.5, "25"):
        with pytest.raises(ValidationError):
            catalog_http.CatalogAllowance(metric_key="SIMULATED.metric", unit="test", quantity=invalid)
    assert (
        catalog_http.CatalogAllowance(metric_key="SIMULATED.metric", unit="test", quantity=9007199254740993).model_dump(
            mode="json"
        )["quantity"]
        == "9007199254740993"
    )


async def test_money_larger_than_binary_float_precision_and_high_scale_is_not_rounded(stored: StoredMapping) -> None:
    # Presenter-only precision boundary; this modified object is never published
    # or used as evidence of commercial approval.
    money = replace(
        stored.document.material.terms.money,
        recurring_amount=Decimal("9007199254740993.123456789012345678"),
        connection_amount=Decimal("0.000000000000000001"),
        decimal_places=18,
    )
    material = stored.document.material.model_copy(
        update={
            "terms": replace(stored.document.material.terms, money=money),
        }
    )
    offer = catalog_http.present_offer(
        replace(stored, document=stored.document.model_copy(update={"material": material}))
    )
    assert offer.money.recurring_amount == "9007199254740993.123456789012345678"
    assert offer.money.connection_amount == "0.000000000000000001"


async def test_catalog_openapi_uses_named_schemas_and_string_money(client: TestClient) -> None:
    schemas = client.app.openapi()["components"]["schemas"]
    assert "CatalogProductsResponse" in schemas
    assert "CatalogProductResponse" in schemas
    assert schemas["CatalogMoney"]["properties"]["recurring_amount"]["type"] == "string"
    assert schemas["CatalogAllowance"]["properties"]["quantity"]["type"] == "string"


def test_manual_preview_setup_publishes_through_existing_publisher_and_serves_real_db(
    client: TestClient,
    migrated_database: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os

    from apps.api.tests.support.catalog_preview import publish_simulated_preview
    from apps.api.tests.support.lbx import ACCOUNT

    runtime = {
        "APP_ENV": "development",
        "POSTGRES_DB": "payments_12345678",
        "INSTANCE_TENANT_ID": "anytoolai",
        "INSTANCE_REGION": "ru",
        "MAPPING_ACCOUNT_ID": ACCOUNT,
    }
    configuration = operator_settings(app_env=AppEnv.DEVELOPMENT, mapping_operator_uids=(SIMULATED_UID,))
    monkeypatch.setattr(os, "geteuid", lambda: SIMULATED_UID, raising=False)
    # Only redirect the outer dev-tool DB capability to this test's real PG DB.
    # Both clients, normalization, approval evaluation and publication stay real.
    monkeypatch.setattr("scripts.repo.host_database_url_from_runtime", lambda _: migrated_database.url)
    first = publish_simulated_preview(runtime, operator=configuration, expected_previous_revision=0)
    second = publish_simulated_preview(runtime, operator=configuration, expected_previous_revision=0)
    assert second.stored.mapping_revision_id == first.stored.mapping_revision_id
    assert not second.inserted
    response = client.get("/api/catalog/products/proposal_ai")
    assert response.status_code == 200
    product = response.json()
    assert product["offer"]["revision_id"] == str(first.stored.mapping_revision_id)
    assert product["availability"] == "SIMULATED_PREVIEW"
    assert product["offer"]["money"]["recurring_amount"] == "200.02"
    assert product["offer"]["money"]["connection_amount"] == "14.06"
