from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.integrations.cloudpayments.payload import get_first
from app.integrations.cloudpayments.validation import (
    cancel_validation_error,
    check_order_state_error,
    confirm_validation_error,
    payment_validation_error,
    recurrent_validation_error,
    refund_validation_error,
    validation_error_message,
)
from app.integrations.cloudpayments.refunds import record_refund
from app.integrations.cloudpayments.rules import (
    find_default_provider_account,
    payment_schema_error,
)
from app.models import Order, Payment, PaymentWebhookEvent

TERMINAL_ORDER_STATUSES = {"paid", "canceled", "refunded", "partially_refunded"}
TERMINAL_PAYMENT_STATUSES = {"succeeded", "canceled", "refunded", "partially_refunded"}


def datetime_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _parse_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = get_first(payload, "Data", "data")
    if isinstance(data, dict):
        return data
    if isinstance(data, str) and data:
        try:
            parsed = json.loads(data)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _safe_summary(payload: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    return {
        "invoice_id": get_first(payload, "InvoiceId", "invoiceId", "invoice_id"),
        "transaction_id": get_first(payload, "TransactionId", "transactionId", "transaction_id"),
        "account_id": get_first(payload, "AccountId", "accountId", "account_id"),
        "payment_method_type": get_first(payload, "PaymentMethod", "paymentMethod"),
        "reason_code": get_first(payload, "ReasonCode", "reasonCode"),
        "reason": get_first(payload, "Reason", "reason"),
        "data": {
            key: value
            for key, value in data.items()
            if key in {"product_code", "plan_code", "auto_renew"}
        },
    }


def find_order(db: Session, invoice_id: str | None, *, for_update: bool = False) -> Order | None:
    if not invoice_id:
        return None
    query = db.query(Order).filter(
        Order.provider == "cloudpayments",
        Order.provider_invoice_id == invoice_id,
    )
    if for_update:
        query = query.with_for_update()
    return query.first()


def _find_payment(
    db: Session,
    *,
    order: Order,
    transaction_id: str | None,
) -> Payment | None:
    query = db.query(Payment).filter(Payment.provider_account_id == order.provider_account_id)
    if transaction_id:
        payment = query.filter(Payment.provider_payment_id == transaction_id).first()
        if payment is not None:
            return payment
        return None
    return (
        db.query(Payment)
        .filter(
            Payment.order_id == order.id,
            Payment.provider_payment_id.is_(None),
        )
        .first()
    )


def upsert_payment_from_webhook(
    db: Session,
    *,
    endpoint: str,
    order: Order,
    invoice_id: str | None,
    transaction_id: str | None,
    amount_minor: int,
    currency: str,
    payload: dict[str, Any], update_order_status: bool = True,
) -> Payment:
    now = datetime_now()
    data = _parse_data(payload)
    payment = _find_payment(db, order=order, transaction_id=transaction_id)
    if payment is None:
        payment = Payment(
            tenant_id=order.tenant_id,
            region=order.region,
            order_id=order.id,
            provider_account_id=order.provider_account_id,
            provider=order.provider,
            provider_payment_id=transaction_id,
            provider_invoice_id=invoice_id,
            status="created",
            amount_minor=amount_minor,
            currency=currency,
            raw_summary={},
        )

    previous_payment_status = payment.status
    payment.provider_payment_id = transaction_id
    payment.provider_invoice_id = invoice_id
    payment.amount_minor = amount_minor
    payment.currency = currency
    payment.payment_method_type = get_first(payload, "PaymentMethod", "paymentMethod")
    payment.raw_summary = _safe_summary(payload, data)

    provider_status = str(get_first(payload, "Status", "status") or "").lower()
    if endpoint == "pay" and provider_status == "authorized":
        if previous_payment_status not in TERMINAL_PAYMENT_STATUSES:
            payment.status = "authorized"
            payment.authorized_at = payment.authorized_at or now
    elif endpoint in {"pay", "confirm"}:
        if previous_payment_status not in TERMINAL_PAYMENT_STATUSES:
            payment.status = "succeeded"
            payment.authorized_at = payment.authorized_at or now
            payment.captured_at = payment.captured_at or now
            if update_order_status:
                order.status = "paid"
                order.paid_at = order.paid_at or now
                order.failed_at = None
    elif endpoint == "fail":
        if previous_payment_status not in TERMINAL_PAYMENT_STATUSES:
            payment.status = "failed"
            payment.failed_at = payment.failed_at or now
            payment.failure_code = str(get_first(payload, "ReasonCode", "reasonCode") or "")
            payment.failure_message_safe = get_first(payload, "Reason", "reason")
        if order.status not in TERMINAL_ORDER_STATUSES:
            order.status = "payment_failed"
            order.failed_at = order.failed_at or now
    elif endpoint == "cancel":
        if previous_payment_status not in TERMINAL_PAYMENT_STATUSES:
            payment.status = "canceled"
        if order.status not in TERMINAL_ORDER_STATUSES:
            order.status = "canceled"
            order.canceled_at = order.canceled_at or now

    db.add(payment)
    db.add(order)
    db.flush()
    return payment


def safe_normalization_error_message(exc: Exception) -> str:
    return f"Webhook normalization failed unexpectedly: {type(exc).__name__}"


def fail_webhook_event(
    db: Session,
    *,
    event_id: Any,
    error_code: str,
    error_message: str,
) -> PaymentWebhookEvent:
    event = db.get(PaymentWebhookEvent, event_id)
    if event is None:
        raise RuntimeError("payment_webhook_event_missing_after_rollback")
    event.status = "failed"
    event.error_code = error_code
    event.error_message = error_message[:1000]
    event.processed_at = datetime_now()
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def _terminal_order_event_error_code(order: Order) -> str:
    codes = {
        "canceled": "order_already_canceled",
        "refunded": "order_already_refunded",
        "partially_refunded": "order_already_refunded",
    }
    return codes.get(order.status, "order_already_paid")


def _handle_pay_or_confirm_for_terminal_order(
    db: Session,
    *,
    event: PaymentWebhookEvent,
    endpoint: str,
    order: Order,
    invoice_id: str | None,
    transaction_id: str | None,
    amount_minor: int | None,
    currency: str | None,
    payload: dict[str, Any],
) -> bool:
    if endpoint not in {"pay", "confirm"} or order.status not in TERMINAL_ORDER_STATUSES:
        return False
    payment = _find_payment(db, order=order, transaction_id=transaction_id)
    if payment is not None:
        if endpoint == "confirm" and payment.status not in TERMINAL_PAYMENT_STATUSES:
            assert amount_minor is not None
            payment = upsert_payment_from_webhook(
                db,
                endpoint=endpoint,
                order=order,
                invoice_id=invoice_id,
                transaction_id=transaction_id,
                amount_minor=amount_minor,
                currency=currency if currency is not None else order.currency,
                payload=payload,
                update_order_status=False,
            )
            event.payment_id = payment.id
            event.currency = payment.currency
            event.status = "processed"
            event.processed_at = datetime_now()
            return True
        event.payment_id = payment.id
        event.status = "ignored"
        event.error_code = _terminal_order_event_error_code(order)
        event.error_message = validation_error_message(event.error_code)
        event.processed_at = datetime_now()
        return True
    if not transaction_id:
        event.payment_id = None
        event.status = "ignored"
        event.error_code = _terminal_order_event_error_code(order)
        event.error_message = validation_error_message(event.error_code)
        event.processed_at = datetime_now()
        return True
    assert amount_minor is not None
    payment = upsert_payment_from_webhook(
        db,
        endpoint=endpoint,
        order=order,
        invoice_id=invoice_id,
        transaction_id=transaction_id,
        amount_minor=amount_minor,
        currency=currency if currency is not None else order.currency,
        payload=payload,
        update_order_status=False,
    )
    event.payment_id = payment.id
    event.currency = payment.currency
    event.status = "processed"
    event.processed_at = datetime_now()
    return True


def _ignore_cancel_for_terminal_order(
    db: Session,
    *,
    event: PaymentWebhookEvent,
    endpoint: str,
    order: Order,
    transaction_id: str | None,
) -> bool:
    if endpoint != "cancel" or order.status not in TERMINAL_ORDER_STATUSES:
        return False
    payment = _find_payment(db, order=order, transaction_id=transaction_id)
    event.payment_id = payment.id if payment is not None else None
    event.status = "ignored"
    event.error_code = _terminal_order_event_error_code(order)
    event.error_message = validation_error_message(event.error_code)
    event.processed_at = datetime_now()
    return True


def process_webhook_event(
    db: Session,
    *,
    event_id: Any,
    endpoint: str,
    payload: dict[str, Any],
    invoice_id: str | None,
    transaction_id: str | None,
    amount_minor: int | None,
    currency: str | None,
    idempotency_key: str,
    account_id: str | None = None,
) -> PaymentWebhookEvent:
    event = db.get(PaymentWebhookEvent, event_id)
    if event is None:
        raise RuntimeError("payment_webhook_event_missing")

    event.status = "processing"
    order = find_order(db, invoice_id, for_update=True)
    if order is not None:
        event.tenant_id = order.tenant_id
        event.region = order.region
        event.provider_account_id = order.provider_account_id
        event.order_id = order.id
    elif endpoint == "recurrent":
        provider_account = find_default_provider_account(db, for_update=True)
        if provider_account is not None:
            event.tenant_id = provider_account.tenant_id
            event.region = provider_account.region
            event.provider_account_id = provider_account.id

    existing_event = None
    if event.provider_account_id is not None:
        existing_event = (
            db.query(PaymentWebhookEvent)
            .filter(
                PaymentWebhookEvent.provider_account_id == event.provider_account_id,
                PaymentWebhookEvent.idempotency_key == idempotency_key,
                PaymentWebhookEvent.id != event.id,
                PaymentWebhookEvent.status.in_(("processed", "ignored", "duplicate")),
            )
            .first()
        )

    if existing_event is not None:
        event.status = "duplicate"
        event.processed_at = datetime_now()
        event.order_id = existing_event.order_id
        event.payment_id = existing_event.payment_id
    elif endpoint == "recurrent" and event.provider_account_id is None:
        event.status = "failed"
        event.error_code = "provider_account_not_found"
        event.error_message = validation_error_message(event.error_code)
        event.processed_at = datetime_now()
    elif endpoint == "recurrent":
        validation_error = recurrent_validation_error(
            payload,
            account_id=account_id,
            amount_minor=amount_minor,
            currency=currency,
        )
        if validation_error is None:
            event.status = "processed"
        else:
            event.status = "failed"
            event.error_code = validation_error
            event.error_message = validation_error_message(validation_error)
        event.processed_at = datetime_now()
    elif order is None:
        event.status = "failed"
        event.error_code = "order_not_found"
        event.error_message = "No order found for provider invoice"
        event.processed_at = datetime_now()
    elif endpoint == "check":
        validation_error = payment_schema_error(
            order=order,
            endpoint=endpoint,
            payload=payload,
        )
        if validation_error is None:
            validation_error = payment_validation_error(
                db,
                order,
                account_id=account_id,
                amount_minor=amount_minor,
                currency=currency,
                check_expiry=True,
            )
        validation_error = validation_error or check_order_state_error(order)
        if validation_error is None:
            event.status = "processed"
        else:
            event.status = "failed"
            event.error_code = validation_error
            event.error_message = validation_error_message(validation_error)
        event.processed_at = datetime_now()
    elif endpoint in {"pay", "fail", "confirm", "cancel"}:
        validation_error = None if transaction_id else "missing_transaction_id"
        validation_error = validation_error or payment_schema_error(
            order=order, endpoint=endpoint, payload=payload,
        )
        if validation_error is None and endpoint == "cancel":
            validation_error = cancel_validation_error(
                db,
                order,
                account_id=account_id,
                amount_minor=amount_minor,
                currency=currency,
            )
        elif validation_error is None and endpoint == "confirm":
            validation_error = confirm_validation_error(
                db,
                order,
                transaction_id=transaction_id,
                account_id=account_id,
                amount_minor=amount_minor,
                currency=currency,
            )
        elif validation_error is None:
            validation_error = payment_validation_error(
                db,
                order,
                account_id=account_id,
                amount_minor=amount_minor,
                currency=currency,
            )
        if validation_error is not None:
            event.status = "failed"
            event.error_code = validation_error
            event.error_message = validation_error_message(validation_error)
        elif _handle_pay_or_confirm_for_terminal_order(
            db,
            event=event,
            endpoint=endpoint,
            order=order,
            invoice_id=invoice_id,
            transaction_id=transaction_id,
            amount_minor=amount_minor,
            currency=currency,
            payload=payload,
        ) or _ignore_cancel_for_terminal_order(
            db,
            event=event,
            endpoint=endpoint,
            order=order,
            transaction_id=transaction_id,
        ):
            pass
        else:
            assert amount_minor is not None
            effective_currency = currency if currency is not None else order.currency
            payment = upsert_payment_from_webhook(
                db,
                endpoint=endpoint,
                order=order,
                invoice_id=invoice_id,
                transaction_id=transaction_id,
                amount_minor=amount_minor,
                currency=effective_currency,
                payload=payload,
            )
            event.payment_id = payment.id
            event.currency = effective_currency
            event.status = "processed"
        event.processed_at = datetime_now()
    elif endpoint == "refund":
        payment = _find_payment(
            db,
            order=order,
            transaction_id=transaction_id,
        )
        if payment is None:
            event.status = "failed"
            event.error_code = "payment_not_found"
            event.error_message = "No payment found for refund webhook"
            event.processed_at = datetime_now()
        else:
            event.payment_id = payment.id
            validation_error = refund_validation_error(
                db,
                order,
                payment,
                account_id=account_id,
                amount_minor=amount_minor,
                currency=currency,
            )
            if validation_error is not None:
                event.status = "failed"
                event.error_code = validation_error
                event.error_message = validation_error_message(validation_error)
                event.processed_at = datetime_now()
                db.add(event)
                db.flush()
                return event
            assert amount_minor is not None
            record_refund(
                db,
                order=order,
                payment=payment,
                amount_minor=amount_minor,
                currency=currency if currency is not None else payment.currency,
                payload=payload,
                now=datetime_now(),
            )
            event.currency = currency if currency is not None else payment.currency
            event.status = "processed"
            event.processed_at = datetime_now()

    db.add(event)
    db.flush()
    return event
