from __future__ import annotations

import pytest
from sqlalchemy.exc import OperationalError

import app.core.database as database_module
from apps.api.tests.support.api import app, client, reset_api_database


def setup_function() -> None:
    reset_api_database()


def test_liveness_readiness_metrics_and_request_id() -> None:
    request_id = "agent-check-123"
    canonical_live_response = client.get(
        "/api/health/live",
        headers={"X-Request-ID": request_id},
    )
    canonical_ready_response = client.get("/api/health/ready")
    metrics_response = client.get("/metrics")

    assert canonical_live_response.status_code == 200
    assert canonical_live_response.headers["X-Request-ID"] == request_id
    assert canonical_live_response.json() == {"status": "alive"}
    assert canonical_ready_response.status_code == 200
    assert canonical_ready_response.json() == {"status": "ready"}
    assert canonical_ready_response.headers["X-Request-ID"]
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain")


def test_legacy_billing_contracts_are_not_mounted_or_documented() -> None:
    removed_contracts = (
        ("get", "/api/catalog/products"),
        ("post", "/api/auth/checkout-intent"),
        ("get", "/api/account/subscriptions"),
        ("get", "/api/account/subscriptions/00000000-0000-0000-0000-000000000001"),
        ("get", "/api/auth/payment-status"),
    )

    for method, path in removed_contracts:
        response = client.request(method, path)
        assert response.status_code == 404

    openapi_paths = app.openapi()["paths"]
    assert "/api/catalog/products" not in openapi_paths
    assert "/api/auth/checkout-intent" not in openapi_paths
    assert "/api/account/subscriptions" not in openapi_paths
    assert "/api/account/subscriptions/{subscription_id}" not in openapi_paths
    assert "/api/auth/payment-status" not in openapi_paths


def test_invalid_request_id_is_replaced() -> None:
    response = client.get(
        "/api/health/live",
        headers={"X-Request-ID": "invalid request id"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "invalid request id"
    assert len(response.headers["X-Request-ID"]) == 32


class FailingSession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, statement):
        raise OperationalError(
            "SELECT 1",
            {},
            RuntimeError("postgresql://internal:secret@database/payments"),
        )


def test_canonical_health_contract() -> None:
    live_response = client.get(
        "/api/health/live",
        headers={"X-Request-ID": "canonical-live"},
    )
    ready_response = client.get("/api/health/ready")

    assert live_response.status_code == 200
    assert live_response.json() == {"status": "alive"}
    assert live_response.headers["X-Request-ID"] == "canonical-live"
    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ready"}
    assert ready_response.headers["X-Request-ID"]


def test_liveness_does_not_use_database(monkeypatch) -> None:
    monkeypatch.setattr(database_module, "SessionLocal", FailingSession)

    response = client.get("/api/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_database_failure_is_safe(monkeypatch) -> None:
    monkeypatch.setattr(database_module, "SessionLocal", FailingSession)

    response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready"}
    assert "postgresql" not in response.text
    assert "secret" not in response.text


@pytest.mark.parametrize("path", ["/health", "/health/live", "/health/ready"])
def test_legacy_health_routes_are_not_registered(path: str) -> None:
    assert client.get(path).status_code == 404
