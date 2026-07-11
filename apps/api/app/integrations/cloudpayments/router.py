from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import record_webhook, redact, traced
from app.models import Order, Payment, PaymentWebhookEvent, Refund
from app.core.settings import settings

router = APIRouter(prefix="/api/cloudpayments", tags=["cloudpayments"])
logger = logging.getLogger(__name__)

SUPPORTED_ENDPOINTS = {"check", "pay", "fail", "refund", "recurrent"}
CARD_DATA_KEYS = {
    "cardfirstsix",
    "cardlastfour",
    "cardtype",
    "cardexpdate",
    "cardproduct",
    "token",
}


def _flatten_form_payload(raw_body: bytes) -> dict[str, Any]:
    parsed = parse_qs(raw_body.decode("utf-8"), keep_blank_values=True)
    return {
        key: values[0] if len(values) == 1 else values
        for key, values in parsed.items()
    }


async def parse_payload(request: Request, raw_body: bytes) -> dict[str, Any]:
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        if not raw_body:
            return {}
        return json.loads(raw_body.decode("utf-8"))
    return _flatten_form_payload(raw_body)


def _get_first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def _safe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in payload.items():
        if key.lower() in CARD_DATA_KEYS:
            safe[key] = "[redacted]"
        elif isinstance(value, dict):
            safe[key] = _safe_payload(value)
        else:
            safe[key] = value
    return safe


