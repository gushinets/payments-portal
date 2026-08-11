from __future__ import annotations

import os
from collections import Counter

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

    route_counts = Counter(route.path for route in first_app.routes)
    for path in ("/health", "/health/live", "/health/ready", "/metrics"):
        assert route_counts[path] == 1

    openapi = first_app.openapi()
    assert openapi["paths"]["/health"]["get"]["tags"] == ["health"]
    assert "/metrics" not in openapi["paths"]


def test_app_factory_preserves_validation_and_cors_contract() -> None:
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
