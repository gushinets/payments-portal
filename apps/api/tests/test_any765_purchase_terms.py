"""Step 1 contracts, exact quantities and historical evidence; no paid projection."""

from dataclasses import replace

import pytest
from pydantic import ValidationError

from app.composition import purchase_terms
from app.domains.catalog.admission import SelectedCapabilityUnavailable
from app.domains.catalog.contracts import CapabilityProduct
from app.domains.purchases.contracts import AcceptedPurchase, PurchaseRefused
from app.domains.purchases.technical_terms import TechnicalOffer, bind_test_terms
from apps.api.tests.factories.purchase_terms import test_terms_source as terms_source, technical_manifest
from apps.api.tests.factories.reconciliation import subject_factory
from apps.api.tests.support.any709_step1 import link_selection, step1_settings


@pytest.mark.parametrize(
    "product,metric,unit,quantity",
    [
        ("proposal_ai", "proposal_ai.test_generations", "generation", 100),
        ("brief_decoder", "brief_decoder.test_analyses", "analysis", 300),
    ],
)
def test_exact_terms_bind_link_component_offer_and_live_capability(
    product: str,
    metric: str,
    unit: str,
    quantity: int,
) -> None:
    subject = subject_factory()
    terms = bind_test_terms(
        terms_source(),
        technical_manifest(),
        account_id=subject.purchase.account_id,
        revision_id=subject.purchase.accepted.meaning.revision_id,
        selection=link_selection(product_id=product),
        commercial_fingerprint=subject.purchase.accepted.offer.fingerprint,
    )
    assert (terms.offer.metric_key, terms.offer.unit, terms.offer.quantity) == (metric, unit, quantity)
    assert terms.provenance == "SIMULATED"
    assert terms.source_version == "ANY-765-test-terms:1"
    changed = terms.model_dump(mode="json")
    changed["offer"]["quantity"] += 1
    with pytest.raises(ValidationError, match="identity"):
        type(terms).model_validate(changed)


@pytest.mark.parametrize("fault", ["owner", "unit", "disabled", "missing", "product"])
def test_terms_require_current_kernel_metric_ownership_unit_and_availability(fault: str) -> None:
    manifest = technical_manifest()
    metric = manifest.usage_metrics[0]
    if fault == "owner":
        metric = replace(metric, product_id="brief_decoder")
    elif fault == "unit":
        metric = replace(metric, unit="analysis")
    elif fault == "disabled":
        metric = replace(metric, enabled=False)
    manifest = replace(manifest, usage_metrics=() if fault == "missing" else (metric,))
    if fault == "product":
        manifest = replace(manifest, products=(CapabilityProduct("proposal_ai", False),))
    original = subject_factory().purchase.accepted
    with pytest.raises(SelectedCapabilityUnavailable):
        bind_test_terms(
            terms_source(),
            manifest,
            account_id="test",
            revision_id=original.meaning.revision_id,
            selection=original.selection,
            commercial_fingerprint=original.offer.fingerprint,
        )


@pytest.mark.parametrize("quantity", [0.5, 100.0, True, False, -1, 2**53, "100"])
def test_quantity_rejects_lossy_noninteger_or_out_of_range_values(quantity: object) -> None:
    data = terms_source().offers[0].model_dump()
    data["quantity"] = quantity
    with pytest.raises(ValidationError):
        TechnicalOffer.model_validate(data)


def test_strict_integer_zero_is_valid_without_inventing_unlimited() -> None:
    data = terms_source().offers[0].model_dump()
    data["quantity"] = 0
    assert TechnicalOffer.model_validate(data).quantity == 0


def test_legacy_snapshot_stays_unmetered_without_loading_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    old = subject_factory().purchase.accepted.model_dump(mode="json", exclude={"technical_terms"})
    old["meaning"].pop("expected_technical_terms_digest")
    monkeypatch.setattr(purchase_terms, "TEST_TERMS_PATH", None)
    parsed = AcceptedPurchase.model_validate(old)
    assert parsed.schema_version == "accepted-purchase:v1" and parsed.technical_terms is None


def test_source_default_disabled_and_production_enablement_refused() -> None:
    assert not step1_settings().purchase_test_terms_enabled
    with pytest.raises(ValidationError, match="Purchase test terms require development/test"):
        step1_settings(
            app_env="production",
            app_public_base_url="https://portal.example.test",
            cors_allow_origins=("https://portal.example.test",),
            kernel_mock_enabled=False,
            kernel_base_url="https://kernel.example.test",
            purchase_test_terms_enabled=True,
        )


def test_enabled_source_missing_file_refuses_without_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    from pathlib import Path
    from app.domains.catalog.link_publication import StoredProductLink
    from apps.api.tests.support.any709_step1 import link_document
    from uuid import uuid4

    monkeypatch.setattr(purchase_terms, "TEST_TERMS_PATH", Path("/nonexistent/ANY-765-terms.json"))
    original = subject_factory().purchase.accepted
    link = StoredProductLink(uuid4(), 1, 1, link_document())
    with pytest.raises(PurchaseRefused, match="purchase_technical_terms_unavailable"):
        purchase_terms.current_technical_terms(
            step1_settings(purchase_test_terms_enabled=True), technical_manifest(), link, original.offer
        )
