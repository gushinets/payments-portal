from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Order, Payment, Refund

CAPTURED_PAYMENT_STATUSES = {"succeeded", "refunded", "partially_refunded"}


def _get_first(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload and payload[key] not in (None, ""):
            return payload[key]
    return None


def record_refund(
    db: Session,
    *,
    order: Order,
    payment: Payment,
    amount_minor: int,
    currency: str,
    payload: dict[str, Any],
    now,
) -> Refund:
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
    if refund is not None:
        return refund

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
    db.add(refund)
    payment.refunded_amount_minor = max(payment.refunded_amount_minor, 0) + amount_minor
    payment.status = (
        "refunded"
        if payment.refunded_amount_minor >= payment.amount_minor
        else "partially_refunded"
    )
    db.add(payment)
    db.flush()
    _apply_order_refund_status(db, order)
    db.add(order)
    db.flush()
    return refund


def _apply_order_refund_status(db: Session, order: Order) -> None:
    if order.status == "canceled":
        return
    captured_payments = (
        db.query(Payment)
        .filter(
            Payment.order_id == order.id,
            Payment.status.in_(CAPTURED_PAYMENT_STATUSES),
        )
        .all()
    )
    captured_total = sum(max(payment.amount_minor, 0) for payment in captured_payments)
    refunded_total = sum(
        max(payment.refunded_amount_minor, 0) for payment in captured_payments
    )
    if refunded_total <= 0:
        return
    order.status = (
        "refunded"
        if captured_total > 0 and refunded_total >= captured_total
        else "partially_refunded"
    )
