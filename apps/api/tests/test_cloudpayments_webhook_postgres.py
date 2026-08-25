from __future__ import annotations

import base64
import hashlib
import hmac
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from apps.api.tests.support.postgres import reset_public_schema
from apps.api.tests.support.settings import configure_api_test_environment

configure_api_test_environment(CLOUDPAYMENTS_PUBLIC_ID="")

pytestmark = pytest.mark.postgres

from app.core.database import Base, get_db  # noqa: E402
from app.integrations.cloudpayments import adapter as cloudpayments_adapter_module  # noqa: E402
from app.integrations.cloudpayments.adapter import verify_cloudpayments_signature  # noqa: E402
from app.integrations.cloudpayments import processing as cloudpayments_processing  # noqa: E402
from app.core.settings import settings  # noqa: E402
from app.domains.billing.enums import (  # noqa: E402
    EntitlementStatus,
    ProviderSubscriptionState,
    SubscriptionEventType,
    SubscriptionStatus,
)
from app.domains.billing.service import (  # noqa: E402
    ApplyProviderSubscriptionStateCommand,
    apply_provider_subscription_state,
)
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    Entitlement,
    Order,
    Payment,
    PaymentProviderAccount,
    PaymentWebhookEvent,
    Plan,
    Refund,
    Region,
    Subscription,
    SubscriptionEvent,
    User,
)


