from __future__ import annotations

import asyncio
from unittest.mock import Mock

import httpx

from apps.api.tests.support.settings import configure_api_test_environment

configure_api_test_environment()

import pytest  # noqa: E402

from app.integrations.cloudpayments import adapter as cloudpayments_adapter_module  # noqa: E402
from app.integrations.cloudpayments import api_client as cloudpayments_api_client_module  # noqa: E402
from app.payment_providers.registry import PaymentProviderRegistry  # noqa: E402


def test_normal_app_composes_an_empty_payment_provider_registry() -> None:
    import app.main as main_module

    app = main_module.create_app()

    assert isinstance(app.state.payment_provider_registry, PaymentProviderRegistry)
    assert app.state.payment_provider_registry.sole_adapter() is None
    with pytest.raises(LookupError, match="payment_provider_not_registered:cloudpayments"):
        app.state.payment_provider_registry.get("cloudpayments")
    assert not hasattr(app.state, "cloudpayments_adapter")


def test_normal_app_lifespan_does_not_initialize_cloudpayments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.main as main_module

    assert not hasattr(main_module, "CloudPaymentsAdapter")
    assert not hasattr(main_module, "build_cloudpayments_api_client")
    assert not hasattr(main_module, "cloudpayments_router")

    adapter_constructor = Mock(side_effect=AssertionError("CloudPayments adapter was initialized"))
    client_builder = Mock(side_effect=AssertionError("CloudPayments API client was initialized"))
    monkeypatch.setattr(cloudpayments_adapter_module, "CloudPaymentsAdapter", adapter_constructor)
    monkeypatch.setattr(cloudpayments_api_client_module, "build_cloudpayments_api_client", client_builder)

    app = main_module.create_app()

    async def exercise_lifespan() -> None:
        async with main_module.lifespan(app):
            assert not hasattr(app.state, "cloudpayments_adapter")

    asyncio.run(exercise_lifespan())

    adapter_constructor.assert_not_called()
    client_builder.assert_not_called()


def test_normal_app_has_no_cloudpayments_http_surface() -> None:
    import app.main as main_module

    app = main_module.create_app()
    cloudpayments_paths = {
        path for route in app.routes if (path := getattr(route, "path", "")).startswith("/api/cloudpayments")
    }

    assert cloudpayments_paths == set()
    assert all(not path.startswith("/api/cloudpayments") for path in app.openapi()["paths"])

    async def assert_callbacks_are_absent() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            for endpoint in ("check", "pay", "anything"):
                response = await client.post(f"/api/cloudpayments/{endpoint}", json={})
                assert response.status_code == 404
                assert response.json() == {"detail": "Not Found"}

    asyncio.run(assert_callbacks_are_absent())
