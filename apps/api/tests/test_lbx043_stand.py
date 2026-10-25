"""043 local wiring and private DTO security using in-process transport only."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import replace
from decimal import localcontext
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import SecretStr

from app.composition.purchases import load_profile
from app.core.settings import AppEnv
from app.domains.catalog.mapping_evidence import MappingEvidenceMode
from app.domains.purchases.contracts import PurchaseRefused
from app.domains.purchases.preparation_contracts import CreateUncertain, ProofState
from app.integrations.lbx.errors import LbxPreparationBlocked
from app.integrations.lbx.preparation import LbxPreparation
from app.integrations.lbx.preparation_dto import PostAgreement, PostUser, PostSubscription, NewServiceInfo
from app.integrations.lbx.purchase_preparation import LbxPurchasePreparation, PreparationRecord
from app.integrations.lbx.stand import Stand043Permission
from app.integrations.lbx.widget import LocalStandWidgetPermission, sign_widget_jwt
from app.models import ExternalCreateOperationKind as Kind
from apps.api.tests.support.lbx043 import (
    PORTAL_USER_ID,
    StandRecording,
    configured_profile,
    stand_source,
    stand_offer,
    stand_settings,
    mapping_for,
)
from apps.api.tests.support.lbx_preparation import CUSTOMER_KEY, USER_ID, AGREEMENT_ID, SUBSCRIPTION_ID


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def record() -> PreparationRecord:
    profile = configured_profile()
    return PreparationRecord(
        schema_version="LOCAL-043-purchase-preparation-v1",
        profile=profile,
        customer=PostUser(type=2, outer_id=CUSTOMER_KEY, email="fixture@example.invalid"),
        agreement=PostAgreement(
            user_id=USER_ID,
            organization_id=21,
            agreement_number="SIMULATED-held-purchase-reference",
            create_date=profile.selection.effective_on,
            is_offer=False,
        ),
        subscription=PostSubscription(
            agreement_id=AGREEMENT_ID,
            tariff_id=32,
            period_id=1,
            activate_by_balance=True,
            activate_manually=False,
            demo_period_length=0,
            outer_id="SIMULATED-subscription-hint",
            services=[NewServiceInfo(tariff_service_id=1, multiplicator=1)],
        ),
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"app_env": AppEnv.PRODUCTION},
        {"app_env": AppEnv.TEST},
        {"lbx043_enabled": False},
        {"lbx_base_url": "https://043.lbxbilling.ru.evil.invalid"},
        {"lbx_base_url": "http://043.lbxbilling.ru"},
        {"lbx_base_url": "https://043.lbxbilling.ru/"},
        {"lbx_seller_organization_id": 9},
        {"lbx_widget_signing_secret": SecretStr("")},
        {"mapping_account_id": "foreign"},
        {"lbx043_test_user_ids": ()},
        {"purchase_stand_profile_file": None},
        {"purchase_simulated_profile_file": Path("/test-only/profile.json")},
    ],
)
async def test_partial_wrong_scope_and_default_real_enablement_refused(overrides: dict) -> None:
    with pytest.raises(PurchaseRefused, match="purchase_not_enabled"):
        Stand043Permission.configured(stand_settings().model_copy(update=overrides))


async def test_allowlist_and_financial_side_effect_approval_are_independent() -> None:
    permission = Stand043Permission.configured(stand_settings(lbx043_financial_approval_reference=""))
    permission.require_user(PORTAL_USER_ID)
    with pytest.raises(PurchaseRefused, match="purchase_ineligible"):
        permission.require_user(uuid4())
    with pytest.raises(PurchaseRefused, match="financial_approval_required"):
        permission.require_financial_approval()
    with pytest.raises(PurchaseRefused):
        load_profile(stand_settings().model_copy(update={"app_env": AppEnv.PRODUCTION}))


@pytest.mark.parametrize(
    "names",
    [
        {},
        {"user_name": "Анна"},
        {"user_surname": "Иванова"},
        {"user_patronymic": "Ильинична"},
        {"user_surname": "Иванова", "user_name": "Анна", "user_patronymic": "Ильинична"},
    ],
)
async def test_five_base_fields_plus_only_supplied_names_and_no_credential_persistence(
    names: dict[str, str], caplog: pytest.LogCaptureFixture
) -> None:
    recording = StandRecording()
    seen: list[tuple[str, str]] = []

    def inspect(path: str, body: dict) -> None:
        assert path == "/users"
        assert set(body) == {"type", "email", "outer_id", "login", "password"} | names.keys()
        assert all(body[name] == value for name, value in names.items())
        login, password = body["login"], body["password"]
        assert login.startswith("any709_") and len(login) == 31
        assert len(password) == 24 and password.isascii() and password.isalnum()
        assert (
            any(c.isupper() for c in password)
            and any(c.islower() for c in password)
            and any(c.isdigit() for c in password)
        )
        seen.append((login, password))  # test assertion only; never an artifact/log

    recording.inspect_post = inspect
    caplog.set_level(logging.DEBUG)
    command = record()
    async with stand_source(recording) as (client, owner):
        offer = await stand_offer(client, owner)
        gateway = LbxPurchasePreparation(client, command, offer, customer_fields=names)
        async with owner.operation() as budget:
            await gateway.before_send(Kind.CUSTOMER, budget)
            assert await gateway.discover_before_send(Kind.CUSTOMER, budget) is None
            assert await gateway.create(Kind.CUSTOMER, budget) == USER_ID
    stored = command.storage_document()
    assert not (set(names) & stored["customer"].keys())
    dumped = repr(command) + str(command) + json.dumps(stored) + caplog.text
    assert len(seen) == 1
    assert all(private not in dumped for private in seen[0])
    ephemeral = command.customer.with_technical_credentials()
    assert "password" not in ephemeral.model_dump() and "login" not in ephemeral.model_dump(mode="json")
    assert (
        "password" not in PreparationRecord(profile=command.profile, customer=ephemeral).storage_document()["customer"]
    )


async def test_agreement_discovery_ignores_auto_org_nine_and_uses_documented_json_filter() -> None:
    recording = StandRecording()
    async with stand_source(recording) as (client, owner):
        offer = await stand_offer(client, owner)
        gateway = LbxPurchasePreparation(client, record(), offer)
        async with owner.operation() as budget:
            assert await gateway.discover_before_send(Kind.AGREEMENT, budget) is None
            assert ("GET", "/agreements/25") in recording.requests
            assert not any(method == "POST" for method, _ in recording.requests)
            recording.rows["agreements"][0]["organization_id"] = 21
            result = await gateway.discover_before_send(Kind.AGREEMENT, budget)
            assert result.state == ProofState.OWNER_CONFLICT


async def test_real_agreement_and_subscription_wire_omits_unsupported_debt_and_start_date() -> None:
    recording = StandRecording()
    observed: dict[str, dict] = {}
    recording.inspect_post = lambda path, body: observed.update({path: body})
    command = record()
    async with stand_source(recording) as (client, owner):
        offer = await stand_offer(client, owner)
        async with owner.operation() as budget:
            await client.create_agreement(command.agreement, profile=command.profile, budget=budget)
            await client.create_subscription(command.subscription, profile=command.profile, offer=offer, budget=budget)
    assert "debt_threshold" not in observed["/agreements"] and "agreement_link" not in observed["/agreements"]
    assert observed["/agreements"]["organization_id"] == 21
    assert "subscription_start_date" not in observed["/subscriptions"]
    assert observed["/subscriptions"]["period_id"] == 1
    assert observed["/subscriptions"]["services"] == [{"tariff_service_id": 1, "multiplicator": 1}]


@pytest.mark.parametrize("date_only", [False, True])
async def test_waiting_dates_are_facts_and_exact_major_rub_does_not_grant_a_period(date_only: bool) -> None:
    recording = StandRecording()
    if date_only:
        recording.rows["subscription"]["subscription_start_date"] = "3000-01-01"
        recording.rows["subscription"]["subscription_end_date"] = "9999-12-31"
    command = record()
    async with stand_source(recording) as (client, owner):
        offer = await stand_offer(client, owner)
        with localcontext() as ctx:
            ctx.prec = 2
            async with owner.operation() as budget:
                proof = await LbxPreparation(client, command.profile).prove_subscription(
                    subscription_id=SUBSCRIPTION_ID,
                    expected=command.subscription,
                    agreement=command.agreement,
                    billing_customer_key=CUSTOMER_KEY,
                    offer=offer,
                    budget=budget,
                )
    assert proof.state == ProofState.COMPLETE_MATCH
    assert proof.value.recurring_amount_minor == 10000
    assert proof.value.period_start is None and proof.value.period_end is None
    assert proof.observed_facts["subscription_start_date"] == ("3000-01-01" if date_only else "3000-01-01 00:00:00")
    assert proof.observed_facts["last_tariffication_period_end"] is None
    assert offer.evidence_mode == "CONFIGURED_SOURCE"
    document = mapping_for(offer)
    assert document.evidence_mode == MappingEvidenceMode.SIMULATED
    assert document.lbx_evidence_mode == "CONFIGURED_SOURCE"
    permission = Stand043Permission.configured(stand_settings())
    local = LocalStandWidgetPermission(permission, PORTAL_USER_ID, document)
    token = sign_widget_jwt(
        customer_id=str(USER_ID),
        secret=SecretStr("x" * 32),
        evidence_mode=document.evidence_mode,
        local_permission=local,
        clock=lambda: 1792600000,
    )
    payload = json.loads(base64.urlsafe_b64decode(token.split(".")[1] + "=="))
    assert payload == {"ident_type": 7, "ident": str(USER_ID), "iat": 1792600000}
    with pytest.raises(PurchaseRefused):
        sign_widget_jwt(
            customer_id=str(USER_ID),
            secret=SecretStr("x" * 32),
            evidence_mode=document.evidence_mode,
            local_permission=replace(local, user_id=uuid4()),
        )
    with pytest.raises(PurchaseRefused):
        replace(local, mapping=document.model_copy(update={"lbx_evidence_mode": "SIMULATED"})).require_source()


@pytest.mark.parametrize(
    "field,value",
    [("credit", 1), ("balance", -1), ("organization_id", 9), ("user_id", 999), ("close_date", "2026-10-17")],
)
async def test_owner_seller_and_financial_conflicts_fail_closed(field: str, value: object) -> None:
    recording = StandRecording()
    recording.rows["agreement"][field] = value
    command = record()
    async with stand_source(recording) as (client, owner):
        async with owner.operation() as budget:
            proof = await LbxPreparation(client, command.profile).prove_agreement(
                agreement_id=AGREEMENT_ID,
                expected=command.agreement,
                billing_customer_key=CUSTOMER_KEY,
                budget=budget,
            )
    assert proof.state != ProofState.COMPLETE_MATCH


async def test_missing_financial_policy_or_operator_approval_cannot_post_subscription() -> None:
    recording = StandRecording()
    command = record()
    async with stand_source(recording, lbx043_financial_approval_reference="") as (client, owner):
        offer = await stand_offer(client, owner)
        async with owner.operation() as budget:
            with pytest.raises(PurchaseRefused, match="financial_approval_required"):
                await client.create_subscription(
                    command.subscription, profile=command.profile, offer=offer, budget=budget
                )
    assert not any(method == "POST" for method, _ in recording.requests)
    with pytest.raises(LbxPreparationBlocked):
        command.profile.model_copy(update={"financial_policy_evidence": None}).require_financial_policy()


@pytest.mark.parametrize("fault", ["price", "extra_service", "missing_price", "identity", "missing_login"])
async def test_changed_effective_material_and_customer_identity_never_prove_widget(fault: str) -> None:
    recording = StandRecording()
    if fault == "price":
        recording.rows["subscription"]["services"][0]["price"] = 101
    elif fault == "missing_price":
        recording.rows["subscription"]["services"][0].pop("price")
    elif fault == "extra_service":
        recording.rows["subscription"]["services"].append(recording.rows["subscription"]["services"][0].copy())
    elif fault == "identity":
        recording.rows["user"]["outer_id"] = "foreign"
    else:
        recording.rows["user"]["login"] = None
    command = record()
    async with stand_source(recording) as (client, owner):
        offer = await stand_offer(client, owner)
        async with owner.operation() as budget:
            proof = await LbxPreparation(client, command.profile).prove_subscription(
                subscription_id=SUBSCRIPTION_ID,
                expected=command.subscription,
                agreement=command.agreement,
                billing_customer_key=CUSTOMER_KEY,
                offer=offer,
                budget=budget,
            )
    assert proof.state != ProofState.COMPLETE_MATCH


async def test_timeout_read_only_recovery_never_reposts_or_regenerates_credentials() -> None:
    recording = StandRecording()
    recording.post_fault = True
    command = record()
    async with stand_source(recording) as (client, owner):
        offer = await stand_offer(client, owner)
        async with owner.operation() as budget:
            gateway = LbxPurchasePreparation(client, command, offer)
            with pytest.raises(CreateUncertain):
                await gateway.create(Kind.CUSTOMER, budget)
    stored = command.storage_document()
    assert "server_username" not in stored["profile"]
    restarted = PreparationRecord.model_validate_json(json.dumps(stored))
    assert restarted.customer.login is None
    assert restarted.customer.password is None
    recording.rows["users"] = [recording.rows["user"]]
    async with stand_source(recording) as (client, owner):
        async with owner.operation() as budget:
            # Storage cannot authorize a Server identity. Restore it from trusted
            # settings in memory, exactly as the runtime composition does.
            with pytest.raises(LbxPreparationBlocked):
                LbxPurchasePreparation(client, restarted, offer)
            restarted = restarted.model_copy(
                update={
                    "profile": restarted.profile.model_copy(
                        update={"server_username": stand_settings().lbx_server_username}
                    )
                }
            )
            gateway = LbxPurchasePreparation(client, restarted, offer)
            result = await gateway.recover(Kind.CUSTOMER, budget)
    assert result.state == ProofState.COMPLETE_MATCH and result.value == USER_ID
    assert recording.requests.count(("POST", "/users")) == 1
