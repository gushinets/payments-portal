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

from app.database import get_db
from app.models import PaymentWebhookEvent, ProductAccessState, User
from app.settings import settings

router = APIRouter(prefix="/api/cloudpayments", tags=["cloudpayments"])
logger = logging.getLogger(__name__)

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


def _extract_json_data(payload: dict[str, Any]) -> dict[str, Any]:
    raw_data = _get_first(payload, "Data", "JsonData", "jsonData", "data")
    if isinstance(raw_data, dict):
        return raw_data
    if isinstance(raw_data, str):
        try:
            loaded = json.loads(raw_data)
            return loaded if isinstance(loaded, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def update_product_access_state(
    db: Session,
    endpoint: str,
    payload: dict[str, Any],
    event: PaymentWebhookEvent,
) -> None:
    email = _get_first(payload, "AccountId", "accountId", "account_id")
    invoice_id = _get_first(payload, "InvoiceId", "invoiceId", "invoice_id")
    transaction_id = _get_first(
        payload, "TransactionId", "transactionId", "transaction_id"
    )
    if not email or not invoice_id:
        return

    user = db.query(User).filter(User.email == str(email).lower()).first()
    if user is None:
        return

    state = (
        db.query(ProductAccessState)
        .filter(
            ProductAccessState.user_id == user.id,
            ProductAccessState.last_invoice_id == str(invoice_id),
        )
        .first()
    )

    json_data = _extract_json_data(payload)
    if state is None and json_data.get("product_code"):
        state = (
            db.query(ProductAccessState)
            .filter(
                ProductAccessState.user_id == user.id,
                ProductAccessState.product_code == json_data["product_code"],
            )
            .first()
        )
        if state is not None:
            state.last_invoice_id = str(invoice_id)

    if state is None:
        return

    state.last_transaction_id = str(transaction_id) if transaction_id else None

    if endpoint == "pay" and event.status == "received":
        state.status = "active"
    elif endpoint in {"fail", "refund"}:
        state.status = "failed"
    elif endpoint == "recurrent" and event.status == "received":
        state.status = "active"

    db.add(state)
    db.commit()


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
    db.refresh(event)

    if status != "error":
        update_product_access_state(db, endpoint, payload, event)

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
