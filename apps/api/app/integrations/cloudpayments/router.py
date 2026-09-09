from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import record_webhook, traced
from app.http_dependencies import get_raw_request_body
from app.integrations.cloudpayments.adapter import (
    SUPPORTED_ENDPOINTS,
    CloudPaymentsAdapter,
    get_cloudpayments_adapter,
)
from app.integrations.cloudpayments.processing import (
    datetime_now,
    fail_webhook_event,
    find_order,
    process_webhook_event,
    safe_normalization_error_message,
)
from app.models import PaymentWebhookEvent, PaymentWebhookEventStatus

router = APIRouter(prefix="/api/cloudpayments", tags=["cloudpayments"])
logger = logging.getLogger(__name__)


def _log_webhook_processed(event: PaymentWebhookEvent) -> None:
    structured: dict[str, str] = {
        "endpoint": event.endpoint,
        "status": event.status.value,
        "webhook_event_id": str(event.id),
    }
    if event.error_code is not None:
        structured["error_code"] = event.error_code
    if event.order_id is not None:
        structured["order_id"] = str(event.order_id)
    if event.payment_id is not None:
        structured["payment_id"] = str(event.payment_id)

    if event.status is PaymentWebhookEventStatus.FAILED:
        logger.warning("cloudpayments_webhook_processed", extra={"structured": structured})
    else:
        logger.info("cloudpayments_webhook_processed", extra={"structured": structured})


@router.post("/{endpoint}", response_model=None)
@traced("cloudpayments.webhook.process")
def receive_cloudpayments_webhook(
    endpoint: str,
    request: Request,
    raw_body: Annotated[bytes, Depends(get_raw_request_body)],
    db: Annotated[Session, Depends(get_db)],
    cloudpayments_adapter: Annotated[CloudPaymentsAdapter, Depends(get_cloudpayments_adapter)],
) -> dict[str, Any]:
    if endpoint not in SUPPORTED_ENDPOINTS:
        raise HTTPException(status_code=404, detail="Unsupported CloudPayments endpoint")

    normalized_event = cloudpayments_adapter.normalize_webhook_request(
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
        status=(
            PaymentWebhookEventStatus.FAILED if normalized_event.error_message else PaymentWebhookEventStatus.RECEIVED
        ),
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
            _log_webhook_processed(event)
            raise HTTPException(status_code=500, detail="webhook_normalization_failed") from exc

    record_webhook(endpoint, event.status)
    _log_webhook_processed(event)

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
