from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from apps.api.tests.support.settings import configure_api_test_environment
from apps.api.tests.support.settings import override_settings

configure_api_test_environment(APP_ENV="development")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def test_app_factory_builds_independent_apps_with_stable_routes() -> None:
    import app.main as main_module

    first_app = main_module.create_app()
    second_app = main_module.create_app()

    assert first_app is not second_app

    with TestClient(first_app) as client:
        for path in (
            "/api/health/live",
            "/api/health/ready",
            "/metrics",
        ):
            assert client.get(path).status_code == 200

    openapi = first_app.openapi()
    assert openapi["paths"]["/api/health/live"]["get"]["tags"] == ["health"]
    assert openapi["paths"]["/api/health/ready"]["get"]["tags"] == ["health"]
    assert {"/api/health/live", "/api/health/ready"} <= set(openapi["paths"])
    assert {"/health", "/health/live", "/health/ready"}.isdisjoint(openapi["paths"])
    assert "/metrics" not in openapi["paths"]


def test_app_factory_preserves_validation_and_development_cors_contract() -> None:
    import app.main as main_module

    with TestClient(main_module.create_app()) as client:
        validation_response = client.post("/api/auth/register", json={})
        preflight_response = client.options(
            "/api/auth/register",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert validation_response.status_code == 422
    assert isinstance(validation_response.json()["detail"], list)
    assert preflight_response.status_code == 200
    assert preflight_response.headers["access-control-allow-origin"] == ("http://localhost:3000")


def test_app_factory_preserves_configured_production_cors_contract() -> None:
    import app.main as main_module

    with (
        override_settings(
            main_module.settings,
            app_env=main_module.AppEnv.PRODUCTION,
            cors_allow_origins=("https://payments.example.com",),
        ),
        TestClient(main_module.create_app()) as client,
    ):
        allowed_response = client.options(
            "/api/auth/register",
            headers={
                "Origin": "https://payments.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        rejected_response = client.options(
            "/api/auth/register",
            headers={
                "Origin": "https://untrusted.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert allowed_response.status_code == 200
    assert allowed_response.headers["access-control-allow-origin"] == ("https://payments.example.com")
    assert rejected_response.status_code == 400
    assert "access-control-allow-origin" not in rejected_response.headers


def test_app_factory_uses_explicit_cors_origins_in_test_mode() -> None:
    import app.main as main_module

    with (
        override_settings(
            main_module.settings,
            app_env=main_module.AppEnv.TEST,
            cors_allow_origins=("https://test-web.example.com",),
        ),
        TestClient(main_module.create_app()) as client,
    ):
        explicit_response = client.options(
            "/api/auth/register",
            headers={
                "Origin": "https://test-web.example.com",
                "Access-Control-Request-Method": "POST",
            },
        )
        localhost_response = client.options(
            "/api/auth/register",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )

    assert explicit_response.status_code == 200
    assert explicit_response.headers["access-control-allow-origin"] == ("https://test-web.example.com")
    assert localhost_response.status_code == 400
    assert "access-control-allow-origin" not in localhost_response.headers


def test_app_factory_runs_lifespan_once(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.main as main_module

    lifecycle_events: list[str] = []
    session = object()
    session_context = MagicMock()
    monkeypatch.delenv("SKIP_LEGAL_SEED", raising=False)

    def assert_no_running_loop() -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        raise AssertionError("synchronous lifespan work must execute outside the event loop")

    def create_session() -> MagicMock:
        assert_no_running_loop()
        lifecycle_events.append("session_created")
        return session_context

    def enter_session() -> object:
        assert_no_running_loop()
        lifecycle_events.append("session_entered")
        return session

    def exit_session(
        exc_type: object,
        exc_value: object,
        traceback: object,
    ) -> None:
        assert_no_running_loop()
        lifecycle_events.append("session_closed")

    def seed_documents(received_session: object) -> None:
        assert_no_running_loop()
        assert received_session is session
        lifecycle_events.append("documents_seeded")

    session_context.__enter__.side_effect = enter_session
    session_context.__exit__.side_effect = exit_session
    monkeypatch.setattr(main_module, "SessionLocal", create_session)
    monkeypatch.setattr(main_module, "seed_legal_documents", seed_documents)

    app = main_module.create_app()

    with TestClient(app) as test_client:
        assert test_client.get("/api/health/live").status_code == 200

    assert lifecycle_events == [
        "session_created",
        "session_entered",
        "documents_seeded",
        "session_closed",
    ]
