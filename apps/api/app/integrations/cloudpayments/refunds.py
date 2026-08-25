from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.errors import PaymentsError
from app.integrations.cloudpayments.account_validation import validate_provider_account_context
from app.integrations.cloudpayments.api_client import CloudPaymentsApiClient
from app.integrations.cloudpayments.operation_meta import (
    failed_meta,
    failed_meta_from_error,
    has_idempotency_key,
    idempotency_key_required_meta,
    succeeded_meta,
)
from app.integrations.cloudpayments.payload import get_first
from app.infrastructure.queries.subscriptions import get_subscription_for_order
from app.models import Order, Payment, PaymentProviderAccount, Refund
from app.payment_providers.contracts import RefundRequest, RefundResult, RefundStatus, RetryDisposition

CAPTURED_PAYMENT_STATUSES = {"succeeded", "refunded", "partially_refunded"}


def refund_payment(
    *,
    api_client: CloudPaymentsApiClient,
    provider_code: str,
    provider_account: PaymentProviderAccount,
    request: RefundRequest,
) -> RefundResult:
    account_error = validate_provider_account_context(
        provider_account=provider_account,
        provider_code=provider_code,
        configured_public_id=api_client.config.public_id,
    )
    if account_error is not None:
        return RefundResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_payment_id=request.provider_payment_id,
            provider_refund_id=None,
            status=RefundStatus.FAILED,
            amount_minor=request.amount_minor,
            amount=request.amount,
            currency=request.currency,
            meta=account_error,
        )

    if not has_idempotency_key(request.idempotency_key):
        return RefundResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_payment_id=request.provider_payment_id,
            provider_refund_id=None,
            status=RefundStatus.FAILED,
            amount_minor=request.amount_minor,
            amount=request.amount,
            currency=request.currency,
            meta=idempotency_key_required_meta(),
        )

    if provider_account.default_currency.strip().upper() != request.currency.strip().upper():
        return RefundResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_payment_id=request.provider_payment_id,
            provider_refund_id=None,
            status=RefundStatus.FAILED,
            amount_minor=request.amount_minor,
            amount=request.amount,
            currency=request.currency,
            meta=failed_meta(
                code="refund_currency_mismatch",
                message_safe="Refund currency does not match provider account default currency.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
                idempotency_key=request.idempotency_key,
            ),
        )

    if request.amount_minor <= 0 or request.amount <= Decimal("0"):
        return RefundResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_payment_id=request.provider_payment_id,
            provider_refund_id=None,
            status=RefundStatus.FAILED,
            amount_minor=request.amount_minor,
            amount=request.amount,
            currency=request.currency,
            meta=failed_meta(
                code="refund_amount_invalid",
                message_safe="Refund amount must be positive.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
                idempotency_key=request.idempotency_key,
            ),
        )

    provider_transaction_id = _provider_transaction_id(request.provider_payment_id)
    if provider_transaction_id is None:
        return RefundResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_payment_id=request.provider_payment_id,
            provider_refund_id=None,
            status=RefundStatus.FAILED,
            amount_minor=request.amount_minor,
            amount=request.amount,
            currency=request.currency,
            meta=failed_meta(
                code="cloudpayments_transaction_id_required",
                message_safe="CloudPayments refund requires provider_payment_id as TransactionId.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
                idempotency_key=request.idempotency_key,
            ),
        )

    expected_amount_minor = _amount_minor(request.amount)
    if expected_amount_minor is None or expected_amount_minor != request.amount_minor:
        return RefundResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_payment_id=request.provider_payment_id,
            provider_refund_id=None,
            status=RefundStatus.FAILED,
            amount_minor=request.amount_minor,
            amount=request.amount,
            currency=request.currency,
            meta=failed_meta(
                code="refund_amount_mismatch",
                message_safe="Refund amount and amount_minor must match.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
                idempotency_key=request.idempotency_key,
            ),
        )

    json_data = {"reason": request.reason} if request.reason else None
    try:
        response = api_client.refund(
            transaction_id=provider_transaction_id,
            amount=request.amount,
            json_data=json_data,
            idempotency_key=request.idempotency_key,
        )
    except PaymentsError as exc:
        return RefundResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_payment_id=request.provider_payment_id,
            provider_refund_id=None,
            status=RefundStatus.FAILED,
            amount_minor=request.amount_minor,
            amount=request.amount,
            currency=request.currency,
            meta=failed_meta_from_error(exc, idempotency_key=request.idempotency_key),
        )

    if response.model is None or response.model.transaction_id <= 0:
        return RefundResult(
            provider=provider_code,
            provider_account_id=str(provider_account.id),
            provider_payment_id=request.provider_payment_id,
            provider_refund_id=None,
            status=RefundStatus.FAILED,
            amount_minor=request.amount_minor,
            amount=request.amount,
            currency=request.currency,
            meta=failed_meta(
                code="payments_api_response_validation_error",
                message_safe="CloudPayments refund response is missing a transaction id.",
                retry_disposition=RetryDisposition.NON_RETRYABLE,
                idempotency_key=request.idempotency_key,
            ),
        )

    return RefundResult(
        provider=provider_code,
        provider_account_id=str(provider_account.id),
        provider_payment_id=request.provider_payment_id,
        provider_refund_id=str(response.model.transaction_id),
        status=RefundStatus.PENDING,
        amount_minor=request.amount_minor,
        amount=request.amount,
        currency=request.currency,
        meta=succeeded_meta(idempotency_key=request.idempotency_key),
    )


def record_refund(
    db: Session,
    *,
    order: Order,
    payment: Payment,
    amount_minor: int,
    currency: str,
    payload: dict[str, Any],
    now: datetime,
) -> Refund:
    provider_refund_id = get_first(
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
        reason=get_first(payload, "Reason", "reason"),
        requested_at=now,
        succeeded_at=now,
        metadata_={},
    )
    db.add(refund)
    payment.refunded_amount_minor = max(payment.refunded_amount_minor, 0) + amount_minor
    payment.status = "refunded" if payment.refunded_amount_minor >= payment.amount_minor else "partially_refunded"
    db.add(payment)
    db.flush()
    _apply_order_refund_status(db, order)
    db.add(order)
    db.flush()
    return refund


def _apply_order_refund_status(db: Session, order: Order) -> None:
    if order.status == "canceled" and get_subscription_for_order(db, order.id) is None:
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
    refunded_total = sum(max(payment.refunded_amount_minor, 0) for payment in captured_payments)
    if refunded_total <= 0:
        return
    order.status = "refunded" if captured_total > 0 and refunded_total >= captured_total else "partially_refunded"


def _provider_transaction_id(value: str | None) -> int | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized or not normalized.isdigit():
        return None
    return int(normalized)


def _amount_minor(amount: Decimal | None) -> int | None:
    if amount is None:
        return None
    scaled = amount * Decimal("100")
    if scaled != scaled.to_integral_value():
        return None
    return int(scaled)
