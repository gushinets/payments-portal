"""SIMULATED preparation recordings share Step 2's actual account/offer."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from app.domains.catalog.commercial_offer import SelectedCommercialOffer
from app.infrastructure.preflight import PreflightAdmission
from app.integrations.lbx.client import API_PATH, LbxServerClient
from app.integrations.lbx.preparation_dto import NewServiceInfo, PostAgreement, PostSubscription, PostUser
from app.integrations.lbx.preparation_profile import PreparationProfile
from app.integrations.lbx.recorded_preparation import RecordedPreparationTransport
from app.integrations.lbx.selected_offer import read_selected_offer
from apps.api.tests.support.lbx import admission, lbx_settings


ROOT = Path(__file__).resolve().parents[4]
DIRECTORY = ROOT / "tools/purchase_mock"
USER_ID = 1501
AGREEMENT_ID = 1601
SUBSCRIPTION_ID = 1701
CUSTOMER_KEY = "SIMULATED-persisted-customer-key"


def preparation_profile() -> PreparationProfile:
    return PreparationProfile.model_validate_json((DIRECTORY / "preparation.json").read_bytes())


def user_command() -> PostUser:
    return PostUser(type=2, outer_id=CUSTOMER_KEY, email="customer@example.invalid")


def agreement_command() -> PostAgreement:
    return PostAgreement(
        user_id=USER_ID,
        organization_id=preparation_profile().organization_id,
        agreement_number="SIMULATED-held-purchase-reference",
        agreement_link="https://portal.example.invalid/terms/simulated",
        create_date=date(2026, 10, 16),
        is_offer=True,
        debt_threshold=Decimal(0),
    )


def subscription_command() -> PostSubscription:
    return PostSubscription(
        agreement_id=AGREEMENT_ID,
        tariff_id=701,
        period_id=901,
        subscription_start_date="2026-10-16 00:00:00",
        activate_by_balance=True,
        demo_period_length=0,
        activate_manually=False,
        outer_id="SIMULATED-subscription-hint",
        services=[NewServiceInfo(tariff_service_id=1001, multiplicator=2)],
    )


class PreparationRecording:
    source_mode = "SIMULATED"

    def __init__(self) -> None:
        self.profile = preparation_profile()
        self.base = RecordedPreparationTransport(DIRECTORY / "recordings", self.profile)
        self.requests: list[httpx.Request] = []
        self.overrides: dict[tuple[str, str], bytes] = {}
        self.post_status = 201
        self.post_fault: str | None = None
        self.post_response: bytes | None = None
        self.auth_status: int | None = None

    def change(self, name: str, edit: Callable[[Any], None]) -> None:
        body = json.loads((DIRECTORY / "recordings" / f"{name}.json").read_bytes())
        edit(body["response"])
        suffix = {
            "user": f"/users/{USER_ID}",
            "agreement": f"/agreements/{AGREEMENT_ID}",
            "subscription": f"/subscriptions/{SUBSCRIPTION_ID}",
            "users": "/users",
            "agreements": "/agreements",
            "subscriptions": "/subscriptions",
        }[name]
        self.overrides[("GET", suffix)] = json.dumps(body).encode()

    async def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        suffix = request.url.path.removeprefix(API_PATH)
        if suffix == "/auth" and self.auth_status is not None:
            return httpx.Response(self.auth_status)
        if request.method == "POST":
            if self.post_fault == "timeout":
                raise httpx.ReadTimeout("SIMULATED-private-remote-payload", request=request)
            if self.post_fault == "disconnect":
                raise httpx.RemoteProtocolError("SIMULATED-private-remote-payload", request=request)
            if self.post_fault is not None:
                return httpx.Response(int(self.post_fault), text="SIMULATED-private-remote-payload")
            response = await self.base.handle_async_request(request)
            return httpx.Response(
                self.post_status,
                content=self.post_response if self.post_response is not None else response.content,
                headers={"Content-Type": "application/json"},
            )
        body = self.overrides.get((request.method, suffix))
        if body is not None:
            return httpx.Response(200, content=body, headers={"Content-Type": "application/json"})
        return await self.base.handle_async_request(request)


@asynccontextmanager
async def preparation_source(
    recording: PreparationRecording, **overrides: Any
) -> AsyncIterator[tuple[LbxServerClient, PreflightAdmission]]:
    config = lbx_settings(
        lbx_base_url=recording.profile.server_origin,
        lbx_server_username=recording.profile.server_username,
        **overrides,
    )
    owner = admission(config)
    client = LbxServerClient(config, transport=httpx.MockTransport(recording.respond))
    try:
        yield client, owner
    finally:
        await owner.aclose()
        await client.aclose()


async def selected_offer(
    client: LbxServerClient, owner: PreflightAdmission, profile: PreparationProfile
) -> SelectedCommercialOffer:
    async with owner.operation() as budget:
        return await read_selected_offer(client, selection=profile.selection, inputs=profile.inputs, budget=budget)
