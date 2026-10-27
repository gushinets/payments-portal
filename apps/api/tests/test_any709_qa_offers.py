"""Captured 043 selected offer plus explicit compatibility/discount regressions."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from app.composition.sources import source_resources
from app.domains.catalog.commercial_offer import SelectedOfferRefused, SelectedOfferSourceFailed
from app.domains.catalog.product_link import CurrentOffer
from app.integrations.lbx.current_offer import read_current_offer
from apps.api.tests.support.any709_step1 import link_selection, step1_settings
from apps.api.tests.support.lbx_selected_offer import SelectedOfferRecording

ROOT = Path(__file__).parent / "fixtures/lbx/qa043"
pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def captured() -> SelectedOfferRecording:
    source = SelectedOfferRecording(tariff_id=32, tariff_service_id=1)
    source.bodies = {name: (ROOT / f"043-{name}.json").read_bytes() for name in source.bodies}
    return source


async def quote(source: SelectedOfferRecording, monkeypatch: pytest.MonkeyPatch) -> CurrentOffer:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 26, tzinfo=UTC))
    config = step1_settings()  # Synthetic calendar, never a claim about 043's timezone.
    async with source_resources(config, lbx_transport=httpx.MockTransport(source.respond)) as sources:
        async with sources.preflight.operation() as budget:
            return await read_current_offer(
                sources.lbx,
                selection=link_selection(tariff_id=32, tariff_service_id=1, period_id=1),
                configuration=config,
                budget=budget,
            )


async def test_any709_qa_captured_offer_preserves_numbers_dates_and_record_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = captured()
    offer = await quote(source, monkeypatch)
    assert offer.money.recurring_amount == Decimal("100.000000")
    assert offer.price_id == 288
    assert offer.tariff_service_id == 1 and offer.period_id == 1 and offer.period_membership_id == 82
    assert source.counts == {name: 2 for name in source.bodies}
    assert b'"record_id": 101' in source.bodies["services"]


@pytest.mark.parametrize(
    "variant,reason",
    [
        ("legacy", None),
        ("both_empty", None),
        ("nonempty", "discounts_unsupported"),
        ("missing", "discounts_unknown"),
        ("null", "discounts_null"),
        ("wrong_type", "lbx_response_invalid"),
        ("contradiction", "discounts_conflict"),
        ("legacy_null", "discounts_null"),
        ("other_period", "discounts_unknown"),
        ("legacy_other_period", "discounts_selected_period_missing"),
        ("matching_nonempty", "discounts_unsupported"),
        ("legacy_nonempty", "discounts_unsupported"),
        ("legacy_missing", "discounts_unknown"),
        ("duplicate_period", "discounts_ambiguous"),
    ],
)
async def test_any709_qa_discount_representations(
    monkeypatch: pytest.MonkeyPatch, variant: str, reason: str | None
) -> None:
    source = captured()
    document = json.loads(source.bodies["services"])
    service = document["response"][0]
    inline = service["prices"][0]
    discount = {"discount_id": 1, "rate": 5}
    if variant == "legacy":
        inline.pop("discounts")
        service["discounts"] = []
    elif variant == "both_empty":
        service["discounts"] = [{"period_id": 1, "discounts": []}]
    elif variant in {"nonempty", "matching_nonempty"}:
        inline["discounts"] = [discount]
    elif variant in {"missing", "other_period", "legacy_other_period", "legacy_nonempty", "legacy_missing"}:
        inline.pop("discounts")
    elif variant == "null":
        inline["discounts"] = None
    elif variant == "wrong_type":
        inline["discounts"] = {}
    elif variant == "contradiction":
        service["discounts"] = [{"period_id": 1, "discounts": [discount]}]
    elif variant == "legacy_null":
        service["discounts"] = None
    elif variant == "duplicate_period":
        service["discounts"] = [{"period_id": 1, "discounts": []}] * 2
    if variant in {"other_period", "legacy_other_period"}:
        service["prices"].append({**inline, "period_id": 2, "discounts": []})
    if variant == "legacy_other_period":
        service["discounts"] = [{"period_id": 2, "discounts": []}]
    if variant in {"legacy_nonempty", "matching_nonempty"}:
        service["discounts"] = [{"period_id": 1, "discounts": [discount]}]
    if variant == "legacy_missing":
        service["discounts"] = [{"period_id": 1}]
    source.bodies["services"] = json.dumps(document).encode()
    if reason is None:
        assert (await quote(source, monkeypatch)).money.recurring_amount == 100
    else:
        with pytest.raises((SelectedOfferRefused, SelectedOfferSourceFailed), match=reason):
            await quote(source, monkeypatch)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("record_id", "101", "lbx_response_invalid"),
        ("tariff_service_id", 101, "component_membership_missing_or_ambiguous"),
        ("unknown_commercial_adjustment", 12, "lbx_response_invalid"),
    ],
)
async def test_any709_qa_service_metadata_does_not_replace_identity_or_drop_unknown_terms(
    monkeypatch: pytest.MonkeyPatch, field: str, value: object, reason: str
) -> None:
    source = captured()
    document = json.loads(source.bodies["services"])
    document["response"][0][field] = value
    source.bodies["services"] = json.dumps(document).encode()
    with pytest.raises((SelectedOfferRefused, SelectedOfferSourceFailed), match=reason):
        await quote(source, monkeypatch)
