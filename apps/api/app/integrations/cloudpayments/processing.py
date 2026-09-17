from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domains.billing.service import (
    ActivatePaidPeriodCommand,
    ApplyRefundCommand,
    activate_paid_period,
    apply_refund,
)
from app.domains.billing.service.commercial_transitions import (
    CommercialTransitionResult,
    PaymentOutcome,
    PaymentTransitionCommand,
    RefundTransitionCommand,
    TransitionDisposition,
    apply_payment_transition,
    apply_refund_transition,
)
from app.integrations.cloudpayments.payload import get_first
from app.integrations.cloudpayments.refunds import refund_lifecycle_applies
from app.integrations.cloudpayments.validation import (
    cancel_validation_error,
    check_order_state_error,
    commercial_field_length_error,
    confirm_validation_error,
    payment_validation_error,
    recurrent_validation_error,
    refund_validation_error,
    validation_error_message,
)
from app.integrations.cloudpayments.rules import (
    find_default_provider_account,
    payment_schema_error,
)
from app.models import (
    Order,
    PaymentWebhookEvent,
    PaymentWebhookEventStatus,
)

datetime_now = utc_now


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


def _payment_outcome(endpoint: str, payload: dict[str, Any]) -> PaymentOutcome:
    if endpoint == "pay" and str(get_first(payload, "Status", "status") or "").lower() == "authorized":
        return PaymentOutcome.AUTHORIZED
    return {
        "pay": PaymentOutcome.SUCCEEDED,
        "confirm": PaymentOutcome.SUCCEEDED,
        "fail": PaymentOutcome.FAILED,
        "cancel": PaymentOutcome.CANCELED,
    }[endpoint]


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _apply_transition_result(
    event: PaymentWebhookEvent,
    result: CommercialTransitionResult,
) -> None:
    event.payment_id = result.payment_id
    if result.disposition in {TransitionDisposition.APPLIED, TransitionDisposition.DUPLICATE}:
        event.status = PaymentWebhookEventStatus.PROCESSED
        return
    event.error_code = result.reason_code or "commercial_transition_conflict"
    event.error_message = validation_error_message(event.error_code)
    event.status = (
        PaymentWebhookEventStatus.IGNORED
        if result.disposition == TransitionDisposition.IGNORED
        else PaymentWebhookEventStatus.FAILED
    )


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
    event.status = PaymentWebhookEventStatus.FAILED
    event.error_code = error_code
    event.error_message = error_message[:1000]
    event.processed_at = datetime_now()
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


