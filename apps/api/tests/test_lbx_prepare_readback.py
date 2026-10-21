from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import replace
from decimal import Decimal, localcontext
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.core.settings import AppEnv
from app.integrations.lbx.client import API_PATH, LbxServerClient
from app.integrations.lbx.errors import (
    LbxAuthenticationFailed,
    LbxCreateUncertain,
    LbxPreparationBlocked,
    LbxResponseInvalid,
    LbxScopeMismatch,
)
from app.integrations.lbx.preparation import LbxPreparation, ProofState
from app.integrations.lbx.preparation_dto import NewServiceInfo, PostUser
from apps.api.tests.support.lbx import TOKEN, lbx_settings
from apps.api.tests.support.lbx_preparation import (
    AGREEMENT_ID,
    CUSTOMER_KEY,
    DIRECTORY,
    SUBSCRIPTION_ID,
    USER_ID,
    PreparationRecording,
    agreement_command,
    preparation_profile,
    preparation_source,
    selected_offer,
    subscription_command,
    user_command,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("status", [200, 201])
async def test_simulated_create_receipts_then_authoritative_owner_and_material_proof(status: int) -> None:
    recording = PreparationRecording()
    async with preparation_source(recording) as (client, owner):
        profile = recording.profile
        offer = await selected_offer(client, owner, profile)
        boundary = LbxPreparation(client, profile)
        async with owner.operation() as budget:
            customer = await client.create_user(user_command(), profile=profile, budget=budget)
            customer_proof = await boundary.prove_customer(
                user_id=customer.user_id, billing_customer_key=CUSTOMER_KEY, budget=budget
            )
            assert customer_proof.state == ProofState.COMPLETE_MATCH
            agreement = await client.create_agreement(agreement_command(), profile=profile, budget=budget)
            assert agreement.agreement_id == AGREEMENT_ID
            recording.post_status = status
            receipt = await client.create_subscription(
                subscription_command(), profile=profile, offer=offer, budget=budget
            )
            assert receipt.subscription_id == SUBSCRIPTION_ID
            proof = await boundary.prove_subscription(
                subscription_id=receipt.subscription_id,
                expected=subscription_command(),
                agreement=agreement_command(),
                billing_customer_key=CUSTOMER_KEY,
                offer=offer,
                budget=budget,
            )
        assert proof.state == ProofState.COMPLETE_MATCH and proof.value is not None
        assert proof.evidence_mode == "SIMULATED"
        assert proof.value.recurring_amount_minor == 20002
        assert proof.value.connection_amount_minor == 1406
        assert proof.value.account_id == profile.selection.external_billing_account_id
        assert proof.value.currency == "RUB"
        assert proof.value.selected_evidence_digest == offer.selected_evidence_digest
        posts = [request for request in recording.requests if request.method == "POST"]
        assert len(posts) == 3
        assert json.loads(posts[0].content) == user_command().model_dump(exclude_none=True)
        agreement_body = json.loads(posts[1].content)
        assert agreement_body["organization_id"] == profile.organization_id
        assert type(agreement_body["debt_threshold"]) is int and agreement_body["debt_threshold"] == 0
        subscription_body = json.loads(posts[2].content)
        assert subscription_body["services"] == [{"tariff_service_id": 1001, "multiplicator": 2}]
        assert subscription_body["activate_by_balance"] is True
        assert subscription_body["activate_manually"] is False
        assert subscription_body["demo_period_length"] == 0
        assert all(request.url.host == "purchase-recording.invalid" for request in recording.requests)


@pytest.mark.parametrize("fault", ["401", "403", "429", "500", "503", "timeout", "disconnect"])
@pytest.mark.parametrize("kind", ["customer", "agreement", "subscription"])
async def test_possible_send_is_explicit_and_never_retried(kind: str, fault: str) -> None:
    recording = PreparationRecording()
    async with preparation_source(recording) as (client, owner):
        offer = await selected_offer(client, owner, recording.profile)
        recording.requests.clear()
        recording.post_fault = fault
        async with owner.operation() as budget:
            with pytest.raises(LbxCreateUncertain) as error:
                if kind == "customer":
                    await client.create_user(user_command(), profile=recording.profile, budget=budget)
                elif kind == "agreement":
                    await client.create_agreement(agreement_command(), profile=recording.profile, budget=budget)
                else:
                    await client.create_subscription(
                        subscription_command(), profile=recording.profile, offer=offer, budget=budget
                    )
        assert error.value.possible_send is True
        assert str(error.value) == "lbx_create_uncertain"
        assert [request.method for request in recording.requests] == ["POST"]


async def test_auth_is_acquired_before_send_and_failure_does_not_claim_possible_send() -> None:
    recording = PreparationRecording()
    recording.auth_status = 401
    async with preparation_source(recording) as (client, owner):
        with pytest.raises(LbxAuthenticationFailed):
            async with owner.operation() as budget:
                await client.create_user(user_command(), profile=recording.profile, budget=budget)
    assert [(request.method, request.url.path) for request in recording.requests] == [("GET", API_PATH + "/auth")]


@pytest.mark.parametrize(
    "body",
    [
        b'{"code":200,"response":{}}',
        b'{"code":200,"response":{"user_id":1501,"extra":"private"}}',
        b'{"code":200,"response":{"user_id":1501.0}}',
        b'{"code":200,"response":{"user_id":1501,"user_id":1502}}',
    ],
)
async def test_malformed_post_body_is_uncertain_even_on_documented_success(body: bytes) -> None:
    recording = PreparationRecording()
    recording.post_response = body
    async with preparation_source(recording) as (client, owner):
        with pytest.raises(LbxCreateUncertain):
            async with owner.operation() as budget:
                await client.create_user(user_command(), profile=recording.profile, budget=budget)
    assert sum(request.method == "POST" for request in recording.requests) == 1


@pytest.mark.parametrize("kind", ["customer", "agreement"])
async def test_only_subscription_accepts_observed_200_post_status(kind: str) -> None:
    recording = PreparationRecording()
    recording.post_status = 200
    async with preparation_source(recording) as (client, owner):
        with pytest.raises(LbxCreateUncertain):
            async with owner.operation() as budget:
                if kind == "customer":
                    await client.create_user(user_command(), profile=recording.profile, budget=budget)
                else:
                    await client.create_agreement(agreement_command(), profile=recording.profile, budget=budget)


@pytest.mark.parametrize(
    "changes, expected",
    [
        ({"services": []}, ProofState.MISMATCH),
        ({"services": None}, ProofState.INCOMPLETE),
        ({"agreement_id": 999}, ProofState.OWNER_CONFLICT),
        ({"tariff_id": 999}, ProofState.MISMATCH),
        ({"period_id": 999}, ProofState.MISMATCH),
        ({"total_price": 200.03}, ProofState.MISMATCH),
        ({"currency_symbol": "USD"}, ProofState.MISMATCH),
        ({"currency_symbol": None}, ProofState.INCOMPLETE),
        ({"is_demo": True}, ProofState.MISMATCH),
        ({"state": -3}, ProofState.MISMATCH),
        ({"subscription_start_date": "2026-10-17 00:00:00"}, ProofState.MISMATCH),
        ({"last_tariffication_period_end": "not-a-calendar-value"}, ProofState.INCOMPLETE),
        ({"subscription_end_date": "2026-10-25 00:00:00"}, ProofState.MISMATCH),
        ({"next_change_date": "2026-10-25 00:00:00"}, ProofState.MISMATCH),
        ({"next_change_date": None}, ProofState.INCOMPLETE),
    ],
)
async def test_point_readback_conflicts_never_yield_complete_match(changes: dict, expected: ProofState) -> None:
    recording = PreparationRecording()
    recording.change("subscription", lambda body: body.update(changes))
    async with preparation_source(recording) as (client, owner):
        offer = await selected_offer(client, owner, recording.profile)
        async with owner.operation() as budget:
            proof = await LbxPreparation(client, recording.profile).prove_subscription(
                subscription_id=SUBSCRIPTION_ID,
                expected=subscription_command(),
                agreement=agreement_command(),
                billing_customer_key=CUSTOMER_KEY,
                offer=offer,
                budget=budget,
            )
    assert proof.state == expected and proof.value is None


@pytest.mark.parametrize(
    "change, expected",
    [
        ({"price": 105.01}, ProofState.MISMATCH),
        ({"price": "100.01"}, ProofState.INCOMPLETE),
        ({"price": 100.011}, ProofState.INCOMPLETE),
        ({"price": None}, ProofState.INCOMPLETE),
        ({"tariff_service_id": 999}, ProofState.MISMATCH),
        ({"multiplicator": 3}, ProofState.MISMATCH),
        ({"multiplicator": 2.5}, ProofState.INCOMPLETE),
        ({"bulk_service": True}, ProofState.MISMATCH),
        ({"periodic_service": 0}, ProofState.MISMATCH),
    ],
)
async def test_effective_service_fields_not_catalog_price_prove_material(change: dict, expected: ProofState) -> None:
    recording = PreparationRecording()
    recording.change("subscription", lambda body: body["services"][0].update(change))
    async with preparation_source(recording) as (client, owner):
        offer = await selected_offer(client, owner, recording.profile)
        async with owner.operation() as budget:
            proof = await LbxPreparation(client, recording.profile).prove_subscription(
                subscription_id=SUBSCRIPTION_ID,
                expected=subscription_command(),
                agreement=agreement_command(),
                billing_customer_key=CUSTOMER_KEY,
                offer=offer,
                budget=budget,
            )
    assert proof.state == expected and proof.value is None


async def test_extra_default_service_is_refused_and_tariff_price_is_comparison_only() -> None:
    recording = PreparationRecording()
    recording.change("subscription", lambda body: body["services"].append({"service_id": 1902}))
    async with preparation_source(recording) as (client, owner):
        offer = await selected_offer(client, owner, recording.profile)
        boundary = LbxPreparation(client, recording.profile)
        async with owner.operation() as budget:
            proof = await boundary.prove_subscription(
                subscription_id=SUBSCRIPTION_ID,
                expected=subscription_command(),
                agreement=agreement_command(),
                billing_customer_key=CUSTOMER_KEY,
                offer=offer,
                budget=budget,
            )
            assert proof.state == ProofState.MISMATCH
            recording.change("subscription", lambda body: body["services"][0].update(tariff_price=999))
            proof = await boundary.prove_subscription(
                subscription_id=SUBSCRIPTION_ID,
                expected=subscription_command(),
                agreement=agreement_command(),
                billing_customer_key=CUSTOMER_KEY,
                offer=offer,
                budget=budget,
            )
    assert proof.state == ProofState.COMPLETE_MATCH


@pytest.mark.parametrize(
    "name, changes, state",
    [
        ("user", {"outer_id": "foreign"}, ProofState.IDENTITY_CONFLICT),
        ("user", {"user_id": 999}, ProofState.IDENTITY_CONFLICT),
        ("user", {"outer_id": None}, ProofState.INCOMPLETE),
        ("agreement", {"organization_id": None}, ProofState.INCOMPLETE),
        ("agreement", {"organization_id": 999}, ProofState.OWNER_CONFLICT),
        ("agreement", {"user_id": 999}, ProofState.OWNER_CONFLICT),
        ("agreement", {"credit": 1}, ProofState.MISMATCH),
        ("agreement", {"debt_threshold": 1}, ProofState.MISMATCH),
        ("agreement", {"currency_symbol": "unknown"}, ProofState.MISMATCH),
        ("agreement", {"agreement_number": "another-purchase"}, ProofState.MISMATCH),
    ],
)
async def test_identity_seller_dedication_and_credit_proofs(name: str, changes: dict, state: ProofState) -> None:
    recording = PreparationRecording()
    recording.change(name, lambda body: body.update(changes))
    async with preparation_source(recording) as (client, owner):
        async with owner.operation() as budget:
            proof = await LbxPreparation(client, recording.profile).prove_agreement(
                agreement_id=AGREEMENT_ID,
                expected=agreement_command(),
                billing_customer_key=CUSTOMER_KEY,
                budget=budget,
            )
    assert proof.state == state and proof.value is None


async def test_unknown_currency_or_wrong_account_cannot_be_repaired_from_symbol() -> None:
    recording = PreparationRecording()
    async with preparation_source(recording) as (client, owner):
        profile = recording.profile
        assert profile.inputs.currency is not None
        for inputs in (
            profile.inputs.model_copy(update={"currency": None}),
            profile.inputs.model_copy(
                update={"currency": profile.inputs.currency.model_copy(update={"iso_currency": None})}
            ),
        ):
            with pytest.raises(LbxPreparationBlocked):
                LbxPreparation(client, profile.model_copy(update={"inputs": inputs}))
        selection = profile.selection.model_copy(update={"external_billing_account_id": "another-account"})
        with pytest.raises(LbxPreparationBlocked):
            LbxPreparation(client, profile.model_copy(update={"selection": selection}))
    assert recording.requests == []


async def test_unapproved_fields_flags_quantity_and_service_rule_fail_before_send() -> None:
    recording = PreparationRecording()
    async with preparation_source(recording) as (client, owner):
        offer = await selected_offer(client, owner, recording.profile)
        recording.requests.clear()
        async with owner.operation() as budget:
            with pytest.raises(LbxPreparationBlocked):
                await client.create_user(
                    user_command().model_copy(update={"user_name": "Uncollected name"}),
                    profile=recording.profile,
                    budget=budget,
                )
            with pytest.raises(LbxPreparationBlocked):
                await client.create_agreement(
                    agreement_command().model_copy(update={"organization_id": 999}),
                    profile=recording.profile,
                    budget=budget,
                )
            for changes in (
                {"activate_manually": True},
                {"activate_by_balance": False},
                {"demo_period_length": 1},
                {"services": None},
                {"services": [NewServiceInfo(tariff_service_id=1001, multiplicator=10)]},
            ):
                with pytest.raises(LbxPreparationBlocked):
                    await client.create_subscription(
                        subscription_command().model_copy(update=changes),
                        profile=recording.profile,
                        offer=offer,
                        budget=budget,
                    )
            fractional = replace(
                offer, terms=replace(offer.terms, quantity=replace(offer.terms.quantity, selected=Decimal("2.5")))
            )
            with pytest.raises(LbxPreparationBlocked):
                await client.create_subscription(
                    subscription_command(), profile=recording.profile, offer=fractional, budget=budget
                )
    assert recording.requests == []


async def test_selected_account_default_rule_omits_services_only_when_explicitly_authorized() -> None:
    recording = PreparationRecording()
    async with preparation_source(recording) as (client, owner):
        offer = await selected_offer(client, owner, recording.profile)
        profile = recording.profile.model_copy(update={"service_composition": "account_default_single"})
        async with owner.operation() as budget:
            await client.create_subscription(
                subscription_command().model_copy(update={"services": None}),
                profile=profile,
                offer=offer,
                budget=budget,
            )
    post = next(request for request in recording.requests if request.method == "POST")
    assert "services" not in json.loads(post.content)


@pytest.mark.parametrize("count", [0, 1, 2])
async def test_scoped_discovery_is_only_a_hint_even_with_zero_or_one_result(count: int) -> None:
    recording = PreparationRecording()

    def rows(body: list) -> None:
        row = body[0]
        body[:] = [{**row, "subscription_id": SUBSCRIPTION_ID + offset} for offset in range(count)]

    recording.change("subscriptions", rows)
    async with preparation_source(recording) as (client, owner):
        async with owner.operation() as budget:
            proof = await LbxPreparation(client, recording.profile).discover(
                user_id=USER_ID, billing_customer_key=CUSTOMER_KEY, budget=budget
            )
    assert proof.state == ProofState.UNRESOLVED and proof.value is not None
    assert len(proof.value.candidate_ids) == count
    inventory = next(request for request in recording.requests if request.url.path == API_PATH + "/subscriptions")
    assert json.loads(inventory.content) == {"user_id": USER_ID}
    assert all(request.method == "GET" for request in recording.requests)


async def test_discovery_refuses_local_cap_duplicates_malformed_and_foreign_owner() -> None:
    for fault in ("cap", "duplicate", "malformed", "foreign"):
        recording = PreparationRecording()
        if fault == "duplicate":
            recording.change("subscriptions", lambda rows: rows.append(rows[0].copy()))
        elif fault == "malformed":
            recording.change("subscriptions", lambda rows: rows[0].update(agreement_id=None))
        elif fault == "foreign":
            recording.change("agreement", lambda row: row.update(user_id=999))
        async with preparation_source(recording, lbx_discovery_max_items=1 if fault == "cap" else 50) as (
            client,
            owner,
        ):
            with pytest.raises((LbxResponseInvalid, LbxScopeMismatch)):
                async with owner.operation() as budget:
                    await client.discover_subscriptions(user_id=USER_ID, budget=budget)


async def test_customer_and_agreement_discovery_use_only_documented_scoped_filters() -> None:
    recording = PreparationRecording()
    async with preparation_source(recording) as (client, owner):
        boundary = LbxPreparation(client, recording.profile)
        async with owner.operation() as budget:
            customer = await boundary.customer_hints(billing_customer_key=CUSTOMER_KEY, budget=budget)
            agreement = await boundary.agreement_hints(
                user_id=USER_ID, billing_customer_key=CUSTOMER_KEY, budget=budget
            )
    assert customer.state == agreement.state == ProofState.UNRESOLVED
    assert customer.value is not None and customer.value.candidate_ids == (USER_ID,)
    assert agreement.value is not None and agreement.value.candidate_ids == (AGREEMENT_ID,)
    filters = {request.url.path: json.loads(request.content) for request in recording.requests if request.content}
    assert filters[API_PATH + "/users"] == {"outer_id": CUSTOMER_KEY, "show_passwords": False}
    assert filters[API_PATH + "/agreements"] == {"user_id": USER_ID}


async def test_create_disabled_without_recorded_transport_and_missing_seller_does_not_block_settings() -> None:
    config = lbx_settings()
    assert config.lbx_seller_organization_id is None
    client = LbxServerClient(config)
    try:
        with pytest.raises(LbxPreparationBlocked):
            LbxPreparation(client, preparation_profile())
    finally:
        await client.aclose()
    recording = PreparationRecording()
    async with preparation_source(recording, lbx_seller_organization_id=999) as (client, owner):
        with pytest.raises(LbxPreparationBlocked):
            LbxPreparation(client, recording.profile)
    assert recording.requests == []


async def test_production_never_accepts_simulated_create_even_with_injected_transport() -> None:
    recording = PreparationRecording()
    # Copy avoids unrelated production URL/bootstrap validators: this test
    # targets the CREATE gate itself, including a miswired injected transport.
    config = lbx_settings().model_copy(update={"app_env": AppEnv.PRODUCTION})
    client = LbxServerClient(config, transport=httpx.MockTransport(recording.respond))
    try:
        with pytest.raises(LbxPreparationBlocked):
            LbxPreparation(client, recording.profile)
    finally:
        await client.aclose()
    assert recording.requests == []


async def test_private_diagnostics_receipts_dtos_and_failures_do_not_expose_secrets_or_pii(
    caplog: pytest.LogCaptureFixture,
) -> None:
    recording = PreparationRecording()
    caplog.set_level(logging.DEBUG)
    async with preparation_source(recording) as (client, owner):
        async with owner.operation() as budget:
            dto = await client.get_user(user_id=USER_ID, budget=budget)
            receipt = await client.create_user(user_command(), profile=recording.profile, budget=budget)
            recording.post_fault = "500"
            with pytest.raises(LbxCreateUncertain) as error:
                await client.create_user(user_command(), profile=recording.profile, budget=budget)
    visible = caplog.text + repr(dto) + str(dto) + repr(receipt) + str(error.value) + repr(recording.profile)
    for private in (
        TOKEN,
        CUSTOMER_KEY,
        "customer@example.invalid",
        "SIMULATED-private-remote-payload",
        "Bearer",
        "Authorization",
    ):
        assert private not in visible


@pytest.mark.parametrize("value", [2.5, 2.0, "2", True])
async def test_fractional_or_coerced_multiplier_is_not_repaired(value: Any) -> None:
    with pytest.raises(ValidationError):
        NewServiceInfo(tariff_service_id=1001, multiplicator=value)


async def test_private_validation_hides_pii_and_customer_type_is_not_boolean() -> None:
    with pytest.raises(ValidationError) as error:
        PostUser(type=True, outer_id=CUSTOMER_KEY, email="customer@example.invalid")
    assert CUSTOMER_KEY not in str(error.value) and "customer@example.invalid" not in str(error.value)


async def test_wire_money_remains_exact_under_small_decimal_context() -> None:
    recording = PreparationRecording()
    async with preparation_source(recording) as (client, owner):
        offer = await selected_offer(client, owner, recording.profile)
        with localcontext() as context:
            context.prec = 2
            async with owner.operation() as budget:
                proof = await LbxPreparation(client, recording.profile).prove_subscription(
                    subscription_id=SUBSCRIPTION_ID,
                    expected=subscription_command(),
                    agreement=agreement_command(),
                    billing_customer_key=CUSTOMER_KEY,
                    offer=offer,
                    budget=budget,
                )
    assert proof.state == ProofState.COMPLETE_MATCH and proof.value is not None
    assert proof.value.recurring_amount_minor == 20002


async def test_same_step_two_profile_supplies_seller_currency_calendar_and_source_identity() -> None:
    old = json.loads((DIRECTORY / "profile.json").read_bytes())
    profile = preparation_profile()
    assert profile.selection.model_dump(mode="json") == old["selection"]
    assert profile.inputs.model_dump(mode="json") == old["inputs"]
    assert profile.organization_id == old["seller"]["organization_id"]


@pytest.mark.parametrize("termination", ["cancel", "deadline"])
async def test_post_cancellation_or_absolute_deadline_is_uncertain_without_resend(
    termination: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    recording = PreparationRecording()
    entered = asyncio.Event()
    original = recording.respond

    async def delayed(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            recording.requests.append(request)
            entered.set()
            await asyncio.Event().wait()
        return await original(request)

    monkeypatch.setattr(recording, "respond", delayed)
    async with preparation_source(
        recording, preflight_total_timeout_seconds=0.2, preflight_cleanup_timeout_seconds=0.02
    ) as (client, owner):

        async def create() -> None:
            async with owner.operation() as budget:
                await client.create_user(user_command(), profile=recording.profile, budget=budget)

        task = asyncio.create_task(create())
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            if termination == "cancel":
                task.cancel()
            with pytest.raises(LbxCreateUncertain):
                await task
        finally:
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        assert sum(request.method == "POST" for request in recording.requests) == 1


async def test_nonempty_password_and_unknown_get_fields_fail_closed() -> None:
    for changes in ({"password": "SIMULATED-private-password"}, {"unknown_legal_data": "private"}):
        recording = PreparationRecording()
        recording.change("user", lambda body: body.update(changes))
        async with preparation_source(recording) as (client, owner):
            async with owner.operation() as budget:
                proof = await LbxPreparation(client, recording.profile).prove_customer(
                    user_id=USER_ID, billing_customer_key=CUSTOMER_KEY, budget=budget
                )
        assert proof.state == ProofState.INCOMPLETE and proof.value is None


async def test_duplicate_customer_hints_are_identity_conflict_and_never_complete_proof() -> None:
    recording = PreparationRecording()
    recording.change("users", lambda rows: rows.append({**rows[0], "user_id": USER_ID + 1}))
    async with preparation_source(recording) as (client, owner):
        async with owner.operation() as budget:
            proof = await LbxPreparation(client, recording.profile).customer_hints(
                billing_customer_key=CUSTOMER_KEY, budget=budget
            )
    assert proof.state == ProofState.IDENTITY_CONFLICT and proof.value is None
