from __future__ import annotations

import asyncio
import base64
import json
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.integrations.lbx.client import API_PATH, LbxServerClient
from app.integrations.lbx.errors import (
    LbxAuthenticationFailed,
    LbxClosed,
    LbxNotConfigured,
    LbxResponseInvalid,
    LbxScopeMismatch,
)
from apps.api.tests.support.lbx import (
    ACCOUNT,
    PASSWORD,
    SERVICE,
    TARIFF,
    TOKEN,
    USERNAME,
    fixture_response,
    lbx_settings,
    lbx_source,
    respond_with_fixture,
)


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_documented_selected_get_inventory_and_exact_source_values() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return respond_with_fixture(request)

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        assert requests == []
        async with owner.operation() as budget:
            tariffs = await client.list_tariffs(tariff_id=TARIFF, budget=budget)
            tariff = await client.get_tariff(tariff_id=TARIFF, budget=budget)
            periods = await client.list_tariff_periods(tariff_id=TARIFF, budget=budget)
            services = await client.list_tariff_services(tariff_id=TARIFF, budget=budget)
            prices = await client.list_service_prices(tariff_id=TARIFF, tariff_service_id=SERVICE, budget=budget)
        for result in (tariffs, tariff, periods, services, prices):
            assert result.external_billing_account_id == ACCOUNT
            assert result.tariff_id == TARIFF
            assert result.observed_at.utcoffset() is not None
        assert prices.tariff_service_id == SERVICE
        assert tariff.value.currency_id == 77  # Opaque, not an ISO currency/scale mapping.
        assert tariff.value.payment_type == 0
        assert periods.value[0].period_type == 3
        assert periods.value[0].period_length == 1
        assert prices.value[0].price == Decimal("0.1000000000000000000001")
        assert prices.value[0].connection_price == Decimal("0.00000001")
        assert prices.value[0].bulk_price == Decimal(0)
        assert prices.value[1].price == Decimal("9007199254740993.123456789012345678901")
        assert prices.value[0].start_date == date(2026, 10, 1)
        assert prices.value[0].next_change_date == date(2027, 1, 1)
        service = services.value[0]
        assert service.min_multiplicator == 1
        assert service.prices is not None
        assert service.prices[0].price_start_date == date(2026, 10, 1)
        assert service.discounts is not None and service.discounts[0].discounts is not None
        assert service.discounts[0].discounts[0].rate == Decimal("0.999999999999999999999")
        assert owner.active_count == owner.waiting_count == 0
    assert [request.url.path for request in requests] == [
        API_PATH + "/auth",
        API_PATH + "/tariffs",
        API_PATH + f"/tariffs/{TARIFF}",
        API_PATH + f"/tariffs/{TARIFF}/periods",
        API_PATH + f"/tariffs/{TARIFF}/services",
        API_PATH + f"/tariffs/{TARIFF}/services/{SERVICE}/prices",
    ]
    basic = base64.b64encode(f"{USERNAME}:{PASSWORD}".encode()).decode()
    assert requests[0].headers["authorization"] == f"Basic {basic}"
    assert json.loads(requests[1].content) == {"tariff_id": TARIFF}
    for request in requests:
        assert request.method == "GET"
        assert request.url.host == "lbx-client.test"
        assert request.url.query == b""
        assert "origin" not in request.headers
        assert request.extensions["timeout"] == {"connect": 1.0, "read": 2.0, "write": 1.0, "pool": 1.0}
    assert all(request.headers["authorization"] == f"Bearer {TOKEN}" for request in requests[1:])


async def test_shared_token_refresh_is_serialized_but_gets_are_not() -> None:
    entered = asyncio.Event()
    release = asyncio.Event()
    auth_count = 0
    get_count = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal auth_count, get_count
        if request.url.path.endswith("/auth"):
            auth_count += 1
            entered.set()
            await release.wait()
        else:
            get_count += 1
        return respond_with_fixture(request)

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):

        async def read() -> None:
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)

        tasks = [asyncio.create_task(read()) for _ in range(3)]
        try:
            await asyncio.wait_for(entered.wait(), timeout=1)
            await asyncio.sleep(0)
            assert auth_count == 1
        finally:
            release.set()
            await asyncio.gather(*tasks)
        assert auth_count == 1 and get_count == 3


async def test_expiry_uses_returned_lifetime_not_an_assumed_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.lbx import client as module

    now = [1000.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    auth_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal auth_count
        if request.url.path.endswith("/auth"):
            auth_count += 1
            return httpx.Response(200, json={"code": 200, "response": {"token": TOKEN, "expires_in": 7}})
        return respond_with_fixture(request)

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        for instant in (1000.0, 1006.0, 1007.0):
            now[0] = instant
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)
        assert auth_count == 2


