from __future__ import annotations

import asyncio
from datetime import date
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from app.domains.catalog.commercial_offer import CommercialEvidenceBasis, OfferRefusalKind, SelectedOfferRefused
from app.infrastructure.preflight import PreflightDeadlineExceeded
from app.integrations.lbx.offer_inputs import SelectedOfferRequest
from app.integrations.lbx.selected_offer import read_selected_offer
from apps.api.tests.support.lbx import lbx_source
from apps.api.tests.support.lbx_selected_offer import (
    SelectedOfferRecording,
    simulated_inputs,
    simulated_selection,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    ("name", "old", "new", "reason"),
    [
        ("tariff", '"currency_id":77,', "", "offer_currency_id_unknown"),
        ("tariff", '"currency_id":77', '"currency_id":78', "currency_identity_mismatch"),
        ("tariff", '"balance_blocks":1,', "", "offer_balance_blocks_unknown"),
        ("tariff", '"payment_type":0', '"payment_type":99', "source_flag_meaning_unknown"),
        ("tariff", '"demo_period_length":0,', "", "offer_demo_period_length_unknown"),
        ("periods", '"period_id":901', '"period_id":999', "period_membership_missing_or_ambiguous"),
        (
            "services",
            '"tariff_service_id":1001',
            '"tariff_service_id":1002',
            "component_membership_missing_or_ambiguous",
        ),
        ("services", '"discounts":[]', '"discounts":null', "discounts_unknown"),
        ("services", '"min_multiplicator":1', '"min_multiplicator":10', "commercial_bounds_invalid"),
        ("services", '"price":100.01', '"price":101.01', "inline_effective_price_conflict"),
        ("prices", '"connection_price":7.03,', "", "effective_connection_price_unknown"),
        ("prices", '"period_id":901', '"period_id":902', "applicable_price_missing"),
        ("prices", '"start_date":"2026-10-01",', "", "price_start_unknown"),
        ("prices", '"start_date":"2027-01-01"', '"start_date":"2026-10-01"', "price_applicability_ambiguous"),
        (
            "prices",
            '"next_change_date":"2027-01-01"',
            '"next_change_date":"2026-12-01"',
            "price_schedule_gap_or_overlap",
        ),
        (
            "prices",
            '"next_change_date":"2027-01-01"',
            '"next_change_date":"2027-02-01"',
            "price_schedule_gap_or_overlap",
        ),
        ("prices", '"price":100.01', '"price":"100.01"', "lbx_response_invalid"),
        ("prices", '"price":100.01', '"price":NaN', "lbx_response_invalid"),
        ("prices", '"price":100.01', '"price":1e9999', "numeric_representation_unsupported"),
    ],
)
async def test_missing_ambiguous_contradictory_or_inexact_source_is_incomplete(
    name: str, old: str, new: str, reason: str
) -> None:
    recording = SelectedOfferRecording()
    recording.replace(name, old, new)
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(
                    client, selection=simulated_selection(), inputs=simulated_inputs(), budget=budget
                )
        assert owner.active_count == 0
    assert caught.value.kind == OfferRefusalKind.INCOMPLETE
    assert caught.value.reason == reason


@pytest.mark.parametrize(
    ("field", "reason"),
    [
        ("account_binding", "account_binding_unproven"),
        ("list_completeness", "list_completeness_unproven"),
        ("historical_policy", "historical_policy_unproven"),
        ("price_applicability", "price_applicability_unproven"),
        ("tax_treatment", "policy_tax_treatment_unknown"),
        ("account_discounts", "policy_account_discounts_unknown"),
        ("proration", "policy_proration_unknown"),
        ("credit_disabled", "policy_credit_disabled_unknown"),
        ("renewal_terms", "policy_renewal_terms_unknown"),
        ("historical_applicability", "policy_historical_applicability_unknown"),
    ],
)
async def test_missing_configuration_never_becomes_zero_disabled_or_proven(field: str, reason: str) -> None:
    inputs = simulated_inputs()
    inputs = inputs.model_copy(update={"policy": inputs.policy.model_copy(update={field: None})})
    recording = SelectedOfferRecording()
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(client, selection=simulated_selection(), inputs=inputs, budget=budget)
    assert caught.value.kind == OfferRefusalKind.INCOMPLETE
    assert caught.value.reason == reason


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("iso_currency", None, "currency_iso_unknown"),
        ("source_units", None, "money_units_unknown"),
        ("decimal_places", None, "money_scale_unknown"),
        ("decimal_places", -1, "money_scale_invalid"),
        ("decimal_places", 37, "money_scale_invalid"),
        ("decimal_places", 1, "money_scale_mismatch"),
        ("source_units", "minor", "money_scale_mismatch"),
        ("external_billing_account_id", "another-account", "currency_account_mismatch"),
    ],
)
async def test_currency_units_scale_and_account_are_never_guessed(
    field: str, value: str | int | None, reason: str
) -> None:
    inputs = simulated_inputs()
    inputs = inputs.model_copy(update={"currency": inputs.currency.model_copy(update={field: value})})
    recording = SelectedOfferRecording()
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(client, selection=simulated_selection(), inputs=inputs, budget=budget)
    assert caught.value.kind == OfferRefusalKind.INCOMPLETE
    assert caught.value.reason == reason


