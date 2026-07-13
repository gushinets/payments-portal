from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


TEST_DATABASE_URL = os.getenv("TEST_POSTGRES_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="set TEST_POSTGRES_DATABASE_URL to run PostgreSQL webhook integration tests",
)

os.environ.setdefault("DATABASE_URL", TEST_DATABASE_URL or "sqlite+pysqlite:///:memory:")
os.environ["CLOUDPAYMENTS_API_SECRET"] = ""
os.environ["SKIP_LEGAL_SEED"] = "true"

api_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(api_root))

from app.core.database import Base, get_db  # noqa: E402
from app.integrations.cloudpayments import processing as cloudpayments_processing  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Order,
    Payment,
    PaymentProviderAccount,
    PaymentWebhookEvent,
    Region,
    User,
)


engine = create_engine(TEST_DATABASE_URL, future=True) if TEST_DATABASE_URL else None
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def reset_schema() -> None:
    assert engine is not None
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_order(invoice_id: str) -> None:
    now = datetime.now(timezone.utc)
    with TestingSessionLocal() as db:
        db.add(
            Region(
                code="ru",
                name="Russia",
                residency_zone="ru",
                default_currency="RUB",
                default_locale="ru-RU",
            )
        )
        user = User(
            tenant_id="anytoolai",
            region="ru",
            email="durable-webhook@example.com",
            email_normalized="durable-webhook@example.com",
            status="active",
            metadata_={},
        )
        db.add(user)
        db.flush()
        provider_account = PaymentProviderAccount(
            tenant_id="anytoolai",
            region="ru",
            provider="cloudpayments",
            public_identifier="pk_test",
            default_currency="RUB",
            enabled=True,
            test_mode=True,
            config={},
        )
        db.add(provider_account)
        db.flush()
        db.add(
            Order(
                tenant_id="anytoolai",
                region="ru",
                order_number="RU-TEST-0001",
                user_id=user.id,
                status="pending_payment",
                amount_minor=99000,
                currency="RUB",
                provider="cloudpayments",
                provider_account_id=provider_account.id,
                merchant_order_id=invoice_id,
                provider_invoice_id=invoice_id,
                expires_at=now + timedelta(minutes=30),
                metadata_={},
            )
        )
        db.commit()


def test_raw_webhook_event_survives_failed_normalization_and_can_retry(monkeypatch) -> None:
    reset_schema()
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-durable-1"
    seed_order(invoice_id)

    original_upsert = cloudpayments_processing.upsert_payment_from_webhook

    def raising_upsert(*args, **kwargs):
        original_upsert(*args, **kwargs)
        raise RuntimeError("forced normalization error with card 4111111111111111")

    monkeypatch.setattr(cloudpayments_processing, "upsert_payment_from_webhook", raising_upsert)

    payload = {
        "InvoiceId": invoice_id,
        "TransactionId": "tx-durable-1",
        "AccountId": "durable-webhook@example.com",
        "Amount": "990.00",
        "Currency": "RUB",
        "CardFirstSix": "411111",
    }
    failed_response = client.post(
        "/api/cloudpayments/pay",
        headers={"Content-HMAC": "demo-secret-header"},
        json=payload,
    )

    assert failed_response.status_code == 500
    with TestingSessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()
        order = db.query(Order).one()
        payment_count = db.query(Payment).count()

    assert event.status == "failed"
    assert event.error_code == "normalization_unexpected_error"
    assert "RuntimeError" in event.error_message
    assert "411111" not in event.error_message
    assert event.processed_at
    assert event.raw_payload["CardFirstSix"] == "[redacted]"
    assert event.headers["content-hmac"] == "[redacted]"
    assert order.status == "pending_payment"
    assert payment_count == 0

    monkeypatch.setattr(cloudpayments_processing, "upsert_payment_from_webhook", original_upsert)
    retry_response = client.post("/api/cloudpayments/pay", json=payload)

    assert retry_response.status_code == 200
    with TestingSessionLocal() as db:
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        order = db.query(Order).one()
        payments = db.query(Payment).all()

    assert [event.status for event in events] == ["failed", "processed"]
    assert order.status == "paid"
    assert len(payments) == 1
    assert payments[0].provider_payment_id == "tx-durable-1"

    app.dependency_overrides.clear()
