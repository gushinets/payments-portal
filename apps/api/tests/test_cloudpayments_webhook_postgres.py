from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
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
from app.integrations.cloudpayments import adapter as cloudpayments_adapter_module  # noqa: E402
from app.integrations.cloudpayments.adapter import verify_cloudpayments_signature  # noqa: E402
from app.integrations.cloudpayments import processing as cloudpayments_processing  # noqa: E402
from app.core.settings import settings  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Order,
    Payment,
    PaymentProviderAccount,
    PaymentWebhookEvent,
    Refund,
    Region,
    User,
)


engine = create_engine(TEST_DATABASE_URL, future=True) if TEST_DATABASE_URL else None
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
_original_verify_cloudpayments_signature = verify_cloudpayments_signature


def _verified_webhook_for_test(raw_body: bytes, headers: dict[str, str]) -> bool:
    return True


def cloudpayments_signature(raw_body: bytes, secret: str = "test-secret") -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    ).decode("ascii")


def allow_unsigned_cloudpayments_webhooks_for_test() -> None:
    cloudpayments_adapter_module.verify_cloudpayments_signature = _verified_webhook_for_test


def require_signed_cloudpayments_webhooks_for_test() -> None:
    cloudpayments_adapter_module.verify_cloudpayments_signature = (
        _original_verify_cloudpayments_signature
    )


def reset_schema() -> None:
    assert engine is not None
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    Base.metadata.create_all(engine)


def clear_schema() -> None:
    assert engine is not None
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))


@pytest.fixture(autouse=True)
def clean_schema_after_test():
    allow_unsigned_cloudpayments_webhooks_for_test()
    yield
    if engine is not None:
        clear_schema()
    app.dependency_overrides.clear()


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


def seed_order(invoice_id: str, *, widget_mode: str = "charge") -> None:
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
            config={"widget_mode": widget_mode},
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
                metadata_={"payment_mode": widget_mode},
            )
        )
        db.commit()


def paid_payload(invoice_id: str, transaction_id: str) -> dict[str, str]:
    return {
        "InvoiceId": invoice_id,
        "TransactionId": transaction_id,
        "AccountId": "durable-webhook@example.com",
        "Amount": "990.00",
        "Currency": "RUB",
        "Status": "Completed",
    }


def authorized_payload(invoice_id: str, transaction_id: str) -> dict[str, str]:
    return {
        **paid_payload(invoice_id, transaction_id),
        "Status": "Authorized",
    }


def cancel_payload(invoice_id: str, transaction_id: str) -> dict[str, str]:
    return {
        "InvoiceId": invoice_id,
        "TransactionId": transaction_id,
        "Amount": "990.00",
    }


def refund_payload(
    invoice_id: str,
    *,
    refund_transaction_id: str,
    payment_transaction_id: str,
    amount: str,
) -> dict[str, str]:
    return {
        "InvoiceId": invoice_id,
        "TransactionId": refund_transaction_id,
        "PaymentTransactionId": payment_transaction_id,
        "AccountId": "durable-webhook@example.com",
        "Amount": amount,
    }


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
        "Status": "Completed",
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


def test_concurrent_duplicate_webhook_is_serialized_without_provider_payment_id(monkeypatch) -> None:
    reset_schema()
    app.dependency_overrides[get_db] = override_get_db
    invoice_id = "inv-concurrent-1"
    seed_order(invoice_id)

    original_upsert = cloudpayments_processing.upsert_payment_from_webhook
    first_upsert_entered = threading.Event()
    call_lock = threading.Lock()
    call_count = 0

    def slow_first_upsert(*args, **kwargs):
        nonlocal call_count
        with call_lock:
            call_count += 1
            is_first_call = call_count == 1
        if is_first_call:
            first_upsert_entered.set()
            time.sleep(0.3)
        return original_upsert(*args, **kwargs)

    monkeypatch.setattr(
        cloudpayments_processing,
        "upsert_payment_from_webhook",
        slow_first_upsert,
    )

    payload = {
        "InvoiceId": invoice_id,
        "AccountId": "durable-webhook@example.com",
        "Amount": "990.00",
        "Currency": "RUB",
        "Status": "Completed",
    }

    def post_webhook():
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.post("/api/cloudpayments/pay", json=payload)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_result = executor.submit(post_webhook)
            assert first_upsert_entered.wait(timeout=5)
            second_result = executor.submit(post_webhook)

            first_response = first_result.result(timeout=10)
            second_response = second_result.result(timeout=10)

        assert first_response.status_code == 200
        assert second_response.status_code == 200

        with TestingSessionLocal() as db:
            events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
            order = db.query(Order).one()
            payments = db.query(Payment).all()

        assert sorted(event.status for event in events) == ["duplicate", "processed"]
        processed_event = next(event for event in events if event.status == "processed")
        duplicate_event = next(event for event in events if event.status == "duplicate")
        assert duplicate_event.payment_id == processed_event.payment_id
        assert order.status == "paid"
        assert len(payments) == 1
        assert payments[0].provider_payment_id is None
    finally:
        app.dependency_overrides.clear()


