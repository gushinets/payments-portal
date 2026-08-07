from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import record_webhook, traced
from app.integrations.cloudpayments.adapter import (
    SUPPORTED_ENDPOINTS,
    cloudpayments_adapter,
)
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
    normalized_event = await cloudpayments_adapter.normalize_webhook_request(
        endpoint=endpoint,
        request=request,
        raw_body=raw_body,
    )
    order = find_order(db, normalized_event.invoice_id)

    event = PaymentWebhookEvent(
        tenant_id=order.tenant_id if order else "anytoolai",
        region=order.region if order else "ru",
        provider_account_id=order.provider_account_id if order else None,
        provider=cloudpayments_adapter.provider_code,
        endpoint=endpoint,
        event_type=normalized_event.event_type,
        provider_event_id=normalized_event.provider_event_id,
        idempotency_key=normalized_event.idempotency_key,
        payload_hash=normalized_event.payload_hash,
        invoice_id=normalized_event.invoice_id,
        transaction_id=normalized_event.transaction_id,
        account_id=normalized_event.account_id,
        order_id=order.id if order else None,
        amount_minor=normalized_event.amount_minor,
        amount=normalized_event.amount,
        currency=normalized_event.currency,
        raw_payload=normalized_event.safe_payload,
        headers=normalized_event.safe_headers,
        status="failed" if normalized_event.error_message else "received",
        error_code=normalized_event.error_code,
        error_message=normalized_event.error_message,
        processed_at=datetime_now() if normalized_event.error_message else None,
    )
    db.add(event)
    db.flush()
    event_id = event.id
    db.commit()
    db.refresh(event)

    if not normalized_event.error_message:
        try:
            event = process_webhook_event(
                db,
                event_id=event_id,
                endpoint=endpoint,
                payload=normalized_event.safe_payload,
                invoice_id=normalized_event.invoice_id,
                transaction_id=normalized_event.transaction_id,
                amount_minor=normalized_event.amount_minor,
                currency=normalized_event.currency,
                idempotency_key=normalized_event.idempotency_key,
                account_id=normalized_event.account_id,
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

    if normalized_event.error_message:
        logger.warning(
            "cloudpayments_webhook_error endpoint=%s status=%s error=%s transaction_id=%s invoice_id=%s",
            endpoint,
            event.status,
            normalized_event.error_message,
            event.transaction_id,
            event.invoice_id,
        )

    if normalized_event.error_message == "invalid_cloudpayments_signature":
        raise HTTPException(
            status_code=400,
            detail=normalized_event.error_message,
        )

    return cloudpayments_adapter.webhook_event_response(
        endpoint=endpoint,
        error_code=event.error_code,
        event_status=event.status,
    )
