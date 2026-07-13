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
from app.core.settings import settings
from app.integrations.cloudpayments.processing import (
    datetime_now,
    fail_webhook_event,
    find_order,
    process_webhook_event,
    safe_normalization_error_message,
)
from app.models import PaymentWebhookEvent

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
        status = "failed"
        error_code = "payload_parse_error"
        error_message = f"payload_parse_error: {type(exc).__name__}"

    if not verify_cloudpayments_signature(raw_body, headers):
        status = "failed"
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
    order = find_order(db, str(invoice_id) if invoice_id is not None else None)
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
        processed_at=datetime_now() if error_message else None,
    )
    db.add(event)
    db.flush()
    event_id = event.id
    db.commit()
    db.refresh(event)

    if not error_message:
        try:
            event = process_webhook_event(
                db,
                event_id=event_id,
                endpoint=endpoint,
                payload=payload,
                invoice_id=str(invoice_id) if invoice_id is not None else None,
                transaction_id=str(transaction_id) if transaction_id is not None else None,
                amount_minor=amount_minor,
                currency=str(currency) if currency is not None else None,
                idempotency_key=idempotency_key,
            )
            db.commit()
            db.refresh(event)
        except Exception as exc:
            db.rollback()
            event = fail_webhook_event(
                db,
                event_id=event_id,
                error_code="normalization_unexpected_error",
                error_message=safe_normalization_error_message(exc),
            )
            record_webhook(endpoint, event.status)
            logger.warning(
                "cloudpayments_webhook_error endpoint=%s status=%s error_code=%s error=%s transaction_id=%s invoice_id=%s",
                endpoint,
                event.status,
                event.error_code,
                event.error_message,
                event.transaction_id,
                event.invoice_id,
            )
            raise HTTPException(status_code=500, detail="webhook_normalization_failed") from exc

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
