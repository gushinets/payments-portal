"""Synthetic protocol/contract tests for Step 3; no live LBX requests."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import httpx
import pytest
from pydantic import ValidationError

from app.composition.sources import source_resources
from app.domains.billing.router import WidgetBootstrapRequest, WidgetBootstrapResponse
from app.domains.purchases.router import PurchaseConfirmRequest
from app.integrations.lbx.current_offer import read_current_offer
from app.integrations.lbx.financial import (
    NewAgreement,
    NewSubscription,
    Subscription,
    prove_agreement,
    prove_subscription,
    Agreement,
)
from app.integrations.lbx.errors import LbxError, LbxResponseInvalid, LbxScopeMismatch
from apps.api.tests.support.any709_step1 import step1_settings, link_selection
from apps.api.tests.support.any709_step3 import PurchaseTransport

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def fixed_billing_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("path", ["/agreements", "/subscriptions"])
@pytest.mark.parametrize("status", [200, 201, 500])
async def test_any709_step3_create_uses_shared_decoder_and_never_retries(path: str, status: int) -> None:
    sends = []

    def respond(request: httpx.Request) -> httpx.Response:
        sends.append(request)
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "synthetic", "expires_in": 60}})
        if status == 500:
            return httpx.Response(status, json={"code": 500, "response": {"error": "PRIVATE canary"}})
        return httpx.Response(
            status,
            json={"code": status, "response": {"agreement_id" if path == "/agreements" else "subscription_id": 123}},
        )

    async with source_resources(step1_settings(), lbx_transport=httpx.MockTransport(respond)) as sources:
        async with sources.billing.operation() as budget:
            client = sources.require_lbx()
            await client.prepare_customer_create(budget=budget)
            command = (
                NewAgreement(
                    user_id=345, organization_id=21, agreement_number="portal-test", create_date=date(2026, 10, 27)
                )
                if path == "/agreements"
                else NewSubscription(
                    agreement_id=456,
                    tariff_id=701,
                    period_id=901,
                    tariff_service_id=1001,
                    quantity=1,
                    outer_id="portal-test",
                )
            )
            if status == 500:
                with pytest.raises(LbxError) as caught:
                    await (
                        client.create_agreement(command, budget=budget)
                        if path == "/agreements"
                        else client.create_subscription(command, budget=budget)
                    )
                assert caught.value.response_facts.http_status == 500
                assert caught.value.response_facts.reason == "provider_rejected"
                assert "PRIVATE" not in str(caught.value)
            else:
                assert (
                    await (
                        client.create_agreement(command, budget=budget)
                        if path == "/agreements"
                        else client.create_subscription(command, budget=budget)
                    )
                    == 123
                )
    assert len([request for request in sends if request.method == "POST"]) == 1


async def test_any709_step3_effective_terms_ignore_catalog_outer_hint_and_waiting_dates() -> None:
    transport = PurchaseTransport()
    async with source_resources(step1_settings(), lbx_transport=httpx.MockTransport(transport.respond)) as sources:
        async with sources.preflight.operation() as budget:
            offer = await read_current_offer(
                sources.require_lbx(), selection=link_selection(), configuration=step1_settings(), budget=budget
            )
    raw = {
        "subscription_id": 567,
        "agreement_id": 456,
        "tariff_id": 701,
        "period_id": 901,
        "period_type": 3,
        "period_length": 1,
        "state": -2,
        "current_blocking": 0,
        "is_demo": False,
        "is_offer_agrm": False,
        "currency_symbol": "rub",
        "total_price": 100,
        "outer_id": "changed-nonunique-hint",
        "subscription_start_date": None,
        "last_tariffication_period_start": "1970-01-01 00:00:00",
        "services": [
            {
                "tariff_service_id": 1001,
                "multiplicator": Decimal(1),
                "price": Decimal(100),
                "tariff_price": Decimal(999),
                "bulk_service": False,
                "periodic_service": 1,
                "bulk_price": 0,
                "bulk_include_amount": 0,
            }
        ],
    }
    point = Subscription.model_validate(raw)
    prove_subscription(point, agreement_id=456, selection=link_selection(), offer=offer)
    assert point.subscription_start_date is None
    raw["services"][0]["price"] = Decimal(101)
    with pytest.raises(LbxScopeMismatch):
        prove_subscription(Subscription.model_validate(raw), agreement_id=456, selection=link_selection(), offer=offer)
    raw["services"][0].pop("price")
    with pytest.raises(LbxResponseInvalid):
        prove_subscription(Subscription.model_validate(raw), agreement_id=456, selection=link_selection(), offer=offer)


async def test_any709_step3_agreement_seller_and_empty_link() -> None:
    raw = {
        "agreement_id": 456,
        "user_id": 345,
        "organization_id": 21,
        "agreement_number": "portal-test",
        "is_offer": False,
        "agreement_link": "",
    }
    prove_agreement(Agreement.model_validate(raw), user_id=345, seller_id=21, number="portal-test")
    raw["organization_id"] = 9
    with pytest.raises(LbxScopeMismatch):
        prove_agreement(Agreement.model_validate(raw), user_id=345, seller_id=21, number="portal-test")
    raw.pop("organization_id")
    with pytest.raises(LbxResponseInvalid):
        prove_agreement(Agreement.model_validate(raw), user_id=345, seller_id=21, number="portal-test")


async def test_any709_step3_public_input_and_payment_flags_are_bounded() -> None:
    assert WidgetBootstrapRequest().purchase_intent_id is None
    assert WidgetBootstrapResponse.model_json_schema()["properties"]["disablePayments"]["type"] == "boolean"
    with pytest.raises(ValidationError):
        WidgetBootstrapRequest.model_validate({"agreement_id": 456, "disablePayments": False})
    with pytest.raises(ValidationError):
        Subscription.model_validate({"subscription_id": 1, "agreement_id": 2, "tariff_id": 3, "total_price": 0.1})
    doc = {"document_version_id": str(uuid4()), "acceptance_text_hash": "1" * 64}
    payload = {
        "product_id": "proposal_ai",
        "revision_id": str(uuid4()),
        "expected_fingerprint": "sha256:" + "1" * 64,
        "documents": [doc, doc],
    }
    with pytest.raises(ValidationError):
        PurchaseConfirmRequest.model_validate(payload)
    assert (
        "subscription_start_date"
        not in NewSubscription(
            agreement_id=456, tariff_id=701, period_id=901, tariff_service_id=1001, quantity=1, outer_id="test"
        ).request_document()
    )
    # The original evidence, never a price/amount/provider ID supplied by browser.
    payload["documents"] = [doc]
    payload["amount"] = "1"
    with pytest.raises(ValidationError):
        PurchaseConfirmRequest.model_validate(payload)
    assert "portal-test" not in json.dumps(WidgetBootstrapResponse.model_json_schema())


@pytest.mark.parametrize("payment", [False, True])
async def test_any709_step3_widget_response_enables_only_verified_payment_presentation(
    monkeypatch: pytest.MonkeyPatch, payment: bool
) -> None:
    from fastapi import FastAPI
    from pydantic import SecretStr
    from app.composition.billing import AccountWidget
    from app.domains.billing import router as routes
    from app.http.dependencies import get_session_factory

    purchase_id = uuid4()

    async def bootstrap(*args: object, **kwargs: object) -> AccountWidget:
        assert kwargs["purchase_id"] == (purchase_id if payment else None)
        return AccountWidget(
            SecretStr("synthetic-jwt"),
            "https://billing.test",
            purchase_id if payment else None,
            "portal-proof" if payment else None,
            "21" if payment else None,
        )

    monkeypatch.setattr(routes, "bootstrap_account", bootstrap)
    app = FastAPI()
    app.include_router(routes.router)
    app.state.sources = object()
    app.dependency_overrides[get_session_factory] = lambda: object()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client:
        response = await client.post(
            "/api/billing/widget-bootstrap",
            json={"purchase_intent_id": str(purchase_id)} if payment else {},
            headers={"Authorization": "Bearer synthetic"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["presentation"] == ("payment" if payment else "account")
    assert body["disablePayments"] is not payment
    assert all(
        body[field] is True
        for field in (
            "disableCreateSubscription",
            "disableEditSubscription",
            "disableStopSubscription",
            "disableAutopayments",
            "disableInvoiceGeneration",
        )
    )
    assert body["payment_target"] == (
        {"purchase_intent_id": str(purchase_id), "agreement_reference": "portal-proof", "seller_reference": "21"}
        if payment
        else None
    )
    assert response.headers["cache-control"] == "no-store"


async def test_any709_step3_observation_time_does_not_change_consent_and_connection_proof_is_required() -> None:
    from dataclasses import replace

    transport = PurchaseTransport()
    async with source_resources(step1_settings(), lbx_transport=httpx.MockTransport(transport.respond)) as sources:
        async with sources.preflight.operation() as budget:
            first = await read_current_offer(
                sources.require_lbx(), selection=link_selection(), configuration=step1_settings(), budget=budget
            )
            second = await read_current_offer(
                sources.require_lbx(), selection=link_selection(), configuration=step1_settings(), budget=budget
            )
    assert first.fingerprint == second.fingerprint
    money = replace(first.money, connection_amount=Decimal(7), connection_unit_amount=Decimal(7))
    point = Subscription.model_validate(
        {
            "subscription_id": 567,
            "agreement_id": 456,
            "tariff_id": 701,
            "period_id": 901,
            "period_type": 3,
            "period_length": 1,
            "state": -2,
            "current_blocking": 0,
            "is_demo": False,
            "is_offer_agrm": False,
            "currency_symbol": "руб",
            "total_price": 100,
            "subscription_start_date": "3000-01-01 00:00:00",
            "services": [
                {
                    "tariff_service_id": 1001,
                    "multiplicator": 1,
                    "price": 100,
                    "periodic_service": 1,
                    "bulk_service": False,
                    "bulk_price": None,
                    "bulk_include_amount": None,
                }
            ],
        }
    )
    with pytest.raises(LbxResponseInvalid):
        prove_subscription(point, agreement_id=456, selection=link_selection(), offer=replace(first, money=money))
    prove_subscription(point, agreement_id=456, selection=link_selection(), offer=first)


async def test_any709_step3_agreement_date_uses_confirmed_moscow_midnight(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 26, 20, 59, tzinfo=UTC))
    assert current_offer.current_billing_date() == date(2026, 10, 26)
    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 26, 21, 0, tzinfo=UTC))
    command = NewAgreement(
        user_id=345,
        organization_id=21,
        agreement_number="portal-proof",
        create_date=current_offer.current_billing_date(),
    )
    assert command.request_document()["create_date"] == "2026-10-27"
    assert "debt_threshold" not in command.request_document() and command.is_offer is False