def process_webhook_event(
    db: Session,
    *,
    event_id: Any,
    endpoint: str,
    payload: dict[str, Any],
    invoice_id: str | None,
    transaction_id: str | None,
    refund_id: str | None,
    amount_minor: int | None,
    currency: str | None,
    idempotency_key: str,
    account_id: str | None = None,
) -> PaymentWebhookEvent:
    event = db.get(PaymentWebhookEvent, event_id)
    if event is None:
        raise RuntimeError("payment_webhook_event_missing")

    event.status = PaymentWebhookEventStatus.PROCESSING
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
                PaymentWebhookEvent.status.in_(
                    (
                        PaymentWebhookEventStatus.PROCESSED,
                        PaymentWebhookEventStatus.IGNORED,
                        PaymentWebhookEventStatus.DUPLICATE,
                    )
                ),
            )
            .first()
        )

    if existing_event is not None:
        event.status = PaymentWebhookEventStatus.DUPLICATE
        event.processed_at = datetime_now()
        event.order_id = existing_event.order_id
        event.payment_id = existing_event.payment_id
    elif endpoint == "recurrent" and event.provider_account_id is None:
        event.status = PaymentWebhookEventStatus.FAILED
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
            event.status = PaymentWebhookEventStatus.PROCESSED
        else:
            event.status = PaymentWebhookEventStatus.FAILED
            event.error_code = validation_error
            event.error_message = validation_error_message(validation_error)
        event.processed_at = datetime_now()
    elif order is None:
        event.status = PaymentWebhookEventStatus.FAILED
        event.error_code = "order_not_found"
        event.error_message = "No order found for provider invoice"
        event.processed_at = datetime_now()
    elif endpoint == "check":
        validation_error = None if transaction_id else "missing_transaction_id"
        validation_error = validation_error or payment_schema_error(
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
            event.status = PaymentWebhookEventStatus.PROCESSED
        else:
            event.status = PaymentWebhookEventStatus.FAILED
            event.error_code = validation_error
            event.error_message = validation_error_message(validation_error)
        event.processed_at = datetime_now()
    elif endpoint in {"pay", "fail", "confirm", "cancel"}:
        validation_error = None if transaction_id else "missing_transaction_id"
        validation_error = validation_error or commercial_field_length_error(
            transaction_id=transaction_id,
            failure_code=_optional_text(get_first(payload, "ReasonCode", "reasonCode")),
            failure_message=_optional_text(get_first(payload, "Reason", "reason")),
            payment_method=_optional_text(get_first(payload, "PaymentMethod", "paymentMethod")),
        )
        validation_error = validation_error or payment_schema_error(
            order=order,
            endpoint=endpoint,
            payload=payload,
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
            event.status = PaymentWebhookEventStatus.FAILED
            event.error_code = validation_error
            event.error_message = validation_error_message(validation_error)
        else:
            assert transaction_id is not None
            assert amount_minor is not None
            effective_currency = currency if currency is not None else order.currency
            occurred_at = datetime_now()
            result = apply_payment_transition(
                db,
                PaymentTransitionCommand(
                    order_id=order.id,
                    provider=order.provider,
                    provider_account_id=order.provider_account_id,
                    provider_payment_id=transaction_id,
                    provider_invoice_id=invoice_id,
                    outcome=_payment_outcome(endpoint, payload),
                    amount_minor=order.amount_minor if endpoint == "cancel" else amount_minor,
                    currency=effective_currency,
                    occurred_at=occurred_at,
                    failure_code=_optional_text(get_first(payload, "ReasonCode", "reasonCode")),
                    failure_message_safe=_optional_text(get_first(payload, "Reason", "reason")),
                    payment_method_type=_optional_text(get_first(payload, "PaymentMethod", "paymentMethod")),
                ),
            )
            event.currency = effective_currency
            _apply_transition_result(event, result)
            if result.order_became_paid:
                assert result.payment_id is not None
                activate_paid_period(
                    db,
                    ActivatePaidPeriodCommand(
                        order_id=order.id,
                        payment_id=result.payment_id,
                        webhook_event_id=event.id,
                        operation_idempotency_key=f"{idempotency_key}:activate",
                        occurred_at=occurred_at,
                    ),
                )
        event.processed_at = datetime_now()
    elif endpoint == "refund":
        if transaction_id is None:
            event.status = PaymentWebhookEventStatus.FAILED
            event.error_code = "payment_not_found"
            event.error_message = "No payment found for refund webhook"
            event.processed_at = datetime_now()
        elif refund_id is None:
            event.status = PaymentWebhookEventStatus.FAILED
            event.error_code = "missing_refund_id"
            event.error_message = validation_error_message(event.error_code)
            event.processed_at = datetime_now()
        else:
            validation_error = commercial_field_length_error(
                transaction_id=transaction_id,
                refund_id=refund_id,
                refund_reason=_optional_text(get_first(payload, "Reason", "reason")),
            )
            if validation_error is not None:
                event.status = PaymentWebhookEventStatus.FAILED
                event.error_code = validation_error
                event.error_message = validation_error_message(validation_error)
                event.processed_at = datetime_now()
                db.add(event)
                db.flush()
                return event
            validation_error = refund_validation_error(
                db,
                order,
                account_id=account_id,
                amount_minor=amount_minor,
                currency=currency,
            )
            if validation_error is not None:
                event.status = PaymentWebhookEventStatus.FAILED
                event.error_code = validation_error
                event.error_message = validation_error_message(validation_error)
                event.processed_at = datetime_now()
                db.add(event)
                db.flush()
                return event
            assert amount_minor is not None
            occurred_at = datetime_now()
            effective_currency = currency if currency is not None else order.currency
            result = apply_refund_transition(
                db,
                RefundTransitionCommand(
                    order_id=order.id,
                    provider=order.provider,
                    provider_account_id=order.provider_account_id,
                    provider_payment_id=transaction_id,
                    provider_refund_id=refund_id,
                    amount_minor=amount_minor,
                    currency=effective_currency,
                    occurred_at=occurred_at,
                    reason=_optional_text(get_first(payload, "Reason", "reason")),
                ),
            )
            _apply_transition_result(event, result)
            if result.refund_created and refund_lifecycle_applies(db, order, for_update=True):
                assert result.refund_id is not None
                apply_refund(
                    db,
                    ApplyRefundCommand(
                        order_id=order.id,
                        refund_id=result.refund_id,
                        amount_minor=amount_minor,
                        operation_idempotency_key=f"cloudpayments:refund:{result.refund_id}",
                        occurred_at=occurred_at,
                    ),
                )
            event.currency = effective_currency
            event.processed_at = datetime_now()

    db.add(event)
    db.flush()
    return event