def _payload_hash(raw_body: bytes, payload: dict[str, Any]) -> str:
    if raw_body:
        return hashlib.sha256(raw_body).hexdigest()
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_amount(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _amount_minor(amount: Decimal | None) -> int | None:
    if amount is None:
        return None
    return int((amount * Decimal("100")).quantize(Decimal("1")))


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


def _provider_event_id(payload: dict[str, Any]) -> str | None:
    value = _get_first(
        payload,
        "EventId",
        "eventId",
        "NotificationId",
        "notificationId",
        "Id",
        "id",
    )
    return str(value) if value is not None else None


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


def _event_idempotency_key(
    endpoint: str,
    provider_event_id: str | None,
    invoice_id: str | None,
    transaction_id: str | None,
    refund_id: str | None,
    payload_hash: str,
) -> str:
    if provider_event_id:
        return f"cloudpayments:event:{provider_event_id}"
    if endpoint == "refund" and refund_id:
        return f"cloudpayments:refund:{refund_id}"
    if transaction_id:
        return f"cloudpayments:{endpoint}:transaction:{transaction_id}"
    if invoice_id:
        return f"cloudpayments:{endpoint}:invoice:{invoice_id}:{payload_hash}"
    return f"cloudpayments:{endpoint}:payload:{payload_hash}"


def _find_order(db: Session, invoice_id: str | None) -> Order | None:
    if not invoice_id:
        return None
    return (
        db.query(Order)
        .filter(
            Order.provider == "cloudpayments",
            Order.provider_invoice_id == invoice_id,
        )
        .first()
    )


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


def _upsert_payment_from_webhook(
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

    if endpoint == "pay":
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
    payment.refunded_amount_minor = max(payment.refunded_amount_minor, 0) + amount_minor
    payment.status = "refunded" if payment.refunded_amount_minor >= payment.amount_minor else "partially_refunded"
    order.status = "refunded" if payment.refunded_amount_minor >= order.amount_minor else "partially_refunded"
    db.add(refund)
    db.add(payment)
    db.add(order)
    db.flush()
    return refund


def datetime_now():
    from datetime import datetime, timezone

    return datetime.now(timezone.utc)


def verify_cloudpayments_signature(raw_body: bytes, headers: dict[str, str]) -> bool:
    if not settings.cloudpayments_api_secret:
        return True

    signature = (
        headers.get("content-hmac")
        or headers.get("x-content-hmac")
        or headers.get("Content-HMAC")
        or headers.get("X-Content-HMAC")
    )
    if not signature:
        return False

    digest = hmac.new(
        settings.cloudpayments_api_secret.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).digest()
    expected = base64.b64encode(digest).decode("ascii")
    return hmac.compare_digest(signature, expected)


@router.post("/{endpoint}")
@traced("cloudpayments.webhook.process")
async def receive_cloudpayments_webhook(
    endpoint: str,
    request: Request,
    db: Session = Depends(get_db),
):
    if endpoint not in SUPPORTED_ENDPOINTS:
        raise HTTPException(status_code=404, detail="Unsupported CloudPayments endpoint")

    raw_body = await request.body()
    headers = dict(request.headers)
    payload: dict[str, Any]
    status = "received"
    error_code = None
    error_message = None

    try:
        payload = await parse_payload(request, raw_body)
    except Exception as exc:
        payload = {"_raw": raw_body.decode("utf-8", errors="replace")}
        status = "error"
        error_code = "payload_parse_error"
        error_message = f"payload_parse_error: {exc}"

    if not verify_cloudpayments_signature(raw_body, headers):
        status = "error"
        error_code = "invalid_cloudpayments_signature"
        error_message = "invalid_cloudpayments_signature"

    invoice_id = _get_first(payload, "InvoiceId", "invoiceId", "invoice_id")
    transaction_id = _get_first(payload, "TransactionId", "transactionId", "transaction_id")
    refund_id = _get_first(payload, "RefundId", "refundId", "refund_id")
    amount = _parse_amount(_get_first(payload, "Amount", "amount"))
    amount_minor = _amount_minor(amount)
    currency = _get_first(payload, "Currency", "currency")
    provider_event_id = _provider_event_id(payload)
    payload_hash = _payload_hash(raw_body, payload)
    order = _find_order(db, str(invoice_id) if invoice_id is not None else None)
    idempotency_key = _event_idempotency_key(
        endpoint,
        provider_event_id,
        str(invoice_id) if invoice_id is not None else None,
        str(transaction_id) if transaction_id is not None else None,
        str(refund_id) if refund_id is not None else None,
        payload_hash,
    )

    event = PaymentWebhookEvent(
        tenant_id=order.tenant_id if order else "anytoolai",
        region=order.region if order else "ru",
        provider_account_id=order.provider_account_id if order else None,
        endpoint=endpoint,
        event_type=endpoint,
        provider_event_id=provider_event_id,
        idempotency_key=idempotency_key,
        payload_hash=payload_hash,
        invoice_id=str(invoice_id) if invoice_id is not None else None,
        transaction_id=str(transaction_id) if transaction_id is not None else None,
        account_id=_get_first(payload, "AccountId", "accountId", "account_id"),
        order_id=order.id if order else None,
        amount_minor=amount_minor,
        amount=amount,
        currency=str(currency) if currency is not None else None,
        raw_payload=_safe_payload(payload),
        headers=redact(headers),
        status=status,
        error_code=error_code,
        error_message=error_message,
    )
    db.add(event)
    db.flush()

    if not error_message:
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
        elif order is None:
            event.status = "ignored"
            event.error_code = "order_not_found"
            event.error_message = "No order found for provider invoice"
            event.processed_at = datetime_now()
        elif endpoint in {"check", "recurrent"}:
            event.status = "ignored"
            event.processed_at = datetime_now()
        elif endpoint in {"pay", "fail"}:
            payment = _upsert_payment_from_webhook(
                db,
                endpoint=endpoint,
                order=order,
                invoice_id=str(invoice_id) if invoice_id is not None else None,
                transaction_id=str(transaction_id) if transaction_id is not None else None,
                amount_minor=amount_minor if amount_minor is not None else order.amount_minor,
                currency=str(currency) if currency is not None else order.currency,
                payload=payload,
            )
            event.payment_id = payment.id
            event.status = "processed"
            event.processed_at = datetime_now()
        elif endpoint == "refund":
            payment = _find_payment(
                db,
                order=order,
                transaction_id=str(transaction_id) if transaction_id is not None else None,
            )
            if payment is None:
                event.status = "failed"
                event.error_code = "payment_not_found"
                event.error_message = "No payment found for refund webhook"
            else:
                refund = _record_refund(
                    db,
                    order=order,
                    payment=payment,
                    amount_minor=amount_minor if amount_minor is not None else payment.amount_minor,
                    currency=str(currency) if currency is not None else payment.currency,
                    payload=payload,
                )
                event.payment_id = payment.id
                event.status = "processed"
                event.processed_at = refund.succeeded_at

    db.commit()
    db.refresh(event)
    record_webhook(endpoint, event.status)

    if error_message:
        logger.warning(
            "cloudpayments_webhook_error endpoint=%s status=%s error=%s transaction_id=%s invoice_id=%s",
            endpoint,
            status,
            error_message,
            event.transaction_id,
            event.invoice_id,
        )

    if error_message == "invalid_cloudpayments_signature":
        raise HTTPException(status_code=400, detail=error_message)

    return {"code": 0}
