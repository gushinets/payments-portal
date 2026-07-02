from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["CLOUDPAYMENTS_API_SECRET"] = ""

api_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(api_root))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import PaymentWebhookEvent  # noqa: E402


client = TestClient(app)


def setup_function() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def test_healthcheck() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_demo_auth_flow() -> None:
    login_response = client.post(
        "/api/auth/request-login",
        json={"email": "user@example.com", "product": "jobact", "region": "ru"},
    )

    assert login_response.status_code == 200
    login_payload = login_response.json()
    assert login_payload["status"] == "demo_link_generated"
    assert login_payload["demo_token"]

    verify_response = client.post(
        "/api/auth/verify",
        json={"email": "user@example.com", "token": login_payload["demo_token"]},
    )

    assert verify_response.status_code == 200
    assert verify_response.json()["email_verified"] is True


def test_cloudpayments_webhook_is_saved_without_secret_hmac() -> None:
    response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": "invoice-1",
            "TransactionId": "tx-1",
            "AccountId": "user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}

    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.provider == "cloudpayments"
    assert event.endpoint == "pay"
    assert event.invoice_id == "invoice-1"
    assert event.transaction_id == "tx-1"
    assert event.account_id == "user@example.com"
    assert str(event.amount) == "990.00"
    assert event.currency == "RUB"
    assert event.status == "received"


def test_cloudpayments_webhook_rejects_invalid_signature_when_secret_is_set() -> None:
    os.environ["CLOUDPAYMENTS_API_SECRET"] = "test-secret"
    app.dependency_overrides.clear()

    from app.settings import settings  # noqa: E402

    object.__setattr__(settings, "cloudpayments_api_secret", "test-secret")

    response = client.post(
        "/api/cloudpayments/pay",
        headers={"Content-HMAC": "invalid-signature"},
        json={
            "InvoiceId": "invoice-2",
            "TransactionId": "tx-2",
            "AccountId": "user@example.com",
            "Amount": "1490.00",
            "Currency": "RUB",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_cloudpayments_signature"

    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.status == "error"
    assert event.error_message == "invalid_cloudpayments_signature"

    object.__setattr__(settings, "cloudpayments_api_secret", "")
    os.environ["CLOUDPAYMENTS_API_SECRET"] = ""