async def test_documentation_is_not_account_specific_currency_proof() -> None:
    inputs = simulated_inputs()
    evidence = inputs.currency.evidence.model_copy(update={"basis": CommercialEvidenceBasis.DOCUMENTED})
    inputs = inputs.model_copy(update={"currency": inputs.currency.model_copy(update={"evidence": evidence})})
    recording = SelectedOfferRecording()
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused, match="account_evidence_required"):
                await read_selected_offer(client, selection=simulated_selection(), inputs=inputs, budget=budget)


@pytest.mark.parametrize(
    ("name", "old", "new", "reason"),
    [
        ("tariff", '"payment_type":0', '"payment_type":1', "prepaid_blocking_required"),
        ("tariff", '"balance_blocks":1', '"balance_blocks":0', "prepaid_blocking_required"),
        ("tariff", '"dynamic_rent":0', '"dynamic_rent":1', "fixed_full_funding_required"),
        ("tariff", '"demo_period_length":0', '"demo_period_length":3', "demo_unsupported"),
        ("tariff", '"proportional_rent":0', '"proportional_rent":1', "proration_unsupported"),
        ("services", '"bulk_service":false', '"bulk_service":true', "fixed_periodic_profile_required"),
        ("services", '"user_available":0', '"user_available":1', "customer_management_unsupported"),
        ("services", '"user_can_set_mul":0', '"user_can_set_mul":1', "customer_management_unsupported"),
        (
            "services",
            '"discounts":[]',
            '"discounts":[{"discount_id":1401,"count":1,"new_price":90,"new_bulk_price":0,"rate":0.9}]',
            "discounts_unsupported",
        ),
    ],
)
async def test_only_fully_known_unsupported_profiles_are_not_sellable(
    name: str, old: str, new: str, reason: str
) -> None:
    recording = SelectedOfferRecording()
    recording.replace(name, old, new)
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(
                    client, selection=simulated_selection(), inputs=simulated_inputs(), budget=budget
                )
    assert caught.value.kind == OfferRefusalKind.NOT_SELLABLE
    assert caught.value.reason == reason


async def test_known_unsupported_flag_does_not_hide_missing_mandatory_evidence() -> None:
    recording = SelectedOfferRecording()
    recording.replace("tariff", '"payment_type":0', '"payment_type":1')
    inputs = simulated_inputs().model_copy(update={"currency": None})
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(client, selection=simulated_selection(), inputs=inputs, budget=budget)
    assert caught.value.kind == OfferRefusalKind.INCOMPLETE


async def test_changed_selected_material_on_bounded_reread_is_incomplete() -> None:
    recording = SelectedOfferRecording()
    for name in ("services", "prices"):
        recording.replace(name, '"price":100.01', '"price":120.01', reread_only=True)
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(
                    client, selection=simulated_selection(), inputs=simulated_inputs(), budget=budget
                )
    assert caught.value.kind == OfferRefusalKind.INCOMPLETE
    assert caught.value.reason == "selected_source_changed"
    assert recording.counts["prices"] == 2


async def test_partial_lists_and_wrong_account_do_not_pass() -> None:
    recording = SelectedOfferRecording()
    inputs = simulated_inputs()
    partial = inputs.model_copy(update={"policy": inputs.policy.model_copy(update={"complete_selected_lists": False})})
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused, match="partial_selected_lists"):
                await read_selected_offer(client, selection=simulated_selection(), inputs=partial, budget=budget)
    async with lbx_source(httpx.MockTransport(recording.respond), lbx_external_billing_account_id="wrong-account") as (
        client,
        owner,
    ):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused, match="source_account_mismatch"):
                await read_selected_offer(client, selection=simulated_selection(), inputs=inputs, budget=budget)


async def test_two_membership_rows_for_the_same_selected_period_are_ambiguous() -> None:
    recording = SelectedOfferRecording()
    recording.append_row("periods", '{"tariff_period_id":802,"period_id":901}')
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(
                    client, selection=simulated_selection(), inputs=simulated_inputs(), budget=budget
                )
    assert caught.value.kind == OfferRefusalKind.INCOMPLETE
    assert caught.value.reason == "period_membership_missing_or_ambiguous"