@pytest.fixture
def webhook_database(
    postgres_engine: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[sessionmaker[Session]]:
    """Provide isolated PostgreSQL state and sessions for webhook persistence tests.

    Use this module-local fixture when a webhook test needs ORM-created metadata,
    FastAPI database injection, or independent sessions for concurrent requests.
    Signature verification is bypassed because these tests cover persistence;
    signature contract tests must restore the real verifier explicitly.
    """
    reset_public_schema(postgres_engine)
    Base.metadata.create_all(postgres_engine)

    def override_get_db() -> Iterator[Session]:
        with postgres_session_factory() as db:
            yield db

    monkeypatch.setattr(
        cloudpayments_adapter_module,
        "verify_cloudpayments_signature",
        lambda _raw_body, _headers: True,
    )
    app.dependency_overrides[get_db] = override_get_db
    try:
        yield postgres_session_factory
    finally:
        app.dependency_overrides.clear()
        reset_public_schema(postgres_engine)


def cloudpayments_signature(raw_body: bytes, secret: str = "test-secret") -> str:
    return base64.b64encode(hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()).decode("ascii")


def seed_order(
    session_factory: sessionmaker[Session],
    invoice_id: str,
    *,
    widget_mode: str = "charge",
) -> None:
    now = datetime.now(timezone.utc)
    with session_factory() as db:
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
        plan = Plan(
            tenant_id="anytoolai",
            region="ru",
            code=f"webhook-plan-{invoice_id}",
            name="Webhook Test Plan",
            scope_type="all_access",
            price_amount_minor=99000,
            currency="RUB",
            billing_period="month",
            renewal_mode="manual",
            trial_days=0,
            status="active",
            valid_from=now,
        )
        db.add(plan)
        db.flush()
        db.add(
            Order(
                tenant_id="anytoolai",
                region="ru",
                order_number="RU-TEST-0001",
                user_id=user.id,
                plan_id=plan.id,
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


def seed_migrated_legacy_order(
    session_factory: sessionmaker[Session],
    invoice_id: str,
    *,
    payment_transaction_id: str,
    order_status: str = "paid",
    subscription_status: str = SubscriptionStatus.ACTIVE.value,
) -> None:
    seed_order(session_factory, invoice_id)
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        order = db.query(Order).filter(Order.provider_invoice_id == invoice_id).one()
        plan = db.get(Plan, order.plan_id)
        assert plan is not None
        order.status = order_status
        order.paid_at = order.paid_at or now
        if order_status == "canceled":
            order.canceled_at = now + timedelta(minutes=1)
        payment = Payment(
            tenant_id=order.tenant_id,
            region=order.region,
            order_id=order.id,
            provider_account_id=order.provider_account_id,
            provider=order.provider,
            provider_payment_id=payment_transaction_id,
            provider_invoice_id=invoice_id,
            status="succeeded",
            amount_minor=order.amount_minor,
            currency=order.currency,
            captured_at=now,
            refunded_amount_minor=0,
            raw_summary={},
        )
        db.add(payment)
        db.flush()
        subscription = Subscription(
            tenant_id=order.tenant_id,
            region=order.region,
            user_id=order.user_id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=subscription_status,
            renewal_mode="manual",
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        db.add(subscription)
        db.flush()
        entitlement = Entitlement(
            tenant_id=order.tenant_id,
            region=order.region,
            user_id=order.user_id,
            subscription_id=subscription.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=EntitlementStatus.ACTIVE.value,
            valid_from=subscription.current_period_start,
            valid_until=subscription.current_period_end,
            source="order",
            order_id=order.id,
        )
        migration_event = SubscriptionEvent(
            subscription_id=subscription.id,
            event_type=SubscriptionEventType.LEGACY_ACCESS_MIGRATED.value,
            previous_status=None,
            next_status=subscription_status,
            occurred_at=now,
            operation_idempotency_key=f"legacy_access_migrated:{invoice_id}",
            order_id=order.id,
            payment_id=payment.id,
            metadata_={"legacy_access_state_id": invoice_id},
        )
        db.add_all([order, entitlement, migration_event])
        db.commit()


def test_raw_webhook_event_survives_failed_normalization_and_can_retry(
    monkeypatch: pytest.MonkeyPatch,
    webhook_database: sessionmaker[Session],
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-durable-1"
    seed_order(webhook_database, invoice_id)

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
    with webhook_database() as db:
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
    with webhook_database() as db:
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        order = db.query(Order).one()
        payments = db.query(Payment).all()

    assert [event.status for event in events] == ["failed", "processed"]
    assert order.status == "paid"
    assert len(payments) == 1
    assert payments[0].provider_payment_id == "tx-durable-1"


def test_concurrent_duplicate_webhook_is_serialized_with_provider_payment_id(
    monkeypatch: pytest.MonkeyPatch,
    webhook_database: sessionmaker[Session],
) -> None:
    invoice_id = "inv-concurrent-1"
    seed_order(webhook_database, invoice_id)

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
        "TransactionId": "tx-concurrent-1",
        "AccountId": "durable-webhook@example.com",
        "Amount": "990.00",
        "Currency": "RUB",
        "Status": "Completed",
    }

    def post_webhook():
        with TestClient(app, raise_server_exceptions=False) as client:
            return client.post("/api/cloudpayments/pay", json=payload)

    with ThreadPoolExecutor(max_workers=2) as executor:
        first_result = executor.submit(post_webhook)
        assert first_upsert_entered.wait(timeout=5)
        second_result = executor.submit(post_webhook)

        first_response = first_result.result(timeout=10)
        second_response = second_result.result(timeout=10)

    assert first_response.status_code == 200
    assert second_response.status_code == 200

    with webhook_database() as db:
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        order = db.query(Order).one()
        payments = db.query(Payment).all()

    assert sorted(event.status for event in events) == ["duplicate", "processed"]
    processed_event = next(event for event in events if event.status == "processed")
    duplicate_event = next(event for event in events if event.status == "duplicate")
    assert duplicate_event.payment_id == processed_event.payment_id
    assert order.status == "paid"
    assert len(payments) == 1
    assert payments[0].provider_payment_id == "tx-concurrent-1"


def test_signed_duplicate_webhook_is_persisted_once_and_acknowledged_idempotently(
    monkeypatch: pytest.MonkeyPatch,
    webhook_database: sessionmaker[Session],
) -> None:
    monkeypatch.setattr(
        cloudpayments_adapter_module,
        "verify_cloudpayments_signature",
        verify_cloudpayments_signature,
    )
    original_enabled = settings.cloudpayments_enabled
    original_api_secret = settings.cloudpayments_api_secret
    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", "test-secret")
    invoice_id = "inv-signed-duplicate-1"
    seed_order(webhook_database, invoice_id)

    raw_payload = (
        b'{"InvoiceId":"inv-signed-duplicate-1","TransactionId":"tx-signed-duplicate-1",'
        b'"AccountId":"durable-webhook@example.com","Amount":"990.00",'
        b'"Currency":"RUB","Status":"Completed"}'
    )
    headers = {
        "Content-HMAC": cloudpayments_signature(raw_payload),
        "Content-Type": "application/json",
    }

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
            assert first_upsert_entered.wait(timeout=5)
            second_result = executor.submit(post_webhook)
            first_response = first_result.result(timeout=10)
            second_response = second_result.result(timeout=10)

        assert first_response.status_code == 200
        assert second_response.status_code == 200
        assert first_response.json() == {"code": 0}
        assert second_response.json() == {"code": 0}

        with webhook_database() as db:
            events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
            payments = db.query(Payment).all()
            order = db.query(Order).one()

        assert sorted(event.status for event in events) == ["duplicate", "processed"]
        assert len(payments) == 1
        assert payments[0].provider_payment_id == "tx-signed-duplicate-1"
        assert order.status == "paid"
    finally:
        object.__setattr__(settings, "cloudpayments_enabled", original_enabled)
        object.__setattr__(settings, "cloudpayments_api_secret", original_api_secret)


def test_cancel_after_paid_payment_is_ignored_without_state_regression(
    webhook_database: sessionmaker[Session],
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-cancel-after-paid-1"
    transaction_id = "tx-paid-before-cancel-1"
    seed_order(webhook_database, invoice_id, widget_mode="auth")

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
    with webhook_database() as db:
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


def test_cancel_after_refunded_payment_is_ignored_without_refund_mutation(
    webhook_database: sessionmaker[Session],
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-cancel-after-refund-1"
    transaction_id = "tx-refunded-before-cancel-1"
    seed_order(webhook_database, invoice_id, widget_mode="auth")

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
    with webhook_database() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        refunds = db.query(Refund).all()

    assert order.status == "refunded"
    assert payment.status == "refunded"
    assert payment.refunded_amount_minor == 99000
    assert len(refunds) == 1
    assert [event.status for event in events] == [
        "processed",
        "processed",
        "processed",
        "ignored",
    ]
    assert events[-1].payment_id == payment.id
    assert events[-1].error_code == "order_already_refunded"


def test_full_refund_after_provider_canceled_subscription_is_processed(
    webhook_database: sessionmaker[Session],
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-refund-after-provider-cancel-1"
    transaction_id = "tx-refund-after-provider-cancel-1"
    seed_order(webhook_database, invoice_id)

    pay_response = client.post(
        "/api/cloudpayments/pay",
        json=paid_payload(invoice_id, transaction_id),
    )
    assert pay_response.status_code == 200

    with webhook_database() as db:
        subscription = db.query(Subscription).one()
        apply_provider_subscription_state(
            db,
            ApplyProviderSubscriptionStateCommand(
                operation_idempotency_key="webhook-provider-cancel-before-refund",
                subscription_id=subscription.id,
                provider_state=ProviderSubscriptionState.CANCELED,
            ),
        )
        db.commit()

    refund_response = client.post(
        "/api/cloudpayments/refund",
        json=refund_payload(
            invoice_id,
            refund_transaction_id="tx-refund-after-provider-cancel-refund-1",
            payment_transaction_id=transaction_id,
            amount="990.00",
        ),
    )

    assert refund_response.status_code == 200
    assert refund_response.json() == {"code": 0}
    with webhook_database() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        subscription = db.query(Subscription).one()
        entitlement = db.query(Entitlement).one()
        refund_event = (
            db.query(SubscriptionEvent)
            .filter(SubscriptionEvent.event_type == SubscriptionEventType.REFUND_APPLIED.value)
            .one()
        )
        webhook_events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status == "refunded"
    assert payment.status == "refunded"
    assert payment.refunded_amount_minor == 99000
    assert subscription.status == SubscriptionStatus.REFUNDED.value
    assert entitlement.status == EntitlementStatus.REVOKED.value
    assert refund_event.previous_status == SubscriptionStatus.CANCELED.value
    assert refund_event.next_status == SubscriptionStatus.REFUNDED.value
    assert [event.status for event in webhook_events] == ["processed", "processed"]


def test_refund_after_canceled_payment_is_rejected_without_refund_mutation(
    webhook_database: sessionmaker[Session],
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-refund-after-cancel-1"
    transaction_id = "tx-canceled-before-refund-1"
    seed_order(webhook_database, invoice_id, widget_mode="auth")

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
    assert refund_response.json() == {"code": 0}
    with webhook_database() as db:
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
    assert events[-1].error_code == "payment_already_canceled"


def test_refund_after_failed_payment_is_rejected_without_refund_mutation(
    webhook_database: sessionmaker[Session],
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-refund-after-fail-1"
    transaction_id = "tx-failed-before-refund-1"
    seed_order(webhook_database, invoice_id)

    fail_response = client.post(
        "/api/cloudpayments/fail",
        json={
            **paid_payload(invoice_id, transaction_id),
            "ReasonCode": "5",
            "Reason": "Insufficient funds",
        },
    )
    refund_response = client.post(
        "/api/cloudpayments/refund",
        json=refund_payload(
            invoice_id,
            refund_transaction_id="tx-refund-after-fail-1",
            payment_transaction_id=transaction_id,
            amount="100.00",
        ),
    )

    assert fail_response.status_code == 200
    assert refund_response.status_code == 200
    assert refund_response.json() == {"code": 0}
    with webhook_database() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        refund_count = db.query(Refund).count()

    assert order.status == "payment_failed"
    assert payment.status == "failed"
    assert payment.refunded_amount_minor == 0
    assert refund_count == 0
    assert [event.status for event in events] == ["processed", "failed"]
    assert events[-1].payment_id == payment.id
    assert events[-1].error_code == "payment_not_refundable"


def test_migrated_legacy_full_refund_webhook_persists_and_duplicate_is_idempotent(
    webhook_database: sessionmaker[Session],
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-legacy-refund-webhook-1"
    payment_transaction_id = "tx-legacy-refund-original-1"
    refund_transaction_id = "tx-legacy-refund-refund-1"
    seed_migrated_legacy_order(
        webhook_database,
        invoice_id,
        payment_transaction_id=payment_transaction_id,
    )

    payload = refund_payload(
        invoice_id,
        refund_transaction_id=refund_transaction_id,
        payment_transaction_id=payment_transaction_id,
        amount="990.00",
    )
    first_response = client.post("/api/cloudpayments/refund", json=payload)
    second_response = client.post("/api/cloudpayments/refund", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == {"code": 0}
    assert second_response.json() == {"code": 0}
    with webhook_database() as db:
        order = db.query(Order).filter(Order.provider_invoice_id == invoice_id).one()
        payment = db.query(Payment).filter(Payment.provider_payment_id == payment_transaction_id).one()
        refunds = db.query(Refund).all()
        subscription = db.query(Subscription).one()
        entitlement = db.query(Entitlement).one()
        webhook_events = (
            db.query(PaymentWebhookEvent)
            .filter(PaymentWebhookEvent.endpoint == "refund")
            .order_by(PaymentWebhookEvent.received_at.asc())
            .all()
        )
        refund_events = (
            db.query(SubscriptionEvent)
            .filter(SubscriptionEvent.event_type == SubscriptionEventType.REFUND_APPLIED.value)
            .all()
        )
        migration_events = (
            db.query(SubscriptionEvent)
            .filter(SubscriptionEvent.event_type == SubscriptionEventType.LEGACY_ACCESS_MIGRATED.value)
            .all()
        )

    assert order.status == "refunded"
    assert payment.status == "refunded"
    assert payment.refunded_amount_minor == 99000
    assert len(refunds) == 1
    assert refunds[0].provider_refund_id == refund_transaction_id
    assert subscription.status == SubscriptionStatus.REFUNDED.value
    assert entitlement.status == EntitlementStatus.REVOKED.value
    assert [event.status for event in webhook_events] == ["processed", "duplicate"]
    assert webhook_events[0].order_id == order.id
    assert webhook_events[0].payment_id == payment.id
    assert len(refund_events) == 1
    assert refund_events[0].order_id == order.id
    assert refund_events[0].refund_id == refunds[0].id
    assert len(migration_events) == 1
    assert migration_events[0].order_id == order.id
    assert migration_events[0].payment_id == payment.id


def test_completed_pay_after_auth_cancel_can_be_refunded_without_reopening_order(
    webhook_database: sessionmaker[Session],
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-late-charge-refund-pg-1"
    seed_order(webhook_database, invoice_id, widget_mode="auth")

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
    assert late_pay_response.json() == {"code": 0}
    assert refund_response.json() == {"code": 0}
    with webhook_database() as db:
        order = db.query(Order).one()
        payments = db.query(Payment).order_by(Payment.provider_payment_id).all()
        refund_count = db.query(Refund).count()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status == "canceled"
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-canceled-attempt-pg-1", "canceled"),
        ("tx-late-distinct-charge-pg-1", "refunded"),
    ]
    assert refund_count == 1
    assert [event.status for event in events] == ["processed", "processed", "processed"]
    assert [event.error_code for event in events] == [
        None,
        None,
        None,
    ]


def test_excessive_partial_refund_is_rejected_without_refund_total_mutation(
    webhook_database: sessionmaker[Session],
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-excessive-refund-1"
    transaction_id = "tx-excessive-refund-payment-1"
    seed_order(webhook_database, invoice_id)

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
    assert excessive_refund_response.json() == {"code": 0}
    with webhook_database() as db:
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


def test_refund_one_of_multiple_successful_payments_keeps_order_partially_refunded(
    webhook_database: sessionmaker[Session],
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    invoice_id = "inv-multi-success-refund-1"
    seed_order(webhook_database, invoice_id)

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
    with webhook_database() as db:
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


def test_concurrent_recurrent_duplicate_delivery_is_serialized(
    monkeypatch: pytest.MonkeyPatch,
    webhook_database: sessionmaker[Session],
) -> None:
    seed_order(webhook_database, "inv-recurrent-account-scope")

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

    with webhook_database() as db:
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert sorted(event.status for event in events) == ["duplicate", "processed"]
    assert {event.idempotency_key for event in events} == {"cloudpayments:recurrent:payload:" + events[0].payload_hash}
    assert all(event.provider_account_id is not None for event in events)
