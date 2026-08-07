from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import Order, Payment, User


def money_mismatch(order: Order, *, amount_minor: int | None, currency: str | None) -> str | None:
    if amount_minor is None:
        return "missing_amount"
    if amount_minor != order.amount_minor:
        return "amount_mismatch"
    if currency is None:
        return "missing_currency"
    if currency.upper() != order.currency.upper():
        return "currency_mismatch"
    return None


def account_mismatch(
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


def order_expired(order: Order) -> bool:
    if order.expires_at is None:
        return False
    now = datetime.now(timezone.utc)
    expires_at = order.expires_at
    if expires_at.tzinfo is None:
        now = now.replace(tzinfo=None)
    return expires_at < now


def payment_validation_error(
    db: Session,
    order: Order,
    *,
    account_id: str | None,
    amount_minor: int | None,
    currency: str | None,
    require_account_id: bool = True,
    check_expiry: bool = False,
) -> str | None:
    account_error = account_mismatch(
        db,
        order,
        account_id=account_id,
        require_account_id=require_account_id,
    )
    if account_error is not None:
        return account_error
    money_error = money_mismatch(order, amount_minor=amount_minor, currency=currency)
    if money_error is not None:
        return money_error
    if check_expiry and order_expired(order):
        return "order_expired"
    return None


def check_order_state_error(order: Order) -> str | None:
    if order.status == "pending_payment":
        return None
    return "order_not_payable"


def validation_error_message(error_code: str) -> str:
    return {
        "missing_account_id": "Webhook account id is missing",
        "account_mismatch": "Webhook account id does not match order user",
        "missing_amount": "Webhook amount is missing",
        "amount_mismatch": "Webhook amount does not match order",
        "missing_currency": "Webhook currency is missing",
        "currency_mismatch": "Webhook currency does not match order",
        "order_expired": "Order is expired",
        "order_not_payable": "Order is not payable",
        "order_already_paid": "Payment capture notification ignored because order is already paid",
        "order_already_canceled": "Payment capture notification ignored because order is canceled",
        "refund_amount_exceeds_payment": "Refund amount exceeds remaining payment amount",
    }.get(error_code, "Webhook validation failed")


def cancel_validation_error(
    db: Session,
    order: Order,
    *,
    account_id: str | None,
    amount_minor: int | None,
    currency: str | None,
) -> str | None:
    account_error = account_mismatch(
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
    if currency is not None and currency.upper() != order.currency.upper():
        return "currency_mismatch"
    return None


def refund_validation_error(
    db: Session,
    order: Order,
    payment: Payment,
    *,
    account_id: str | None,
    amount_minor: int | None,
    currency: str | None,
) -> str | None:
    validation_error = cancel_validation_error(
        db,
        order,
        account_id=account_id,
        amount_minor=amount_minor,
        currency=currency,
    )
    if validation_error is not None:
        return validation_error
    assert amount_minor is not None
    if payment.refunded_amount_minor + amount_minor > payment.amount_minor:
        return "refund_amount_exceeds_payment"
    return None
