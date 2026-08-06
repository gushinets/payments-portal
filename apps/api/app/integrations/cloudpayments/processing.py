from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from app.models import Order, Payment, PaymentWebhookEvent, Refund, User


def datetime_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def _get_first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _parse_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = _get_first(payload, "Data", "data")
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
        "invoice_id": _get_first(payload, "InvoiceId", "invoiceId", "invoice_id"),
        "transaction_id": _get_first(payload, "TransactionId", "transactionId", "transaction_id"),
        "account_id": _get_first(payload, "AccountId", "accountId", "account_id"),
        "payment_method_type": _get_first(payload, "PaymentMethod", "paymentMethod"),
        "reason_code": _get_first(payload, "ReasonCode", "reasonCode"),
        "reason": _get_first(payload, "Reason", "reason"),
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
    payload: dict[str, Any],
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
    payment.payment_method_type = _get_first(payload, "PaymentMethod", "paymentMethod")
    payment.raw_summary = _safe_summary(payload, data)

    if endpoint in {"pay", "confirm"}:
        payment.status = "succeeded"
        payment.authorized_at = payment.authorized_at or now
        payment.captured_at = payment.captured_at or now
        order.status = "paid"
        order.paid_at = order.paid_at or now
        order.failed_at = None
    elif endpoint == "fail":
        terminal_payment_statuses = {"succeeded", "refunded", "partially_refunded"}
        terminal_order_statuses = {"paid", "refunded", "partially_refunded"}
        if previous_payment_status not in terminal_payment_statuses:
            payment.status = "failed"
            payment.failed_at = payment.failed_at or now
            payment.failure_code = str(_get_first(payload, "ReasonCode", "reasonCode") or "")
            payment.failure_message_safe = _get_first(payload, "Reason", "reason")
        if order.status not in terminal_order_statuses:
            order.status = "payment_failed"
            order.failed_at = order.failed_at or now
    elif endpoint == "cancel":
        terminal_payment_statuses = {"succeeded", "refunded", "partially_refunded"}
        terminal_order_statuses = {"paid", "refunded", "partially_refunded"}
        if previous_payment_status not in terminal_payment_statuses:
            payment.status = "canceled"
        if order.status not in terminal_order_statuses:
            order.status = "canceled"
            order.canceled_at = order.canceled_at or now

    db.add(payment)
    db.add(order)
    db.flush()
    return payment


def _record_refund(
    db: Session,
    *,
    order: Order,
    payment: Payment,
    amount_minor: int,
    currency: str,
    payload: dict[str, Any],
) -> Refund:
    now = datetime_now()
    provider_refund_id = _get_first(
        payload,
        "RefundId",
        "refundId",
        "TransactionId",
        "transactionId",
    )
    refund = None
    if provider_refund_id:
        refund = (
            db.query(Refund)
            .filter(
                Refund.provider_account_id == order.provider_account_id,
                Refund.provider_refund_id == str(provider_refund_id),
            )
            .first()
        )
    if refund is None:
        refund = Refund(
            tenant_id=order.tenant_id,
            region=order.region,
            order_id=order.id,
            payment_id=payment.id,
            provider_account_id=order.provider_account_id,
            provider_refund_id=str(provider_refund_id) if provider_refund_id else None,
            status="succeeded",
            amount_minor=amount_minor,
            currency=currency,
            reason=_get_first(payload, "Reason", "reason"),
            requested_at=now,
            succeeded_at=now,
            metadata_={},
        )
    else:
        return refund
    payment.refunded_amount_minor = max(payment.refunded_amount_minor, 0) + amount_minor
    payment.status = "refunded" if payment.refunded_amount_minor >= payment.amount_minor else "partially_refunded"
    order.status = "refunded" if payment.refunded_amount_minor >= order.amount_minor else "partially_refunded"
    db.add(refund)
    db.add(payment)
    db.add(order)
    db.flush()
    return refund


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


def _money_mismatch(order: Order, *, amount_minor: int | None, currency: str | None) -> str | None:
    if amount_minor is None:
        return "missing_amount"
    if amount_minor != order.amount_minor:
        return "amount_mismatch"
    if currency is None:
        return "missing_currency"
    if currency.upper() != order.currency.upper():
        return "currency_mismatch"
    return None


