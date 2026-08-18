from __future__ import annotations

from apps.api.tests.support.settings import configure_api_test_environment

configure_api_test_environment()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.exc import OperationalError  # noqa: E402

import app.core.database as database_module  # noqa: E402
from app.main import app  # noqa: E402


client = TestClient(app)


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
