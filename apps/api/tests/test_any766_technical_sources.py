"""Synthetic backend manifests reuse V1 validation and independent credentials."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import httpx
from pydantic import ValidationError
import pytest

from app.core.settings import Settings
from app.core.backend_consumers import BackendConsumer
from app.composition.catalog import catalog_preview
from app.composition.mapping_operator import fresh_link_evaluation
from app.composition.sources import TechnicalSourceRefused, source_resources
from app.domains.catalog.admission import SelectedCapabilityUnavailable
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.preview import CatalogProductNotFound
from app.domains.catalog.technical_offer import TechnicalOffer
from app.domains.catalog.technical_source import TechnicalOwnership
from app.domains.purchases.technical_terms import AcceptedTechnicalTerms, bind_published_terms
from apps.api.tests.support.any709_step1 import link_selection, recording, step1_settings
from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer
from apps.api.tests.support.kernel import manifest_fixture, resign

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def fixed_billing_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, tzinfo=UTC))


def source_settings(**overrides: object) -> Settings:
    return step1_settings(
        **dict(
            kernel_base_url="",
            kernel_service_token="",
            kernel_mock_enabled=False,
            backend_consumers=(backend_consumer(), second_consumer()),
        )
        | overrides
    )


def summary_manifest() -> dict[str, object]:
    manifest = manifest_fixture()
    manifest["products"] = [{"product_id": "synthetic_summary", "enabled": True}]
    manifest["usage_metrics"] = [
        {
            "product_id": "synthetic_summary",
            "metric_key": "synthetic_summary.results",
            "unit": "result",
            "enabled": True,
        }
    ]
    return resign(manifest)


def summary_offer(quantity: int = 13) -> TechnicalOffer:
    return TechnicalOffer(
        product_id="synthetic_summary",
        metric_key="synthetic_summary.results",
        unit="result",
        quantity=quantity,
        quantity_mode="fixed_per_cycle",
    )


async def test_each_source_uses_own_endpoint_and_key_and_filters_discovery() -> None:
    config = source_settings()
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        consumer = next(item for item in config.backend_consumers if request.url.host in item.backend_base_url)
        assert (
            request.headers["authorization"] == "Bearer " + consumer.portal_to_backend_current_secret.get_secret_value()
        )
        document = summary_manifest() if consumer.consumer_id == "synthetic-summary" else manifest_fixture()
        # An advertised foreign product does not extend this source's configured authority.
        document["products"].append({"product_id": "unowned_product", "enabled": True})
        return httpx.Response(200, json=resign(document))

    async with source_resources(config, kernel_transport=httpx.MockTransport(respond)) as sources:
        assert sources.kernel is None and not requests
        async with sources.preflight.operation() as budget:
            selected = sources.technical_source("synthetic_summary")
            manifest = await selected.client.fetch_manifest(budget=budget)
        assert manifest.provenance == "CONFIGURED_SOURCE"
        assert selected.ownership == TechnicalOwnership("synthetic-summary", "synthetic-summary")
        assert [r.url.host for r in requests] == ["summary.example.test"]
        with pytest.raises(TechnicalSourceRefused):
            sources.technical_source(
                "synthetic_summary", expected=TechnicalOwnership("platform-kernel", "platform-kernel")
            )
        with pytest.raises(TechnicalSourceRefused):
            sources.technical_source("unowned_product")
        products = await catalog_preview(
            sources, config, session_factory=lambda: pytest.fail("listing must be DB-free")
        )
        assert "synthetic_summary" in {item.product_id for item in products}
        assert "unowned_product" not in {item.product_id for item in products}


async def test_source_ids_cannot_select_ambiguous_owners() -> None:
    with pytest.raises(ValidationError, match="Each technical source"):
        source_settings(backend_consumers=(backend_consumer(), second_consumer(technical_source_id="platform-kernel")))


@pytest.mark.parametrize(
    "change", ["foreign_product", "foreign_metric", "unit", "disabled", "simulated", "simulated_registered"]
)
async def test_selected_source_product_metric_unit_and_provenance_are_required(change: str) -> None:
    config = source_settings()
    manifest = summary_manifest()
    if change == "foreign_product":
        selection = link_selection()  # Selects Kernel, never the summary manifest's owner.
    else:
        selection = link_selection(product_id="synthetic_summary")
    if change == "foreign_metric":
        manifest["products"].append({"product_id": "foreign", "enabled": True})
        manifest["usage_metrics"][0]["product_id"] = "foreign"
    elif change == "unit":
        manifest["usage_metrics"][0]["unit"] = "message"
    elif change == "disabled":
        manifest["usage_metrics"][0]["enabled"] = False
    elif change == "simulated_registered":
        config = source_settings(
            kernel_mock_enabled=True,
            backend_consumers=(backend_consumer(allowed_products=["synthetic_summary"]),),
        )
    elif change == "simulated":
        # Explicit legacy mock cannot publish configured quantities.
        config = step1_settings()
        selection = link_selection(product_id="synthetic_summary")
    with pytest.raises((SelectedCapabilityUnavailable, MappingRefused, CatalogProductNotFound)):
        await fresh_link_evaluation(
            config,
            selection=selection,
            technical_offer=summary_offer(),
            principal="os-euid:29001",
            kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=resign(manifest))),
            lbx_transport=httpx.MockTransport(recording().respond),
        )


async def test_new_versions_bind_owner_and_selected_meaning_without_global_audit_churn() -> None:
    evaluation = await fresh_link_evaluation(
        source_settings(),
        selection=link_selection(product_id="synthetic_summary"),
        technical_offer=summary_offer(),
        principal="os-euid:29001",
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=summary_manifest())),
        lbx_transport=httpx.MockTransport(recording().respond),
    )
    link = evaluation.document
    assert link.schema_version == "product-link-v4"
    assert "kernel_provenance" not in link.model_dump(mode="json")
    async with source_resources(
        source_settings(),
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=summary_manifest())),
    ) as sources:
        async with sources.preflight.operation() as budget:
            manifest = await sources.technical_source("synthetic_summary").client.fetch_manifest(budget=budget)
    terms = bind_published_terms(
        link, manifest, revision_id=uuid4(), commercial_fingerprint=evaluation.offer.fingerprint
    )
    encoded = terms.model_dump(mode="json")
    assert terms.schema_version == "purchased-technical-terms:v3"
    assert terms.ownership == link.ownership
    assert "kernel_manifest_version" not in encoded and "kernel_provenance" not in encoded
    later = bind_published_terms(
        link,
        replace(manifest, manifest_version="sha256:" + "2" * 64, generated_at=datetime.now(UTC)),
        revision_id=terms.revision_id,
        commercial_fingerprint=terms.commercial_fingerprint,
    )
    assert later.digest != terms.digest and later.confirmation_digest() == terms.confirmation_digest()
    for field, value in (("backend_consumer_id", "other"), ("technical_source_id", "other")):
        changed = terms.model_copy(update={field: value})
        assert changed.confirmation_digest() != terms.confirmation_digest()
        invalid = deepcopy(encoded)
        invalid[field] = value
        with pytest.raises(ValidationError):
            AcceptedTechnicalTerms.model_validate(invalid)
    for field in ("technical_source_id", "backend_consumer_id", "manifest_version", "manifest_provenance"):
        invalid = deepcopy(encoded)
        invalid.pop(field)
        with pytest.raises(ValidationError):
            AcceptedTechnicalTerms.model_validate(invalid)


@pytest.mark.parametrize(
    "consumer",
    [
        second_consumer(),
        backend_consumer(technical_source_id="other-source", allowed_products=["synthetic_summary"]),
    ],
)
async def test_unmetered_legacy_publication_cannot_erase_an_explicit_source_owner(consumer: BackendConsumer) -> None:
    config = source_settings(backend_consumers=(consumer,))
    with pytest.raises(MappingRefused, match="mapping_technical_offer_required"):
        await fresh_link_evaluation(
            config,
            selection=link_selection(product_id="synthetic_summary"),
            principal="os-euid:29001",
            kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=summary_manifest())),
            lbx_transport=httpx.MockTransport(recording().respond),
        )
