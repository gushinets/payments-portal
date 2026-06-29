from __future__ import annotations

import base64
import hashlib
import hmac
import json
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import PaymentWebhookEvent
from app.settings import settings

router = APIRouter(prefix="/api/cloudpayments", tags=["cloudpayments"])

SUPPORTED_ENDPOINTS = {"check", "pay", "fail", "refund", "recurrent"}


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


def _parse_amount(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


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
    error_message = None

    try:
        payload = await parse_payload(request, raw_body)
    except Exception as exc:
        payload = {"_raw": raw_body.decode("utf-8", errors="replace")}
        status = "error"
        error_message = f"payload_parse_error: {exc}"

    if not verify_cloudpayments_signature(raw_body, headers):
        status = "error"
        error_message = "invalid_cloudpayments_signature"

    event = PaymentWebhookEvent(
        endpoint=endpoint,
        event_type=endpoint,
        invoice_id=_get_first(payload, "InvoiceId", "invoiceId", "invoice_id"),
        transaction_id=_get_first(
            payload, "TransactionId", "transactionId", "transaction_id"
        ),
        account_id=_get_first(payload, "AccountId", "accountId", "account_id"),
        amount=_parse_amount(_get_first(payload, "Amount", "amount")),
        currency=_get_first(payload, "Currency", "currency"),
        raw_payload=payload,
        headers=headers,
        status=status,
        error_message=error_message,
    )
    db.add(event)
    db.commit()

    if error_message == "invalid_cloudpayments_signature":
        raise HTTPException(status_code=400, detail=error_message)

    return {"code": 0}