async def test_expiry_between_transient_gets_does_not_allow_repeated_reauth(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.lbx import client as module

    now = [1000.0]
    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    auth_count = 0
    get_count = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal auth_count, get_count
        if request.url.path.endswith("/auth"):
            auth_count += 1
            return httpx.Response(
                200, json={"code": 200, "response": {"token": f"{TOKEN}-{auth_count}", "expires_in": 1}}
            )
        get_count += 1
        now[0] += 2
        return httpx.Response(503)

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        with pytest.raises(LbxAuthenticationFailed):
            async with owner.operation() as budget:
                await client.get_tariff(tariff_id=TARIFF, budget=budget)
    assert auth_count == get_count == 2


async def test_missing_commercial_fields_stay_unknown_without_synthesized_defaults() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        return httpx.Response(200, json={"code": 200, "response": {"tariff_id": TARIFF}})

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        async with owner.operation() as budget:
            result = await client.get_tariff(tariff_id=TARIFF, budget=budget)
        assert result.value.currency_id is None
        assert result.value.payment_type is None
        assert result.value.balance_blocks is None
        assert result.value.demo_period_length is None
        assert result.value.model_fields_set == {"tariff_id"}


@pytest.mark.parametrize("tariff_id", [True, 1.0, "701", 0, -1])
async def test_invalid_selected_id_makes_no_http_request(tariff_id: Any) -> None:
    def forbidden(request: httpx.Request) -> httpx.Response:
        pytest.fail("invalid selected identity must fail before any HTTP")

    async with lbx_source(httpx.MockTransport(forbidden)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(LbxScopeMismatch):
                await client.get_tariff(tariff_id=tariff_id, budget=budget)


@pytest.mark.parametrize("suffix", ["/tariffs", f"/tariffs/{TARIFF}", f"/tariffs/{TARIFF}/services"])
async def test_wrong_tariff_scope_is_refused(suffix: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        item = {"tariff_id": 999, "tariff_service_id": SERVICE} if suffix.endswith("services") else {"tariff_id": 999}
        return httpx.Response(200, json={"code": 200, "response": item if suffix.endswith(str(TARIFF)) else [item]})

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(LbxScopeMismatch):
                if suffix == "/tariffs":
                    await client.list_tariffs(tariff_id=TARIFF, budget=budget)
                elif suffix.endswith("services"):
                    await client.list_tariff_services(tariff_id=TARIFF, budget=budget)
                else:
                    await client.get_tariff(tariff_id=TARIFF, budget=budget)


@pytest.mark.parametrize("fixture", ["periods", "services", "prices"])
async def test_duplicate_source_identity_is_refused(fixture: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return fixture_response("auth")
        items = {
            "periods": {"tariff_period_id": 801, "period_id": 901},
            "services": {"tariff_id": TARIFF, "tariff_service_id": SERVICE},
            "prices": {"price_id": 1301, "period_id": 901},
        }
        return httpx.Response(200, json={"code": 200, "response": [items[fixture], items[fixture]]})

    async with lbx_source(httpx.MockTransport(respond)) as (client, owner):
        async with owner.operation() as budget:
            with pytest.raises(LbxResponseInvalid):
                if fixture == "periods":
                    await client.list_tariff_periods(tariff_id=TARIFF, budget=budget)
                elif fixture == "services":
                    await client.list_tariff_services(tariff_id=TARIFF, budget=budget)
                else:
                    await client.list_service_prices(tariff_id=TARIFF, tariff_service_id=SERVICE, budget=budget)


@pytest.mark.parametrize(
    "overrides",
    [
        {"lbx_base_url": ""},
        {"lbx_external_billing_account_id": ""},
        {"lbx_server_username": ""},
        {"lbx_server_password": ""},
        {"lbx_base_url": "http://name:secret@lbx.test"},
        {"lbx_base_url": "https://lbx.test/api/rest/v1"},
        {"lbx_base_url": "https://lbx.test?token=secret"},
        {"lbx_base_url": "https://lbx.test/#fragment"},
        {"lbx_base_url": "https://lbx.test:bad"},
        {"lbx_base_url": "ftp://lbx.test"},
        {"lbx_server_username": "bad:username"},
        {"lbx_server_password": "bad\r\npassword"},
        {"lbx_external_billing_account_id": "wrong account"},
        {"lbx_read_timeout_seconds": float("nan")},
        {"lbx_connect_timeout_seconds": 0},
        {"lbx_max_response_bytes": 0},
        {"lbx_max_get_attempts": 9},
        {"lbx_max_retry_delay_seconds": float("inf")},
    ],
)
def test_invalid_configuration_is_safe(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as error:
        lbx_settings(**overrides)
    assert PASSWORD not in str(error.value)
    assert USERNAME not in str(error.value)


def test_configuration_is_optional_and_no_client_is_required_for_startup() -> None:
    configuration = lbx_settings(
        lbx_base_url="", lbx_external_billing_account_id="", lbx_server_username="", lbx_server_password=""
    )
    with pytest.raises(LbxNotConfigured):
        LbxServerClient(configuration)
    assert PASSWORD not in repr(lbx_settings())


@pytest.mark.parametrize("url", ["http://lbx.example.test", "https://localhost"])
def test_production_requires_normal_public_tls_origin(url: str) -> None:
    with pytest.raises(ValidationError):
        lbx_settings(
            app_env="production",
            app_public_base_url="https://portal.example.test",
            cors_allow_origins=("https://portal.example.test",),
            lbx_base_url=url,
        )


def test_production_accepts_explicit_scoped_lbx_configuration_without_enabling_sales() -> None:
    configuration = lbx_settings(
        app_env="production",
        app_public_base_url="https://portal.example.test",
        cors_allow_origins=("https://portal.example.test",),
        lbx_base_url="https://billing.example.test",
    )
    assert configuration.lbx_external_billing_account_id == ACCOUNT
    assert configuration.kernel_base_url == ""


async def test_close_owns_transport_and_closed_client_refuses_new_work() -> None:
    class Transport(httpx.MockTransport):
        closed = False

        async def aclose(self) -> None:
            self.closed = True

    transport = Transport(respond_with_fixture)
    async with lbx_source(transport) as (client, owner):
        async with owner.operation() as budget:
            pass
    assert transport.closed
    # No admission or source HTTP is started by a closed client.
    with pytest.raises(LbxClosed):
        await client.get_tariff(tariff_id=TARIFF, budget=budget)
    assert owner.closed
