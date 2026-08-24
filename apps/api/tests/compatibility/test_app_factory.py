from __future__ import annotations

from unittest.mock import Mock

from apps.api.tests.support.settings import configure_api_test_environment
from apps.api.tests.support.settings import override_settings

configure_api_test_environment(APP_ENV="development")

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


def test_app_factory_runs_lifespan_once(monkeypatch) -> None:
    import app.main as main_module

    seed_calls = []
    api_client = Mock()
    build_calls = []
    monkeypatch.delenv("SKIP_LEGAL_SEED", raising=False)

    def build_client(*, app_settings):
        build_calls.append(app_settings)
        return api_client

    monkeypatch.setattr(
        main_module,
        "build_cloudpayments_api_client",
        build_client,
    )
    monkeypatch.setattr(
        main_module,
        "seed_legal_documents",
        lambda session: seed_calls.append(session),
    )

    app = main_module.create_app()
    assert build_calls == []

    with TestClient(app) as test_client:
        assert test_client.get("/api/health/live").status_code == 200

    assert len(build_calls) == 1
    assert len(seed_calls) == 1
    api_client.close.assert_called_once_with()
