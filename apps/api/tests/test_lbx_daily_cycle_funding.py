"""ANY-898 — exact-day financial proof over the ordinary LBX read path."""

from dataclasses import replace
from datetime import date
import json

import httpx
import pytest

from app.domains.billing.paid_policy import PaidDecision, paid_decision
from app.domains.catalog.commercial_offer import CommercialPeriod
from app.infrastructure.preflight import PreflightAdmission, PreflightPolicy
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.reconciliation import read_subscription_proof
from apps.api.tests.factories.reconciliation import (
    agreement_factory,
    subject_factory,
    subscription_factory,
    tariff_factory,
    user_factory,
)
from apps.api.tests.support.any709_step1 import step1_settings

DAY = "2026-11-25"


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("due", "balance", "detail_change", "expected"),
    [
        (0, 0, {}, PaidDecision.GRANT),
        (100, -100, {}, PaidDecision.KEEP),
        (0, -100, {}, PaidDecision.KEEP),
        (0, 0, {"is_predicted_charge": True}, PaidDecision.KEEP),
        (0, 0, {"is_waiting_for_activation": True}, PaidDecision.KEEP),
        (0, 0, {"service_id": 999}, PaidDecision.KEEP),
        (0, 0, {"subscription_instance_id": 999}, PaidDecision.KEEP),
        (0, 0, {"tariffication_period_end": "2026-11-24"}, PaidDecision.KEEP),
        (0, 0, {"type": 0}, PaidDecision.KEEP),
        (0, 0, {"type": None}, PaidDecision.KEEP),
        (0, 0, {"charge_sum": None}, PaidDecision.KEEP),
    ],
)
async def test_daily_metering_requires_funding_for_the_same_cycle(
    due: int, balance: int, detail_change: dict[str, object], expected: PaidDecision
) -> None:
    subject = subject_factory()
    purchase = subject.purchase
    accepted = purchase.accepted
    period = CommercialPeriod("day", 1, "first_instance_start", date(2026, 1, 1), None)
    subject = replace(
        subject,
        purchase=replace(
            purchase, accepted=accepted.model_copy(update={"offer": replace(accepted.offer, period=period)})
        ),
    )
    subscription = subscription_factory().model_dump(mode="json", exclude_none=True)
    subscription.update(
        period_type=1,
        total_price=100,
        subscription_instance_id=678,
        subscription_start_date="2026-11-24 00:00:00",
        subscription_instance_start_date="2026-11-24 00:00:00",
        last_tariffication_period_start=DAY,
        last_tariffication_period_end=DAY,
    )
    subscription["services"][0].update(service_id=789, multiplicator=1, price=100)
    agreement = agreement_factory().model_dump(mode="json", exclude_none=True)
    agreement.update(credit=0, debt_threshold=0, balance=balance)
    tariff = tariff_factory(subject).value.model_dump(mode="json", exclude_none=True)
    tariff["float_period"] = 2
    details = {
        "recommended_payment": due,
        "current_balance": balance,
        "start_period_balance": 100 if due == 0 else 0,
        "start_period": DAY,
        "end_period": DAY,
        "services": [
            {
                "subscription_instance_id": 678,
                "service_id": 789,
                "charge_type": 0,
                "charge_sum": 100,
                "tariffication_period_start": DAY,
                "tariffication_period_end": DAY,
                "is_predicted_charge": False,
                "is_waiting_for_activation": False,
                **detail_change,
            }
        ],
    }
    reads = []
    payloads = {
        "/auth": {"token": "test-auth", "expires_in": 300},
        "/users/345": user_factory().model_dump(mode="json", exclude_none=True),
        "/agreements/456": agreement,
        "/subscriptions/567": subscription,
        "/tariffs/701": tariff,
        "/recommendedpayment/details": details,
    }

    def reply(request: httpx.Request) -> httpx.Response:
        endpoint = request.url.path.removeprefix("/api/rest/v1")
        reads.append(endpoint)
        assert request.method == "GET"
        if endpoint == "/recommendedpayment/details":
            assert json.loads(request.content) == {"agreement_id": 456, "start_period": DAY, "end_period": DAY}
        return httpx.Response(200, json={"code": 200, "response": payloads[endpoint]})

    config = step1_settings()
    admission = PreflightAdmission(PreflightPolicy(5, 0.1, 1, 0))
    client = LbxServerClient(config, transport=httpx.MockTransport(reply))
    try:
        async with admission.operation(bound_scope=False) as budget:
            proof = await read_subscription_proof(client, subject, config, budget=budget)
    finally:
        await client.aclose()
        await admission.aclose()

    assert paid_decision(proof) == expected
    assert reads.count("/recommendedpayment/details") == 1
