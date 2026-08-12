from __future__ import annotations

import os

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["CLOUDPAYMENTS_API_SECRET"] = ""
os.environ["CLOUDPAYMENTS_PUBLIC_ID"] = "pk_test_provider"
os.environ["SKIP_LEGAL_SEED"] = "true"

from fastapi.testclient import TestClient  # noqa: E402


def test_app_factory_builds_independent_apps_with_stable_routes() -> None:
    import app.main as main_module

    first_app = main_module.create_app()
    second_app = main_module.create_app()

    assert first_app is not second_app

    with TestClient(first_app) as client:
        for path in ("/health", "/health/live", "/health/ready", "/metrics"):
            assert client.get(path).status_code == 200

    openapi = first_app.openapi()
    assert openapi["paths"]["/health"]["get"]["tags"] == ["health"]
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
    assert preflight_response.headers["access-control-allow-origin"] == (
        "http://localhost:3000"
    )


def test_app_factory_preserves_configured_production_cors_contract() -> None:
    import app.main as main_module

    original_origins = main_module.settings.cors_allow_origins
    object.__setattr__(
        main_module.settings,
        "cors_allow_origins",
        ("https://payments.example.com",),
    )
    try:
        with TestClient(main_module.create_app()) as client:
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
    finally:
        object.__setattr__(
            main_module.settings,
            "cors_allow_origins",
            original_origins,
        )

    assert allowed_response.status_code == 200
    assert allowed_response.headers["access-control-allow-origin"] == (
        "https://payments.example.com"
    )
    assert rejected_response.status_code == 400
    assert "access-control-allow-origin" not in rejected_response.headers


def test_app_factory_runs_lifespan_once(monkeypatch) -> None:
    import app.main as main_module

    seed_calls = []
    monkeypatch.delenv("SKIP_LEGAL_SEED", raising=False)
    monkeypatch.setattr(
        main_module,
        "seed_legal_documents",
        lambda session: seed_calls.append(session),
    )

    with TestClient(main_module.create_app()) as client:
        assert client.get("/health/live").status_code == 200

    assert len(seed_calls) == 1