def test_signed_duplicate_webhook_is_persisted_once_and_acknowledged_idempotently(monkeypatch) -> None:
    reset_schema()
    app.dependency_overrides[get_db] = override_get_db
    require_signed_cloudpayments_webhooks_for_test()
    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", "test-secret")
    invoice_id = "inv-signed-duplicate-1"
    seed_order(invoice_id)

    raw_payload = (
        b'{"InvoiceId":"inv-signed-duplicate-1","TransactionId":"tx-signed-duplicate-1",'
        b'"AccountId":"durable-webhook@example.com","Amount":"990.00",'
        b'"Currency":"RUB","Status":"Completed"}'
    )
    headers = {
        "Content-HMAC": cloudpayments_signature(raw_payload),
        "Content-Type": "application/json",
    }

    def post_webhook():
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.post(
                "/api/cloudpayments/pay",
                headers=headers,
                content=raw_payload,
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_result = executor.submit(post_webhook)
            second_result = executor.submit(post_webhook)
            first_response = first_result.result(timeout=10)
            second_response = second_result.result(timeout=10)

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert first_response.json() == {"code": 0}
        assert second_response.json() == {"code": 0}

        with TestingSessionLocal() as db:
            events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
            payments = db.query(Payment).all()
            order = db.query(Order).one()

        assert sorted(event.status for event in events) == ["duplicate", "processed"]
        assert len(payments) == 1
        assert payments[0].provider_payment_id == "tx-signed-duplicate-1"
        assert order.status == "paid"
    finally:
        object.__setattr__(settings, "cloudpayments_enabled", False)
        object.__setattr__(settings, "cloudpayments_api_secret", "")
        app.dependency_overrides.clear()


def test_cancel_after_paid_payment_is_ignored_without_state_regression() -> None:
    reset_schema()
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-cancel-after-paid-1"
    transaction_id = "tx-paid-before-cancel-1"
    seed_order(invoice_id, widget_mode="auth")

    authorized_response = client.post(
        "/api/cloudpayments/pay",
        json=authorized_payload(invoice_id, transaction_id),
    )
    confirm_response = client.post(
        "/api/cloudpayments/confirm",
        json=paid_payload(invoice_id, transaction_id),
    )
    cancel_response = client.post(
        "/api/cloudpayments/cancel",
        json=cancel_payload(invoice_id, transaction_id),
    )

    assert authorized_response.status_code == 200
    assert confirm_response.status_code == 200
    assert cancel_response.status_code == 200
    assert cancel_response.json() == {"code": 0}
    with TestingSessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status == "paid"
    assert order.canceled_at is None
    assert payment.status == "succeeded"
    assert payment.refunded_amount_minor == 0
    assert [event.status for event in events] == ["processed", "processed", "ignored"]
    assert events[-1].payment_id == payment.id
    assert events[-1].error_code == "order_already_paid"


def test_cancel_after_refunded_payment_is_ignored_without_refund_mutation() -> None:
    reset_schema()
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-cancel-after-refund-1"
    transaction_id = "tx-refunded-before-cancel-1"
    seed_order(invoice_id, widget_mode="auth")

    authorized_response = client.post(
        "/api/cloudpayments/pay",
        json=authorized_payload(invoice_id, transaction_id),
    )
    confirm_response = client.post(
        "/api/cloudpayments/confirm",
        json=paid_payload(invoice_id, transaction_id),
    )
    refund_response = client.post(
        "/api/cloudpayments/refund",
        json=refund_payload(
            invoice_id,
            refund_transaction_id="tx-refund-before-cancel-1",
            payment_transaction_id=transaction_id,
            amount="990.00",
        ),
    )
    cancel_response = client.post(
        "/api/cloudpayments/cancel",
        json=cancel_payload(invoice_id, transaction_id),
    )

    assert authorized_response.status_code == 200
    assert confirm_response.status_code == 200
    assert refund_response.status_code == 200
    assert cancel_response.status_code == 200
    assert cancel_response.json() == {"code": 0}
    with TestingSessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        refunds = db.query(Refund).all()

    assert order.status == "refunded"
    assert payment.status == "refunded"
    assert payment.refunded_amount_minor == 99000
    assert len(refunds) == 1
    assert [event.status for event in events] == ["processed", "processed", "processed", "ignored"]
    assert events[-1].payment_id == payment.id
    assert events[-1].error_code == "order_already_refunded"


def test_refund_after_canceled_payment_is_rejected_without_refund_mutation() -> None:
    reset_schema()
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-refund-after-cancel-1"
    transaction_id = "tx-canceled-before-refund-1"
    seed_order(invoice_id, widget_mode="auth")

    pay_response = client.post(
        "/api/cloudpayments/pay",
        json=authorized_payload(invoice_id, transaction_id),
    )
    cancel_response = client.post(
        "/api/cloudpayments/cancel",
        json=cancel_payload(invoice_id, transaction_id),
    )
    refund_response = client.post(
        "/api/cloudpayments/refund",
        json=refund_payload(
            invoice_id,
            refund_transaction_id="tx-refund-after-cancel-1",
            payment_transaction_id=transaction_id,
            amount="100.00",
        ),
    )

    assert pay_response.status_code == 200
    assert cancel_response.status_code == 200
    assert refund_response.status_code == 200
    assert refund_response.json() == {"code": 13}
    with TestingSessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        refund_count = db.query(Refund).count()

    assert order.status == "canceled"
    assert payment.status == "canceled"
    assert payment.refunded_amount_minor == 0
    assert refund_count == 0
    assert [event.status for event in events] == ["processed", "processed", "failed"]
    assert events[-1].payment_id == payment.id
    assert events[-1].error_code == "order_already_canceled"


def test_completed_pay_after_auth_cancel_is_rejected_and_cannot_be_refunded() -> None:
    reset_schema()
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-late-charge-refund-pg-1"
    seed_order(invoice_id, widget_mode="auth")

    cancel_response = client.post(
        "/api/cloudpayments/cancel",
        json=cancel_payload(invoice_id, "tx-canceled-attempt-pg-1"),
    )
    late_pay_response = client.post(
        "/api/cloudpayments/pay",
        json=paid_payload(invoice_id, "tx-late-distinct-charge-pg-1"),
    )
    refund_response = client.post(
        "/api/cloudpayments/refund",
        json=refund_payload(
            invoice_id,
            refund_transaction_id="tx-late-distinct-refund-pg-1",
            payment_transaction_id="tx-late-distinct-charge-pg-1",
            amount="990.00",
        ),
    )

    assert cancel_response.json() == {"code": 0}
    assert late_pay_response.json() == {"code": 13}
    assert refund_response.json() == {"code": 13}
    with TestingSessionLocal() as db:
        order = db.query(Order).one()
        payments = db.query(Payment).order_by(Payment.provider_payment_id).all()
        refund_count = db.query(Refund).count()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status == "canceled"
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-canceled-attempt-pg-1", "canceled"),
    ]
    assert refund_count == 0
    assert [event.status for event in events] == ["processed", "failed", "failed"]
    assert [event.error_code for event in events] == [
        None,
        "payment_schema_mismatch",
        "payment_not_found",
    ]


