"""Captured 043 selected offer plus explicit compatibility/discount regressions."""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
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


@pytest.fixture(autouse=True)
def fixed_offer_date(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 26, tzinfo=UTC))


def captured() -> SelectedOfferRecording:
    source = SelectedOfferRecording(tariff_id=32, tariff_service_id=1)
    source.bodies = {name: (ROOT / f"043-{name}.json").read_bytes() for name in source.bodies}
    return source


async def quote(source: SelectedOfferRecording) -> CurrentOffer:
    config = step1_settings()
    async with source_resources(config, lbx_transport=httpx.MockTransport(source.respond)) as sources:
        async with sources.preflight.operation() as budget:
            return await read_current_offer(
                sources.lbx,
                selection=link_selection(tariff_id=32, tariff_service_id=1, period_id=1),
                configuration=config,
                budget=budget,
            )


async def test_any709_qa_captured_offer_preserves_numbers_dates_and_record_identity() -> None:
    source = captured()
    offer = await quote(source)
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
async def test_any709_qa_discount_representations(variant: str, reason: str | None) -> None:
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
        assert (await quote(source)).money.recurring_amount == 100
    else:
        with pytest.raises((SelectedOfferRefused, SelectedOfferSourceFailed), match=reason):
            await quote(source)


@pytest.mark.parametrize(
    "field,value,reason",
    [
        ("record_id", "101", "lbx_response_invalid"),
        ("tariff_service_id", 101, "component_membership_missing_or_ambiguous"),
        ("unknown_commercial_adjustment", 12, "lbx_response_invalid"),
    ],
)
async def test_any709_qa_service_metadata_does_not_replace_identity_or_drop_unknown_terms(
    field: str, value: object, reason: str
) -> None:
    source = captured()
    document = json.loads(source.bodies["services"])
    document["response"][0][field] = value
    source.bodies["services"] = json.dumps(document).encode()
    with pytest.raises((SelectedOfferRefused, SelectedOfferSourceFailed), match=reason):
        await quote(source)


def scheduled_prices() -> SelectedOfferRecording:
    """043 wire fixtures with synthetic, deliberately unordered price histories."""
    source = captured()
    services = json.loads(source.bodies["services"])
    prices = json.loads(source.bodies["prices"])
    inline, dedicated = services["response"][0]["prices"][0], prices["response"][0]
    rows = [
        ("2026-11-01", 120, 289, 1),
        ("2026-09-01", 80, 287, 1),
        ("2026-10-01", 900, 301, 2),
        ("2026-10-01", 100, 288, 1),
    ]
    services["response"][0]["prices"] = [
        {**inline, "price_start_date": start + " 00:00:00", "price": amount, "period_id": period}
        for start, amount, _, period in rows
    ]
    prices["response"] = [
        {**dedicated, "start_date": start, "price": amount, "price_id": identity, "period_id": period}
        for start, amount, identity, period in rows
    ]
    source.bodies["services"] = json.dumps(services).encode()
    source.bodies["prices"] = json.dumps(prices).encode()
    return source


async def test_any709_qa_current_price_uses_latest_started_price_of_selected_period() -> None:
    source = scheduled_prices()
    offer = await quote(source)
    assert offer.money.recurring_amount == Decimal("100") and offer.price_id == 288
    assert offer.period_id == 1 and offer.period_membership_id == 82
    assert offer.period.price_effective_from == date(2026, 10, 1)
    assert offer.period.price_effective_until == date(2026, 11, 1)
    assert source.counts == {name: 2 for name in source.bodies}


@pytest.mark.parametrize("name,date_field", [("services", "price_start_date"), ("prices", "start_date")])
@pytest.mark.parametrize("change", ["all_future", "other_period_only", "empty", "unknown_start", "null_start"])
async def test_any709_qa_current_price_requires_applicable_dated_record(
    name: str, date_field: str, change: str
) -> None:
    source = captured()
    document = json.loads(source.bodies[name])
    rows = document["response"][0]["prices"] if name == "services" else document["response"]
    reason = "applicable_price_missing"
    if change == "all_future":
        rows[0][date_field] = "2026-11-01 00:00:00" if name == "services" else "2026-11-01"
    elif change == "other_period_only":
        rows[0]["period_id"] = 2
    elif change == "empty":
        rows.clear()
    elif change == "unknown_start":
        rows[0].pop(date_field)
        reason = "price_start_unknown"
    else:
        rows[0][date_field] = None
        reason = "price_start_unknown"
    source.bodies[name] = json.dumps(document).encode()
    with pytest.raises(SelectedOfferRefused, match=reason):
        await quote(source)


@pytest.mark.parametrize("name", ["services", "prices"])
@pytest.mark.parametrize("start", ["2026-09-01", "2026-10-01", "2026-11-01"])
async def test_any709_qa_current_price_checks_ambiguity_only_at_effective_start(name: str, start: str) -> None:
    source = scheduled_prices()
    document = json.loads(source.bodies[name])
    rows = document["response"][0]["prices"] if name == "services" else document["response"]
    field = "price_start_date" if name == "services" else "start_date"
    original = next(row for row in rows if row["period_id"] == 1 and row[field].startswith(start))
    competing = {**original, "price": 500}
    if name == "prices":
        competing["price_id"] = 999
    rows.append(competing)
    source.bodies[name] = json.dumps(document).encode()
    if start == "2026-10-01":
        with pytest.raises(SelectedOfferRefused, match="price_applicability_ambiguous"):
            await quote(source)
    else:
        offer = await quote(source)
        assert offer.money.recurring_amount == 100 and offer.price_id == 288
        assert offer.period.price_effective_until == date(2026, 11, 1)


