from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.integrations.cloudpayments.payload import (
    get_first,
    normalized_recurrent_status,
    parse_bool,
    parse_int,
)
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


def confirm_validation_error(
    db: Session,
    order: Order,
    *,
    transaction_id: str | None,
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
    if amount_minor <= 0:
        return "amount_mismatch"
    if currency is None:
        return "missing_currency"
    if currency.upper() != order.currency.upper():
        return "currency_mismatch"

    authorized_amount_minor = order.amount_minor
    if transaction_id:
        payment = (
            db.query(Payment)
            .filter(
                Payment.provider_account_id == order.provider_account_id,
                Payment.provider_payment_id == transaction_id,
            )
            .first()
        )
        if payment is not None:
            authorized_amount_minor = payment.amount_minor

    if amount_minor > authorized_amount_minor:
        return "amount_mismatch"
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
        "payment_already_canceled": "Refund notification rejected because payment is canceled",
        "order_already_refunded": "Payment notification ignored because order is refunded",
        "refund_amount_exceeds_payment": "Refund amount exceeds remaining payment amount",
        "payment_schema_mismatch": "Webhook type does not match the configured payment schema",
        "provider_account_not_found": "No enabled provider account found for webhook",
        "missing_subscription_id": "Webhook subscription id is missing",
        "missing_subscription_description": "Webhook subscription description is missing",
        "missing_subscription_email": "Webhook subscription email is missing",
        "missing_subscription_require_confirmation": "Webhook subscription confirmation mode is missing",
        "invalid_subscription_require_confirmation": "Webhook subscription confirmation mode is invalid",
        "missing_subscription_start_date": "Webhook subscription start date is missing",
        "missing_subscription_interval": "Webhook subscription interval is missing",
        "missing_subscription_period": "Webhook subscription period is missing",
        "invalid_subscription_period": "Webhook subscription period is invalid",
        "missing_subscription_status": "Webhook subscription status is missing",
        "invalid_subscription_status": "Webhook subscription status is invalid",
        "missing_subscription_successful_transactions_number": (
            "Webhook subscription successful transaction count is missing"
        ),
        "invalid_subscription_successful_transactions_number": (
            "Webhook subscription successful transaction count is invalid"
        ),
        "missing_subscription_failed_transactions_number": (
            "Webhook subscription failed transaction count is missing"
        ),
        "invalid_subscription_failed_transactions_number": (
            "Webhook subscription failed transaction count is invalid"
        ),
        "invalid_subscription_max_periods": "Webhook subscription maximum period count is invalid",
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
    if payment.status == "canceled":
        return "payment_already_canceled"
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


def recurrent_validation_error(
    payload: dict[str, Any],
    *,
    account_id: str | None,
    amount_minor: int | None,
    currency: str | None,
) -> str | None:
    normalized = payload.get("_normalized")
    if not isinstance(normalized, dict):
        normalized = {}
    subscription_id = normalized.get("subscription_id") or get_first(payload, "Id", "id")
    if not subscription_id:
        return "missing_subscription_id"
    if not account_id:
        return "missing_account_id"
    if get_first(payload, "Description", "description") is None:
        return "missing_subscription_description"
    if get_first(payload, "Email", "email") is None:
        return "missing_subscription_email"
    if amount_minor is None:
        return "missing_amount"
    if currency is None:
        return "missing_currency"
    require_confirmation = get_first(payload, "RequireConfirmation", "requireConfirmation")
    if require_confirmation is None:
        return "missing_subscription_require_confirmation"
    if parse_bool(require_confirmation) is None:
        return "invalid_subscription_require_confirmation"
    if get_first(payload, "StartDate", "startDate", "start_at") is None:
        return "missing_subscription_start_date"
    if get_first(payload, "Interval", "interval") is None:
        return "missing_subscription_interval"
    period = get_first(payload, "Period", "period")
    if period is None:
        return "missing_subscription_period"
    if parse_int(period) is None:
        return "invalid_subscription_period"
    raw_status = get_first(payload, "Status", "status")
    if raw_status is None:
        return "missing_subscription_status"
    status = normalized.get("status") or normalized_recurrent_status(raw_status)
    if status == "unknown":
        return "invalid_subscription_status"
    successful_transactions = get_first(
        payload,
        "SuccessfulTransactionsNumber",
        "successfulTransactionsNumber",
    )
    if successful_transactions is None:
        return "missing_subscription_successful_transactions_number"
    if parse_int(successful_transactions) is None:
        return "invalid_subscription_successful_transactions_number"
    failed_transactions = get_first(
        payload,
        "FailedTransactionsNumber",
        "failedTransactionsNumber",
    )
    if failed_transactions is None:
        return "missing_subscription_failed_transactions_number"
    if parse_int(failed_transactions) is None:
        return "invalid_subscription_failed_transactions_number"
    max_periods = get_first(payload, "MaxPeriods", "maxPeriods")
    if max_periods is not None and parse_int(max_periods) is None:
        return "invalid_subscription_max_periods"
    return None