@pytest.mark.parametrize(
    ("field", "value", "kind", "reason"),
    [
        ("tax_treatment", "unknown", OfferRefusalKind.INCOMPLETE, "policy_tax_treatment_unknown"),
        ("tax_treatment", "additional", OfferRefusalKind.NOT_SELLABLE, "tax_profile_unsupported"),
        ("account_discounts", "present", OfferRefusalKind.NOT_SELLABLE, "discounts_unsupported"),
        ("proration", "proportional", OfferRefusalKind.NOT_SELLABLE, "proration_unsupported"),
        (
            "historical_applicability",
            "mutable_current",
            OfferRefusalKind.NOT_SELLABLE,
            "historical_profile_unsupported",
        ),
        ("manual_activation_disabled", False, OfferRefusalKind.NOT_SELLABLE, "activation_profile_unsupported"),
        ("valid_until", date(2026, 10, 16), OfferRefusalKind.INCOMPLETE, "policy_not_applicable"),
    ],
)
async def test_explicit_policy_meaning_and_historical_applicability(
    field: str, value: str | bool | date, kind: OfferRefusalKind, reason: str
) -> None:
    inputs = simulated_inputs()
    inputs = inputs.model_copy(update={"policy": inputs.policy.model_copy(update={field: value})})
    recording = SelectedOfferRecording()
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(client, selection=simulated_selection(), inputs=inputs, budget=budget)
    assert caught.value.kind == kind
    assert caught.value.reason == reason


@pytest.mark.parametrize("quantity", [Decimal("0"), Decimal("-1"), Decimal("10")])
async def test_commercial_quantity_must_be_positive_and_within_provider_bounds(quantity: Decimal) -> None:
    selection = simulated_selection().model_copy(update={"commercial_quantity": quantity})
    recording = SelectedOfferRecording()
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(client, selection=selection, inputs=simulated_inputs(), budget=budget)
    assert caught.value.kind == OfferRefusalKind.NOT_SELLABLE
    assert caught.value.reason == "commercial_quantity_out_of_bounds"


async def test_fractional_commercial_quantity_never_rounds_money_or_creates_a_technical_allowance() -> None:
    selection = simulated_selection().model_copy(update={"commercial_quantity": Decimal("1.5")})
    recording = SelectedOfferRecording()
    async with lbx_source(httpx.MockTransport(recording.respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(client, selection=selection, inputs=simulated_inputs(), budget=budget)
    assert caught.value.kind == OfferRefusalKind.INCOMPLETE
    assert caught.value.reason == "money_scale_mismatch"


async def test_reread_failure_has_no_first_read_fallback_and_exposes_no_payload() -> None:
    recording = SelectedOfferRecording()

    def respond(request: httpx.Request) -> httpx.Response:
        response = recording.respond(request)
        if recording.counts.get("prices", 0) >= 2:
            return httpx.Response(503, text="private-provider-body")
        return response

    async with lbx_source(httpx.MockTransport(respond), lbx_max_get_attempts=2) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(SelectedOfferRefused) as caught:
                await read_selected_offer(
                    client, selection=simulated_selection(), inputs=simulated_inputs(), budget=budget
                )
    assert caught.value.kind == OfferRefusalKind.INCOMPLETE
    assert caught.value.reason == "lbx_unavailable"
    assert "private-provider-body" not in str(caught.value)


async def test_slow_reads_share_one_overall_deadline_including_reread() -> None:
    recording = SelectedOfferRecording()

    async def respond(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.03)
        return recording.respond(request)

    async with lbx_source(
        httpx.MockTransport(respond),
        preflight_total_timeout_seconds=0.18,
        preflight_cleanup_timeout_seconds=0.02,
    ) as (client, owner):
        # Admission can translate deadline cancellation on context exit, so
        # the assertion must cover the complete operation lifetime.
        with pytest.raises(PreflightDeadlineExceeded):
            async with owner.operation() as budget:
                await read_selected_offer(
                    client, selection=simulated_selection(), inputs=simulated_inputs(), budget=budget
                )
        assert owner.active_count == 0
    assert len(recording.requests) < 9


@pytest.mark.parametrize("quantity", [1.5, float("nan"), "NaN", "Infinity", "broken"])
async def test_configuration_rejects_float_or_nonfinite_quantity(quantity: float | str) -> None:
    value = simulated_selection().model_dump()
    value["commercial_quantity"] = quantity
    with pytest.raises(ValidationError):
        SelectedOfferRequest.model_validate(value)