@pytest.mark.parametrize("name", ["services", "prices"])
@pytest.mark.parametrize("field", ["price", "connection_price", "bulk_price", "bulk_include_amount", "date"])
async def test_any709_qa_current_price_checks_selected_record_against_both_methods(name: str, field: str) -> None:
    source = scheduled_prices()
    document = json.loads(source.bodies[name])
    rows = document["response"][0]["prices"] if name == "services" else document["response"]
    date_field = "price_start_date" if name == "services" else "start_date"
    row = next(row for row in rows if row["period_id"] == 1 and row[date_field].startswith("2026-10-01"))
    if field == "date":
        row[date_field] = "2026-10-02 00:00:00" if name == "services" else "2026-10-02"
    else:
        row[field] = 500
    source.bodies[name] = json.dumps(document).encode()
    reason = "inline_effective_date_conflict" if field == "date" else "inline_effective_price_conflict"
    with pytest.raises(SelectedOfferRefused, match=reason):
        await quote(source)


@pytest.mark.parametrize("variant", ["nonempty", "missing", "null"])
@pytest.mark.parametrize("selected", [True, False])
async def test_any709_qa_discounts_belong_only_to_selected_current_price(variant: str, selected: bool) -> None:
    source = scheduled_prices()
    document = json.loads(source.bodies["services"])
    for row in document["response"][0]["prices"]:
        current = row["period_id"] == 1 and row["price_start_date"].startswith("2026-10-01")
        if current != selected:
            continue
        if variant == "nonempty":
            row["discounts"] = [{"discount_id": 1, "rate": 5}]
        elif variant == "missing":
            row.pop("discounts")
        else:
            row["discounts"] = None
    source.bodies["services"] = json.dumps(document).encode()
    if selected:
        reason = {"nonempty": "discounts_unsupported", "missing": "discounts_unknown", "null": "discounts_null"}[
            variant
        ]
        with pytest.raises(SelectedOfferRefused, match=reason):
            await quote(source)
    else:
        assert (await quote(source)).money.recurring_amount == 100


@pytest.mark.parametrize(
    "instant,amount,price_id,start,until",
    [
        (datetime(2026, 10, 31, 20, 59, 59, tzinfo=UTC), 100, 288, date(2026, 10, 1), date(2026, 11, 1)),
        (datetime(2026, 10, 31, 21, 0, 0, tzinfo=UTC), 120, 289, date(2026, 11, 1), None),
    ],
)
async def test_any709_qa_price_starts_inclusively_at_moscow_midnight(
    monkeypatch: pytest.MonkeyPatch, instant: datetime, amount: int, price_id: int, start: date, until: date | None
) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: instant)
    offer = await quote(scheduled_prices())
    assert offer.money.recurring_amount == amount and offer.price_id == price_id
    assert offer.period.price_effective_from == start and offer.period.price_effective_until == until
    assert type(offer.period.price_effective_from) is date


@pytest.mark.parametrize("changed", [None, "price", "price_id"])
async def test_any709_qa_rereads_share_one_moscow_date_and_still_refuse_source_changes(
    monkeypatch: pytest.MonkeyPatch, changed: str | None
) -> None:
    source = scheduled_prices()
    instant = datetime(2026, 10, 31, 20, 59, 59, tzinfo=UTC)
    clock_calls = 0

    def clock() -> datetime:
        nonlocal clock_calls
        clock_calls += 1
        return instant

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal instant
        response = source.respond(request)
        if source.counts.get("prices") == 1:
            instant = datetime(2026, 10, 31, 21, tzinfo=UTC)
        return response

    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", clock)
    if changed == "price":
        for name in ("services", "prices"):
            source.replace(name, '"price": 100', '"price": 110', reread_only=True)
    elif changed == "price_id":
        source.replace("prices", '"price_id": 288', '"price_id": 999', reread_only=True)
    config = step1_settings()
    async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
        async with sources.preflight.operation() as budget:
            kwargs = {
                "selection": link_selection(tariff_id=32, tariff_service_id=1, period_id=1),
                "configuration": config,
                "budget": budget,
            }
            if changed is not None:
                with pytest.raises(SelectedOfferSourceFailed, match="selected_source_changed"):
                    await read_current_offer(sources.lbx, **kwargs)
            else:
                offer = await read_current_offer(sources.lbx, **kwargs)
                assert offer.money.recurring_amount == 100 and offer.price_id == 288
    assert clock_calls == 1
    assert source.counts == {name: 2 for name in source.bodies}


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="Host does not support changing process timezone")
@pytest.mark.parametrize("host_timezone", ["UTC", "America/Los_Angeles", "Asia/Tokyo"])
async def test_any709_qa_price_is_independent_of_host_timezone(
    monkeypatch: pytest.MonkeyPatch, host_timezone: str
) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 31, 21, tzinfo=UTC))
    try:
        with monkeypatch.context() as context:
            context.setenv("TZ", host_timezone)
            time.tzset()
            offer = await quote(scheduled_prices())
            assert offer.money.recurring_amount == 120 and offer.price_id == 289
    finally:
        time.tzset()


@pytest.mark.parametrize("obsolete_value", [None, "Etc/UTC", "Unknown/Invalid"])
async def test_any709_qa_current_offer_needs_no_timezone_configuration(
    monkeypatch: pytest.MonkeyPatch, obsolete_value: str | None
) -> None:
    if obsolete_value is None:
        monkeypatch.delenv("LBX_BILLING_TIMEZONE", raising=False)
    else:
        monkeypatch.setenv("LBX_BILLING_TIMEZONE", obsolete_value)
    assert "lbx_billing_timezone" not in type(step1_settings()).model_fields
    assert (await quote(captured())).money.recurring_amount == 100