def test_excessive_partial_refund_is_rejected_without_refund_total_mutation() -> None:
    reset_schema()
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-excessive-refund-1"
    transaction_id = "tx-excessive-refund-payment-1"
    seed_order(invoice_id)

    pay_response = client.post(
        "/api/cloudpayments/pay",
        json=paid_payload(invoice_id, transaction_id),
    )
    first_refund_response = client.post(
        "/api/cloudpayments/refund",
        json=refund_payload(
            invoice_id,
            refund_transaction_id="tx-partial-refund-1",
            payment_transaction_id=transaction_id,
            amount="600.00",
        ),
    )
    excessive_refund_response = client.post(
        "/api/cloudpayments/refund",
        json=refund_payload(
            invoice_id,
            refund_transaction_id="tx-partial-refund-2",
            payment_transaction_id=transaction_id,
            amount="500.00",
        ),
    )

    assert pay_response.status_code == 200
    assert first_refund_response.status_code == 200
    assert excessive_refund_response.status_code == 200
    assert excessive_refund_response.json() == {"code": 13}
    with TestingSessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        refunds = db.query(Refund).all()

    assert order.status == "partially_refunded"
    assert payment.status == "partially_refunded"
    assert payment.refunded_amount_minor == 60000
    assert len(refunds) == 1
    assert [event.status for event in events] == ["processed", "processed", "failed"]
    assert events[-1].payment_id == payment.id
    assert events[-1].error_code == "refund_amount_exceeds_payment"


