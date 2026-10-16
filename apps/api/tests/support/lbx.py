"""Explicitly SIMULATED, isolated HTTP inputs; never used by Portal runtime."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx

from app.core.settings import Settings
from app.infrastructure.preflight import PreflightAdmission, PreflightPolicy
from app.integrations.lbx.client import API_PATH, LbxServerClient
from apps.api.tests.support.settings import DEFAULT_API_TEST_ENV


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/lbx"
USERNAME = "simulated-lbx-server-user"
PASSWORD = "simulated-lbx-server-password"
TOKEN = "simulated-lbx-session-token"
ACCOUNT = "simulated-ru-lbx-account"
TARIFF = 701
SERVICE = 1001


def lbx_settings(**overrides: Any) -> Settings:
    values = {name.lower(): value for name, value in DEFAULT_API_TEST_ENV.items()}
    values.update(
        kernel_base_url="",
        kernel_service_token="",
        lbx_base_url="https://lbx-client.test",
        lbx_external_billing_account_id=ACCOUNT,
        lbx_server_username=USERNAME,
        lbx_server_password=PASSWORD,
        lbx_retry_delay_seconds=0,
    )
    values.update(overrides)
    return Settings(_env_file=None, **values)


def fixture_response(name: str) -> httpx.Response:
    return httpx.Response(
        200, content=(FIXTURES / f"{name}.json").read_bytes(), headers={"Content-Type": "application/json"}
    )


def respond_with_fixture(request: httpx.Request) -> httpx.Response:
    suffix = request.url.path.removeprefix(API_PATH)
    names = {
        "/auth": "auth",
        "/tariffs": "tariffs",
        f"/tariffs/{TARIFF}": "tariff",
        f"/tariffs/{TARIFF}/periods": "periods",
        f"/tariffs/{TARIFF}/services": "services",
        f"/tariffs/{TARIFF}/services/{SERVICE}/prices": "prices",
    }
    return fixture_response(names[suffix])


def admission(configuration: Settings) -> PreflightAdmission:
    return PreflightAdmission(
        PreflightPolicy(
            total_timeout_seconds=configuration.preflight_total_timeout_seconds,
            cleanup_timeout_seconds=configuration.preflight_cleanup_timeout_seconds,
            max_active=configuration.preflight_max_active,
            max_waiting=configuration.preflight_max_waiting,
        )
    )


@asynccontextmanager
async def lbx_source(
    transport: httpx.AsyncBaseTransport, **overrides: Any
) -> AsyncIterator[tuple[LbxServerClient, PreflightAdmission]]:
    config = lbx_settings(**overrides)
    owner = admission(config)
    client = LbxServerClient(config, transport=transport)
    try:
        yield client, owner
    finally:
        await owner.aclose()
        await client.aclose()
