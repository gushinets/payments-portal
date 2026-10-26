"""Explicit local HTTP fixtures; never a runtime billing mode or live network."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.core.settings import Settings
from app.domains.catalog.commercial_offer import (
    CommercialEvidenceMode,
    CommercialScope,
    canonical_document,
    commercial_digest,
)
from app.domains.catalog.contracts import SourceProvenance
from app.domains.catalog.product_link import LINK_SCHEMA, ProductLinkDocument, ProductLinkRequest
from apps.api.tests.support.kernel import TOKEN
from apps.api.tests.support.lbx import lbx_settings
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording


def step1_settings(**overrides: Any) -> Settings:
    return lbx_settings(
        **{
            "kernel_base_url": "http://kernel-client.test",
            "kernel_service_token": TOKEN,
            "kernel_max_retries": 0,
            "kernel_mock_enabled": True,
            "lbx_widget_signing_secret": "isolated-test-widget-secret",
            "lbx_seller_organization_id": "21",
            "lbx_billing_timezone": "Etc/UTC",
            "lbx_currency_id": "1",
            "lbx_currency": "RUB",
            **overrides,
        }
    )


def link_selection(**overrides: Any) -> ProductLinkRequest:
    return ProductLinkRequest(
        **{"product_id": "proposal_ai", "tariff_id": 701, "tariff_service_id": 1001, "period_id": 901, **overrides}
    )


def recording() -> SelectedOfferRecording:
    result = SelectedOfferRecording()
    result.replace("tariff", '"currency_id":77', '"currency_id":1')
    return result


def readiness_recording() -> SelectedOfferRecording:
    """Retained E04/E05 wire bodies, with explicitly synthetic tariff/period support.

    Source: ANY709-LBX043-readonly-readiness.md, 2026-10-25. The two bodies
    were extracted from its sanitized logs without re-encoding JSON numbers.
    This combined test recording is not a captured complete stand snapshot.
    """
    result = SelectedOfferRecording(tariff_id=32, tariff_service_id=1)
    result.bodies["tariff"] = recording().bodies["tariff"].replace(b'"tariff_id":701', b'"tariff_id":32')
    result.bodies["periods"] = (
        result.bodies["periods"]
        .replace(b'"period_id":901', b'"period_id":1')
        .replace(b'"tariff_period_id":801', b'"tariff_period_id":82')
    )
    fixture_root = Path(__file__).resolve().parents[1] / "fixtures/lbx/readiness"
    result.bodies["services"] = (fixture_root / "e04-services.json").read_bytes()
    result.bodies["prices"] = (fixture_root / "e05-prices.json").read_bytes()
    return result


def link_document(**overrides: Any) -> ProductLinkDocument:
    selection = overrides.pop("selection", link_selection())
    config = step1_settings()
    scope = overrides.pop(
        "scope",
        CommercialScope(config.instance_tenant_id, config.instance_region, config.lbx_external_billing_account_id),
    )
    now = datetime(2026, 10, 26, tzinfo=UTC)
    identity = canonical_document(
        {
            "schema": LINK_SCHEMA,
            "scope": asdict(scope),
            "selection": selection.model_dump(mode="json"),
            "kernel_provenance": SourceProvenance.SIMULATED,
            "lbx_evidence_mode": CommercialEvidenceMode.CONFIGURED_SOURCE,
        }
    )
    return ProductLinkDocument(
        **{
            "scope": scope,
            "selection": selection,
            "kernel_provenance": SourceProvenance.SIMULATED,
            "lbx_evidence_mode": CommercialEvidenceMode.CONFIGURED_SOURCE,
            "manifest_version": "sha256:" + "1" * 64,
            "manifest_generated_at": now,
            "evaluated_at": now,
            "published_at": now,
            "publisher_principal": "os-euid:29001",
            "reason": "Isolated product link fixture",
            "identity_digest": commercial_digest(identity),
            **overrides,
        }
    )
