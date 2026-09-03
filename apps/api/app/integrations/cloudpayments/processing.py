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
from app.integrations.cloudpayments.payload import get_first
from app.integrations.cloudpayments.processing_support import (
    TERMINAL_ORDER_STATUSES,
    TERMINAL_PAYMENT_STATUSES,
    parse_data as _parse_data,
    safe_summary as _safe_summary,
    terminal_order_event_error_code as _terminal_order_event_error_code,
)
from app.integrations.cloudpayments.validation import (
    cancel_validation_error,
    check_order_state_error,
    confirm_validation_error,
    payment_validation_error,
    recurrent_validation_error,
    refund_validation_error,
    validation_error_message,
)
from app.integrations.cloudpayments.refunds import record_refund, refund_lifecycle_applies
from app.integrations.cloudpayments.rules import (
    find_default_provider_account,
    payment_schema_error,
)
from app.models import (
    Order,
    OrderStatus,
    Payment,
    PaymentStatus,
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
    payload: dict[str, Any],
    update_order_status: bool = True,
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
            status=PaymentStatus.CREATED,
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
            payment.status = PaymentStatus.AUTHORIZED
            payment.authorized_at = payment.authorized_at or now
    elif endpoint in {"pay", "confirm"}:
        if previous_payment_status not in TERMINAL_PAYMENT_STATUSES:
            payment.status = PaymentStatus.SUCCEEDED
            payment.authorized_at = payment.authorized_at or now
            payment.captured_at = payment.captured_at or now
            if update_order_status:
                order.status = OrderStatus.PAID
                order.paid_at = order.paid_at or now
                order.failed_at = None
    elif endpoint == "fail":
        if previous_payment_status not in TERMINAL_PAYMENT_STATUSES:
            payment.status = PaymentStatus.FAILED
            payment.failed_at = payment.failed_at or now
            payment.failure_code = str(get_first(payload, "ReasonCode", "reasonCode") or "")
            payment.failure_message_safe = get_first(payload, "Reason", "reason")
        if order.status not in TERMINAL_ORDER_STATUSES:
            order.status = OrderStatus.PAYMENT_FAILED
            order.failed_at = order.failed_at or now
    elif endpoint == "cancel":
        if previous_payment_status not in TERMINAL_PAYMENT_STATUSES:
            payment.status = PaymentStatus.CANCELED
        if order.status not in TERMINAL_ORDER_STATUSES:
            order.status = OrderStatus.CANCELED
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
    event.status = PaymentWebhookEventStatus.FAILED
    event.error_code = error_code
    event.error_message = error_message[:1000]
    event.processed_at = datetime_now()
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


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
            event.status = PaymentWebhookEventStatus.PROCESSED
            event.processed_at = datetime_now()
            return True
        event.payment_id = payment.id
        event.status = PaymentWebhookEventStatus.IGNORED
        event.error_code = _terminal_order_event_error_code(order)
        event.error_message = validation_error_message(event.error_code)
        event.processed_at = datetime_now()
        return True
    if not transaction_id:
        event.payment_id = None
        event.status = PaymentWebhookEventStatus.IGNORED
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
    event.status = PaymentWebhookEventStatus.PROCESSED
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
    event.status = PaymentWebhookEventStatus.IGNORED
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
            event.status = PaymentWebhookEventStatus.FAILED
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
            event.status = PaymentWebhookEventStatus.PROCESSED
            if payment.status == PaymentStatus.SUCCEEDED:
                activate_paid_period(
                    db,
                    ActivatePaidPeriodCommand(
                        order_id=order.id,
                        payment_id=payment.id,
                        webhook_event_id=event.id,
                        operation_idempotency_key=f"{idempotency_key}:activate",
                        occurred_at=datetime_now(),
                    ),
                )
        event.processed_at = datetime_now()
    elif endpoint == "refund":
        payment = _find_payment(db, order=order, transaction_id=transaction_id)
        if payment is None:
            event.status = PaymentWebhookEventStatus.FAILED
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
                event.status = PaymentWebhookEventStatus.FAILED
                event.error_code = validation_error
                event.error_message = validation_error_message(validation_error)
                event.processed_at = datetime_now()
                db.add(event)
                db.flush()
                return event
            assert amount_minor is not None
            refund = record_refund(
                db,
                order=order,
                payment=payment,
                amount_minor=amount_minor,
                currency=currency if currency is not None else payment.currency,
                payload=payload,
                now=datetime_now(),
            )
            if refund_lifecycle_applies(db, order, for_update=True):
                apply_refund(
                    db,
                    ApplyRefundCommand(
                        order_id=order.id,
                        refund_id=refund.id,
                        amount_minor=refund.amount_minor,
                        operation_idempotency_key=f"cloudpayments:refund:{refund.id}",
                        occurred_at=datetime_now(),
                    ),
                )
            event.currency = currency if currency is not None else payment.currency
            event.status = PaymentWebhookEventStatus.PROCESSED
            event.processed_at = datetime_now()

    db.add(event)
    db.flush()
    return event