def test_refund_one_of_multiple_successful_payments_keeps_order_partially_refunded() -> None:
    reset_schema()
    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-multi-success-refund-1"
    seed_order(invoice_id)

    first_pay_response = client.post(
        "/api/cloudpayments/pay",
        json=paid_payload(invoice_id, "tx-multi-success-refund-pg-1"),
    )
    second_pay_response = client.post(
        "/api/cloudpayments/pay",
        json=paid_payload(invoice_id, "tx-multi-success-refund-pg-2"),
    )
    refund_response = client.post(
        "/api/cloudpayments/refund",
        json=refund_payload(
            invoice_id,
            refund_transaction_id="tx-multi-success-refund-pg-refund-1",
            payment_transaction_id="tx-multi-success-refund-pg-1",
            amount="990.00",
        ),
    )

    assert first_pay_response.status_code == 200
    assert second_pay_response.status_code == 200
    assert refund_response.status_code == 200
    assert refund_response.json() == {"code": 0}
    with TestingSessionLocal() as db:
        order = db.query(Order).one()
        payments = db.query(Payment).order_by(Payment.provider_payment_id).all()
        refund = db.query(Refund).one()

    assert order.status == "partially_refunded"
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-multi-success-refund-pg-1", "refunded"),
        ("tx-multi-success-refund-pg-2", "succeeded"),
    ]
    assert [payment.refunded_amount_minor for payment in payments] == [99000, 0]
    assert refund.provider_refund_id == "tx-multi-success-refund-pg-refund-1"


def test_concurrent_recurrent_duplicate_delivery_is_serialized(monkeypatch) -> None:
    reset_schema()
    app.dependency_overrides[get_db] = override_get_db
    seed_order("inv-recurrent-account-scope")

    original_find_account = cloudpayments_processing.find_default_provider_account
    first_account_locked = threading.Event()
    call_lock = threading.Lock()
    call_count = 0

    def slow_first_account_lookup(*args, **kwargs):
        nonlocal call_count
        account = original_find_account(*args, **kwargs)
        with call_lock:
            call_count += 1
            is_first_call = call_count == 1
        if is_first_call:
            first_account_locked.set()
            time.sleep(0.3)
        return account

    monkeypatch.setattr(
        cloudpayments_processing,
        "find_default_provider_account",
        slow_first_account_lookup,
    )

    payload = {
        "Id": "sub-concurrent-recurrent-1",
        "AccountId": "durable-webhook@example.com",
        "Description": "Document Summary Pro",
        "Email": "durable-webhook@example.com",
        "Status": "Active",
        "Amount": "990.00",
        "Currency": "RUB",
        "RequireConfirmation": False,
        "StartDate": "2026-08-07 00:00:00",
        "Interval": "Month",
        "Period": 1,
        "SuccessfulTransactionsNumber": 1,
        "FailedTransactionsNumber": 0,
    }

    def post_webhook():
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.post("/api/cloudpayments/recurrent", json=payload)

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_result = executor.submit(post_webhook)
            assert first_account_locked.wait(timeout=5)
            second_result = executor.submit(post_webhook)

            first_response = first_result.result(timeout=10)
            second_response = second_result.result(timeout=10)

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert first_response.json() == {"code": 0}
        assert second_response.json() == {"code": 0}

        with TestingSessionLocal() as db:
            events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

        assert sorted(event.status for event in events) == ["duplicate", "processed"]
        assert {event.idempotency_key for event in events} == {
            "cloudpayments:recurrent:payload:" + events[0].payload_hash
        }
        assert all(event.provider_account_id is not None for event in events)
    finally:
        app.dependency_overrides.clear()