def _account_mismatch(
    db: Session,
    order: Order,
    *,
    account_id: str | None,
    require_account_id: bool,
) -> str | None:
    if not account_id:
        return "missing_account_id" if require_account_id else None
    user = db.get(User, order.user_id)
    if user is None:
        return "account_mismatch"
    if str(account_id).strip().lower() != user.email_normalized:
        return "account_mismatch"
    return None


def _order_expired(order: Order) -> bool:
    if order.expires_at is None:
        return False
    now = datetime_now()
    expires_at = order.expires_at
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return expires_at < now


def _validation_error(
    db: Session,
    order: Order,
    *,
    account_id: str | None,
    amount_minor: int | None,
    currency: str | None,
    require_account_id: bool = True,
) -> str | None:
    account_error = _account_mismatch(
        db,
        order,
        account_id=account_id,
        require_account_id=require_account_id,
    )
    if account_error is not None:
        return account_error
    money_error = _money_mismatch(order, amount_minor=amount_minor, currency=currency)
    if money_error is not None:
        return money_error
    if _order_expired(order):
        return "order_expired"
    return None


def _validation_error_message(error_code: str) -> str:
    return {
        "missing_account_id": "Webhook account id is missing",
        "account_mismatch": "Webhook account id does not match order user",
        "missing_amount": "Webhook amount is missing",
        "amount_mismatch": "Webhook amount does not match order",
        "missing_currency": "Webhook currency is missing",
        "currency_mismatch": "Webhook currency does not match order",
        "order_expired": "Order is expired",
    }.get(error_code, "Webhook validation failed")


def _refund_validation_error(
    db: Session,
    order: Order,
    *,
    account_id: str | None,
    amount_minor: int | None,
    currency: str | None,
) -> str | None:
    account_error = _account_mismatch(
        db,
        order,
        account_id=account_id,
        require_account_id=False,
    )
    if account_error is not None:
        return account_error
    if amount_minor is None:
        return "missing_amount"
    if amount_minor <= 0 or amount_minor > order.amount_minor:
        return "amount_mismatch"
    if currency is None:
        return "missing_currency"
    if currency.upper() != order.currency.upper():
        return "currency_mismatch"
    return None


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

    existing_event = None
    if order is not None:
        existing_event = (
            db.query(PaymentWebhookEvent)
            .filter(
                PaymentWebhookEvent.provider_account_id == order.provider_account_id,
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
    elif endpoint == "recurrent":
        event.status = "processed"
        event.processed_at = datetime_now()
    elif order is None:
        event.status = "failed"
        event.error_code = "order_not_found"
        event.error_message = "No order found for provider invoice"
        event.processed_at = datetime_now()
    elif endpoint == "check":
        validation_error = _validation_error(
            db,
            order,
            account_id=account_id,
            amount_minor=amount_minor,
            currency=currency,
        )
        if validation_error is None:
            event.status = "processed"
        else:
            event.status = "failed"
            event.error_code = validation_error
            event.error_message = _validation_error_message(validation_error)
        event.processed_at = datetime_now()
    elif endpoint in {"pay", "fail", "confirm", "cancel"}:
        validation_error = _validation_error(
            db,
            order,
            account_id=account_id,
            amount_minor=amount_minor,
            currency=currency,
        )
        if validation_error is not None:
            event.status = "failed"
            event.error_code = validation_error
            event.error_message = _validation_error_message(validation_error)
        else:
            assert amount_minor is not None
            assert currency is not None
            payment = upsert_payment_from_webhook(
                db,
                endpoint=endpoint,
                order=order,
                invoice_id=invoice_id,
                transaction_id=transaction_id,
                amount_minor=amount_minor,
                currency=currency,
                payload=payload,
            )
            event.payment_id = payment.id
            event.status = "processed"
        event.processed_at = datetime_now()
    elif endpoint == "refund":
        validation_error = _refund_validation_error(
            db,
            order,
            account_id=account_id,
            amount_minor=amount_minor,
            currency=currency,
        )
        if validation_error is not None:
            event.status = "failed"
            event.error_code = validation_error
            event.error_message = _validation_error_message(validation_error)
            event.processed_at = datetime_now()
            db.add(event)
            db.flush()
            return event
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
            refund = _record_refund(
                db,
                order=order,
                payment=payment,
                amount_minor=amount_minor if amount_minor is not None else payment.amount_minor,
                currency=currency if currency is not None else payment.currency,
                payload=payload,
            )
            event.payment_id = payment.id
            event.status = "processed"
            event.processed_at = refund.succeeded_at

    db.add(event)
    db.flush()
    return event
