from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest
from pydantic import ValidationError

from app.composition.sources import source_resources
from app.domains.catalog.contracts import SourceProvenance
from app.integrations.kernel.client import KernelNotConfigured
from apps.api.tests.support.kernel import TOKEN, kernel_settings, manifest_fixture


pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def test_unconfigured_sources_initialize_no_client_or_outbound_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden_client(*args: Any, **kwargs: Any) -> None:
        pytest.fail("unconfigured local reads must not initialize an HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden_client)
    async with source_resources(kernel_settings(kernel_base_url="", kernel_service_token="")) as sources:
        assert sources.kernel is None
        assert sources.preflight.active_count == sources.preflight.waiting_count == 0
        with pytest.raises(KernelNotConfigured):
            sources.require_kernel()


async def test_startup_never_requests_manifest_and_shutdown_closes_owned_transport() -> None:
    class TrackingTransport(httpx.AsyncBaseTransport):
        requests = 0
        closed = False

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.requests += 1
            return httpx.Response(200, json=manifest_fixture())

        async def aclose(self) -> None:
            self.closed = True

    transport = TrackingTransport()
    async with source_resources(kernel_settings(), kernel_transport=transport) as sources:
        assert sources.kernel is not None
        assert transport.requests == 0
        owner = sources.preflight
        async with owner.operation() as budget:
            result = await sources.require_kernel().fetch_manifest(budget=budget)
        assert result.provenance is SourceProvenance.SIMULATED
        assert transport.requests == 1
    assert owner.closed
    assert transport.closed


async def test_lifespan_owns_one_resource_set_without_any_startup_http(monkeypatch: pytest.MonkeyPatch) -> None:
    from app import main

    monkeypatch.setenv("SKIP_LEGAL_SEED", "true")
    monkeypatch.setattr(main, "settings", kernel_settings())

    async def forbidden_send(*args: Any, **kwargs: Any) -> None:
        pytest.fail("startup must not request source data")

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_send)
    application = main.create_app()
    async with main.lifespan(application):
        sources = application.state.sources
        assert sources is application.state.sources
        assert sources.kernel is not None
        assert sources.preflight.active_count == 0
    assert sources.preflight.closed


async def test_real_local_http_route_runs_while_new_source_admission_is_saturated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app import main

    monkeypatch.setenv("SKIP_LEGAL_SEED", "true")
    monkeypatch.setattr(main, "settings", kernel_settings(preflight_max_active=1, preflight_max_waiting=0))
    application = main.create_app()
    async with main.lifespan(application):
        sources = application.state.sources
        async with sources.preflight.operation():
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=application), base_url="http://portal.test"
            ) as browser:
                response = await asyncio.wait_for(browser.get("/api/health/live"), timeout=0.5)
            assert response.status_code == 200
            assert response.json() == {"status": "alive"}
            assert sources.preflight.active_count == 1
            assert sources.preflight.waiting_count == 0


@pytest.mark.parametrize("url", ["http://local-counterpart.test", "https://future-compatible-counterpart.test"])
async def test_changing_url_does_not_promote_simulated_evidence(url: str) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=manifest_fixture())

    async with source_resources(
        kernel_settings(kernel_base_url=url), kernel_transport=httpx.MockTransport(respond)
    ) as sources:
        async with sources.preflight.operation() as budget:
            result = await sources.require_kernel().fetch_manifest(budget=budget)
        assert result.provenance is SourceProvenance.SIMULATED


@pytest.mark.parametrize(
    "overrides",
    [
        {"kernel_base_url": ""},
        {"kernel_service_token": ""},
        {"kernel_service_token": "bad\r\ntoken"},
        {"kernel_base_url": "ftp://kernel.test"},
        {"kernel_base_url": "http://user:password@kernel.test"},
        {"kernel_base_url": "http://kernel.test/other"},
        {"kernel_base_url": "http://kernel.test?secret=1"},
        {"kernel_base_url": "http://kernel.test/#fragment"},
        {"kernel_base_url": "http://kernel.test:bad"},
        {"preflight_total_timeout_seconds": float("inf")},
        {"preflight_total_timeout_seconds": float("nan")},
        {"preflight_total_timeout_seconds": 0.1, "preflight_cleanup_timeout_seconds": 0.2},
        {"preflight_max_active": 0},
        {"preflight_max_waiting": -1},
        {"kernel_max_response_bytes": 0},
        {"kernel_read_timeout_seconds": 0},
        {"kernel_max_retries": 3},
    ],
)
def test_invalid_configured_source_policy_is_rejected_without_secret_output(overrides: dict[str, Any]) -> None:
    with pytest.raises(ValidationError) as error:
        kernel_settings(**overrides)
    assert TOKEN not in str(error.value)


def test_production_basic_startup_allows_absent_source_but_forbids_provisional_source() -> None:
    production = {
        "app_env": "production",
        "app_public_base_url": "https://portal.example.test",
        "cors_allow_origins": ("https://portal.example.test",),
    }
    configuration = kernel_settings(**production, kernel_base_url="", kernel_service_token="")
    assert configuration.kernel_base_url == ""
    for url in ("http://kernel.test", "https://localhost", "https://kernel.example.test"):
        with pytest.raises(ValidationError):
            kernel_settings(**production, kernel_base_url=url)
