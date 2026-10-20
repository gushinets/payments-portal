from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, localcontext

import httpx
import pytest

from app.domains.catalog.commercial_offer import CommercialEvidenceMode, SelectedCommercialOffer
from app.integrations.lbx.selected_offer import read_selected_offer
from apps.api.tests.support.lbx import ACCOUNT, lbx_source
from apps.api.tests.support.lbx_selected_offer import (
    SelectedOfferRecording,
    simulated_inputs,
    simulated_selection,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def _read(recording: SelectedOfferRecording) -> SelectedCommercialOffer:
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            result = await read_selected_offer(
                client, selection=simulated_selection(), inputs=simulated_inputs(), budget=budget
            )
        assert owner.active_count == owner.waiting_count == 0
        return result


async def test_complete_simulated_offer_uses_real_auth_and_selected_reads() -> None:
    recording = SelectedOfferRecording()
    result = await _read(recording)
    assert result.evidence_mode == CommercialEvidenceMode.SIMULATED
    assert result.scope.external_billing_account_id == ACCOUNT
    assert result.references.effective_price == "1301"
    assert result.references.period_membership == "801"
    assert result.digest_scope == "selected_offer"
    assert json.loads(result.selected_evidence_json)["dependencies"]["default_components"] == ["1001"]
    assert any(item.field == "dependencies.default_components" for item in result.field_sources)
    assert result.terms.money.currency == "RUB"
    assert result.terms.money.decimal_places == 2
    assert result.terms.money.recurring_unit_amount == Decimal("100.01")
    assert result.terms.money.connection_unit_amount == Decimal("7.03")
    assert result.terms.money.recurring_amount == Decimal("200.02")
    assert result.terms.money.connection_amount == Decimal("14.06")
    assert result.terms.quantity.unit == "commercial_service"
    assert result.terms.quantity.selected == 2
    assert (result.terms.quantity.minimum, result.terms.quantity.maximum) == (1, 9)
    assert result.terms.period.unit == "month"
    assert result.terms.period.anchor == "instance_start"
    assert result.terms.period.price_effective_from == date(2026, 10, 1)
    assert result.terms.period.price_effective_until == date(2027, 1, 1)
    assert result.terms.policy.prepaid and result.terms.policy.insufficient_funds_block
    assert result.terms.policy.historical_applicability == "pinned_effective_terms"
    assert len(result.observations) == 8
    assert all(item.observed_at.utcoffset() is not None for item in result.observations)
    assert {item.basis for item in result.field_sources} == {"SIMULATED"}
    assert (
        result.selected_evidence_digest
        == "sha256:" + hashlib.sha256(result.selected_evidence_json.encode("utf-8")).hexdigest()
    )
    assert json.loads(result.terms.canonical_json())["money"]["recurring_amount"] == "200.02"
    assert recording.counts == {"tariff": 2, "periods": 2, "services": 2, "prices": 2}
    assert len(recording.requests) == 9  # One auth, no whole-account /tariffs GET.
    assert all(request.url.host == "lbx-client.test" and not request.url.query for request in recording.requests)


async def test_unrelated_records_editorial_text_and_observation_time_do_not_change_equality() -> None:
    baseline = await _read(SelectedOfferRecording())
    recording = SelectedOfferRecording()
    recording.replace("tariff", "SIMULATED selected fixed offer", "Unrelated editorial revision", reread_only=True)
    recording.append_row("periods", '{"tariff_period_id":802,"period_id":902}', reread_only=True)
    recording.append_row(
        "services", '{"tariff_id":701,"tariff_service_id":1002,"enabled_by_default":0}', reread_only=True
    )
    recording.append_row("prices", '{"price_id":1399,"period_id":902}', reread_only=True)
    result = await _read(recording)
    assert result.terms == baseline.terms
    assert result.selected_evidence_json == baseline.selected_evidence_json
    assert result.selected_evidence_digest == baseline.selected_evidence_digest
    assert result.observations != baseline.observations
    assert "observed_at" not in result.selected_evidence_json
    assert "effective_on" not in result.selected_evidence_json


async def test_other_effective_rows_and_equivalent_decimal_spellings_do_not_reprice_selected_terms() -> None:
    baseline = await _read(SelectedOfferRecording())
    recording = SelectedOfferRecording()
    recording.replace("prices", '"price":90', '"price":80')
    recording.replace("prices", '"price":110', '"price":999')
    for name in ("services", "prices"):
        recording.replace(name, '"price":100.01', '"price":100.0100')
    result = await _read(recording)
    assert result.terms == baseline.terms
    assert result.selected_evidence_digest == baseline.selected_evidence_digest


async def test_large_fractional_amounts_and_totals_are_exact_under_small_decimal_context() -> None:
    recording = SelectedOfferRecording()
    exact = "9007199254740993.123456789012345678901"
    for name in ("services", "prices"):
        recording.replace(name, '"price":100.01', '"price":' + exact)
        recording.replace(name, '"connection_price":7.03', '"connection_price":0.000000000000000000001')
    inputs = simulated_inputs()
    inputs = inputs.model_copy(update={"currency": inputs.currency.model_copy(update={"decimal_places": 21})})
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with localcontext() as context:
                context.prec = 6
                result = await read_selected_offer(
                    client, selection=simulated_selection(), inputs=inputs, budget=budget
                )
    assert result.terms.money.recurring_unit_amount == Decimal(exact)
    assert result.terms.money.recurring_amount == Decimal("18014398509481986.246913578024691357802")
    assert result.terms.money.connection_amount == Decimal("0.000000000000000000002")


async def test_same_numeric_currency_id_is_account_scoped_with_synthetic_eu_scale() -> None:
    ru = await _read(SelectedOfferRecording())
    recording = SelectedOfferRecording()
    for name in ("services", "prices"):
        recording.replace(name, '"price":100.01', '"price":10001')
        recording.replace(name, '"connection_price":7.03', '"connection_price":703')
    selection = simulated_selection().model_copy(
        update={
            "region": "eu",
            "external_billing_account_id": "simulated-eu-lbx-account",
        }
    )
    inputs = simulated_inputs()
    currency = inputs.currency.model_copy(
        update={
            "external_billing_account_id": selection.external_billing_account_id,
            "iso_currency": "EUR",
            "decimal_places": 3,
            "source_units": "minor",
            "evidence": inputs.currency.evidence.model_copy(update={"reference": "SIMULATED:synthetic-eu-currency"}),
        }
    )
    policy = inputs.policy.model_copy(
        update={
            "region": "eu",
            "external_billing_account_id": selection.external_billing_account_id,
            "evidence": inputs.policy.evidence.model_copy(update={"reference": "SIMULATED:synthetic-eu-policy"}),
        }
    )
    inputs = inputs.model_copy(update={"currency": currency, "policy": policy})
    # Application-level isolated composition only. No EU deployment or URL.
    async with lbx_source(
        httpx.MockTransport(recording.respond), lbx_external_billing_account_id=selection.external_billing_account_id
    ) as (client, owner):
        async with owner.operation() as budget:
            eu = await read_selected_offer(client, selection=selection, inputs=inputs, budget=budget)
    assert ru.terms.money.currency == "RUB" and eu.terms.money.currency == "EUR"
    assert eu.terms.money.decimal_places == 3
    assert eu.terms.money.recurring_unit_amount == Decimal("10.001")
    assert eu.terms.money.connection_amount == Decimal("1.406")
    assert eu.selected_evidence_digest != ru.selected_evidence_digest
    assert eu.evidence_mode == CommercialEvidenceMode.SIMULATED
    assert currency.currency_id == simulated_inputs().currency.currency_id == 77


async def test_new_current_price_does_not_rewrite_an_earlier_immutable_pin() -> None:
    pin = await _read(SelectedOfferRecording())
    pinned_document = pin.terms.canonical_json()
    recording = SelectedOfferRecording()
    for name in ("services", "prices"):
        recording.replace(name, '"price":100.01', '"price":120.01')
    current = await _read(recording)
    assert current.terms.money.recurring_amount == Decimal("240.02")
    assert current.selected_evidence_digest != pin.selected_evidence_digest
    assert pin.terms.canonical_json() == pinned_document
    assert pin.terms.money.recurring_amount == Decimal("200.02")


async def test_any_simulated_input_keeps_the_result_simulated_after_source_mode_switch() -> None:
    inputs = simulated_inputs().model_copy(update={"source_mode": CommercialEvidenceMode.CONFIGURED_SOURCE})
    recording = SelectedOfferRecording()
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            result = await read_selected_offer(client, selection=simulated_selection(), inputs=inputs, budget=budget)
    assert result.evidence_mode == CommercialEvidenceMode.SIMULATED


async def test_once_only_connection_fee_is_separate_and_changes_material_terms() -> None:
    inputs = simulated_inputs()
    inputs = inputs.model_copy(update={"policy": inputs.policy.model_copy(update={"connection_charge_basis": "once"})})
    recording = SelectedOfferRecording()
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            result = await read_selected_offer(client, selection=simulated_selection(), inputs=inputs, budget=budget)
    assert result.terms.money.connection_amount == Decimal("7.03")
    assert result.terms.money.recurring_amount == Decimal("200.02")
    assert result.terms != (await _read(SelectedOfferRecording())).terms
