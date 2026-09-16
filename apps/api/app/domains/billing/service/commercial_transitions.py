"""Canonical provider-neutral Order, Payment, and Refund transitions."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.infrastructure.persistence.commercial import (
    establish_payment_identity,
    establish_refund_identity,
)
from app.infrastructure.queries.orders import get_order_by_id
from app.infrastructure.queries.payments import (
    get_payment_by_provider_identity,
    get_provider_account_by_id,
    get_refund_by_provider_identity,
    list_payments_for_order_with_statuses,
)
from app.models import (
    Order,
    OrderStatus,
    Payment,
    PaymentProviderAccount,
    PaymentStatus,
    Refund,
    RefundStatus,
)


class PaymentOutcome(StrEnum):
    AUTHORIZED = "authorized"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELED = "canceled"


class TransitionDisposition(StrEnum):
    APPLIED = "applied"
    DUPLICATE = "duplicate"
    IGNORED = "ignored"
    CONFLICT = "conflict"


class PaymentTransitionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: uuid.UUID
    provider: str = Field(min_length=1, max_length=255)
    provider_account_id: uuid.UUID
    provider_payment_id: str = Field(min_length=1, max_length=255)
    provider_invoice_id: str | None = Field(default=None, min_length=1, max_length=255)
    outcome: PaymentOutcome
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    occurred_at: datetime
    failure_code: str | None = Field(default=None, max_length=255)
    failure_message_safe: str | None = Field(default=None, max_length=2000)
    payment_method_type: str | None = Field(default=None, max_length=255)

    @field_validator("provider", "provider_payment_id", "provider_invoice_id")
    @classmethod
    def normalize_required_identifiers(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("identifier_must_not_be_blank")
        return normalized

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("failure_code", "failure_message_safe", "payment_method_type")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("occurred_at")
    @classmethod
    def require_aware_occurrence(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at_must_be_timezone_aware")
        return value


class RefundTransitionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    order_id: uuid.UUID
    provider: str = Field(min_length=1, max_length=255)
    provider_account_id: uuid.UUID
    provider_payment_id: str = Field(min_length=1, max_length=255)
    provider_refund_id: str = Field(min_length=1, max_length=255)
    amount_minor: int = Field(gt=0)
    currency: str = Field(min_length=3, max_length=3)
    occurred_at: datetime
    reason: str | None = Field(default=None, max_length=2000)

    @field_validator("provider", "provider_payment_id", "provider_refund_id")
    @classmethod
    def normalize_required_identifiers(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("identifier_must_not_be_blank")
        return normalized

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        return value.upper()

    @field_validator("reason")
    @classmethod
    def normalize_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip() or None

    @field_validator("occurred_at")
    @classmethod
    def require_aware_occurrence(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at_must_be_timezone_aware")
        return value


class CommercialTransitionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    disposition: TransitionDisposition
    order_id: uuid.UUID
    payment_id: uuid.UUID | None = None
    refund_id: uuid.UUID | None = None
    order_status: OrderStatus | None = None
    payment_status: PaymentStatus | None = None
    refund_status: RefundStatus | None = None
    reason_code: str | None = None
    order_became_paid: bool = False
    refund_created: bool = False


_PAYABLE_ORDER_STATUSES = frozenset({OrderStatus.PENDING_PAYMENT, OrderStatus.PAYMENT_FAILED})
_TERMINAL_ORDER_STATUSES = frozenset(
    {
        OrderStatus.PAID,
        OrderStatus.CANCELED,
        OrderStatus.PARTIALLY_REFUNDED,
        OrderStatus.REFUNDED,
    }
)
_SUPPORTED_ORDER_STATUSES = _PAYABLE_ORDER_STATUSES | _TERMINAL_ORDER_STATUSES
_CAPTURED_PAYMENT_STATUSES = frozenset(
    {
        PaymentStatus.SUCCEEDED,
        PaymentStatus.PARTIALLY_REFUNDED,
        PaymentStatus.REFUNDED,
    }
)


def _result(
    disposition: TransitionDisposition,
    *,
    order_id: uuid.UUID,
    order: Order | None = None,
    payment: Payment | None = None,
    refund: Refund | None = None,
    reason_code: str | None = None,
    order_became_paid: bool = False,
    refund_created: bool = False,
) -> CommercialTransitionResult:
    return CommercialTransitionResult(
        disposition=disposition,
        order_id=order_id,
        payment_id=payment.id if payment is not None else None,
        refund_id=refund.id if refund is not None else None,
        order_status=order.status if order is not None else None,
        payment_status=payment.status if payment is not None else None,
        refund_status=refund.status if refund is not None else None,
        reason_code=reason_code,
        order_became_paid=order_became_paid,
        refund_created=refund_created,
    )


def _provider_context_matches(
    order: Order,
    account: PaymentProviderAccount | None,
    *,
    provider: str,
    provider_account_id: uuid.UUID,
) -> bool:
    return bool(
        account is not None
        and order.provider == provider
        and order.provider_account_id == provider_account_id
        and account.id == provider_account_id
        and account.provider == provider
        and account.tenant_id == order.tenant_id
        and account.region == order.region
    )


def _payment_context_matches(payment: Payment, order: Order, command: PaymentTransitionCommand) -> bool:
    if (
        payment.order_id != order.id
        or payment.provider_account_id != order.provider_account_id
        or payment.provider != order.provider
        or payment.tenant_id != order.tenant_id
        or payment.region != order.region
        or payment.amount_minor != command.amount_minor
        or payment.currency.upper() != command.currency
    ):
        return False
    if (
        order.provider_invoice_id is not None
        and command.provider_invoice_id is not None
        and order.provider_invoice_id != command.provider_invoice_id
    ):
        return False
    if (
        payment.provider_invoice_id is not None
        and command.provider_invoice_id is not None
        and payment.provider_invoice_id != command.provider_invoice_id
    ):
        return False
    return not (
        order.provider_invoice_id is not None
        and payment.provider_invoice_id is not None
        and order.provider_invoice_id != payment.provider_invoice_id
    )


def _payment_disposition(payment: Payment, outcome: PaymentOutcome) -> TransitionDisposition:
    desired_status = PaymentStatus(outcome.value)
    if payment.status == PaymentStatus.CREATED:
        return TransitionDisposition.APPLIED
    if payment.status == PaymentStatus.AUTHORIZED:
        return (
            TransitionDisposition.DUPLICATE
            if desired_status == PaymentStatus.AUTHORIZED
            else TransitionDisposition.APPLIED
        )
    if payment.status == PaymentStatus.SUCCEEDED:
        return (
            TransitionDisposition.DUPLICATE
            if desired_status == PaymentStatus.SUCCEEDED
            else TransitionDisposition.IGNORED
        )
    if payment.status in {PaymentStatus.PARTIALLY_REFUNDED, PaymentStatus.REFUNDED}:
        return TransitionDisposition.IGNORED
    if payment.status == PaymentStatus.CANCELED:
        if desired_status == PaymentStatus.CANCELED:
            return TransitionDisposition.DUPLICATE
        if desired_status == PaymentStatus.AUTHORIZED:
            return TransitionDisposition.IGNORED
        return TransitionDisposition.CONFLICT
    if payment.status == PaymentStatus.FAILED:
        return (
            TransitionDisposition.DUPLICATE
            if desired_status == PaymentStatus.FAILED
            else TransitionDisposition.CONFLICT
        )
    return TransitionDisposition.CONFLICT


def _payment_disposition_reason(disposition: TransitionDisposition) -> str | None:
    if disposition == TransitionDisposition.IGNORED:
        return "stale_payment_fact"
    if disposition == TransitionDisposition.CONFLICT:
        return "payment_outcome_conflict"
    return None


def _apply_payment_outcome(payment: Payment, command: PaymentTransitionCommand) -> None:
    payment.status = PaymentStatus(command.outcome.value)
    if payment.provider_invoice_id is None:
        payment.provider_invoice_id = command.provider_invoice_id
    if payment.payment_method_type is None:
        payment.payment_method_type = command.payment_method_type
    if command.outcome == PaymentOutcome.AUTHORIZED:
        payment.authorized_at = payment.authorized_at or command.occurred_at
    elif command.outcome == PaymentOutcome.SUCCEEDED:
        payment.authorized_at = payment.authorized_at or command.occurred_at
        payment.captured_at = payment.captured_at or command.occurred_at
    elif command.outcome == PaymentOutcome.FAILED:
        payment.failed_at = payment.failed_at or command.occurred_at
        payment.failure_code = command.failure_code
        payment.failure_message_safe = command.failure_message_safe


def _apply_order_payment_outcome(order: Order, command: PaymentTransitionCommand) -> bool:
    if order.status not in _PAYABLE_ORDER_STATUSES:
        return False
    if command.outcome == PaymentOutcome.SUCCEEDED:
        order.status = OrderStatus.PAID
        order.paid_at = order.paid_at or command.occurred_at
        order.failed_at = None
        return True
    if command.outcome == PaymentOutcome.FAILED:
        order.status = OrderStatus.PAYMENT_FAILED
        order.failed_at = order.failed_at or command.occurred_at
    elif command.outcome == PaymentOutcome.CANCELED:
        order.status = OrderStatus.CANCELED
        order.canceled_at = order.canceled_at or command.occurred_at
    return False


def apply_payment_transition(db: Session, command: PaymentTransitionCommand) -> CommercialTransitionResult:
    order = get_order_by_id(db, command.order_id, for_update=True)
    if order is None:
        return _result(TransitionDisposition.CONFLICT, order_id=command.order_id, reason_code="order_not_found")
    account = get_provider_account_by_id(db, command.provider_account_id)
    if not _provider_context_matches(
        order,
        account,
        provider=command.provider,
        provider_account_id=command.provider_account_id,
    ):
        return _result(
            TransitionDisposition.CONFLICT,
            order_id=command.order_id,
            order=order,
            reason_code="provider_context_mismatch",
        )
    if (
        order.provider_invoice_id is not None
        and command.provider_invoice_id is not None
        and order.provider_invoice_id != command.provider_invoice_id
    ):
        return _result(
            TransitionDisposition.CONFLICT,
            order_id=command.order_id,
            order=order,
            reason_code="provider_invoice_mismatch",
        )

    payment = get_payment_by_provider_identity(
        db,
        provider_account_id=command.provider_account_id,
        provider_payment_id=command.provider_payment_id,
    )
    if payment is not None and payment.order_id == order.id:
        payment = get_payment_by_provider_identity(
            db,
            provider_account_id=command.provider_account_id,
            provider_payment_id=command.provider_payment_id,
            for_update=True,
        )
        assert payment is not None
    if payment is not None:
        if not _payment_context_matches(payment, order, command):
            return _result(
                TransitionDisposition.CONFLICT,
                order_id=command.order_id,
                order=order,
                payment=payment,
                reason_code="payment_context_mismatch",
            )
        disposition = _payment_disposition(payment, command.outcome)
        if disposition != TransitionDisposition.APPLIED:
            return _result(
                disposition,
                order_id=command.order_id,
                order=order,
                payment=payment,
                reason_code=_payment_disposition_reason(disposition),
            )
        if order.status not in _SUPPORTED_ORDER_STATUSES:
            return _result(
                TransitionDisposition.CONFLICT,
                order_id=command.order_id,
                order=order,
                payment=payment,
                reason_code="unsupported_order_status",
            )
    else:
        if order.status not in _SUPPORTED_ORDER_STATUSES:
            return _result(
                TransitionDisposition.CONFLICT,
                order_id=command.order_id,
                order=order,
                reason_code="unsupported_order_status",
            )
        if command.amount_minor != order.amount_minor:
            return _result(
                TransitionDisposition.CONFLICT,
                order_id=command.order_id,
                order=order,
                reason_code="amount_mismatch",
            )
        if command.currency != order.currency.upper():
            return _result(
                TransitionDisposition.CONFLICT,
                order_id=command.order_id,
                order=order,
                reason_code="currency_mismatch",
            )
        candidate = Payment(
            tenant_id=order.tenant_id,
            region=order.region,
            order_id=order.id,
            provider_account_id=order.provider_account_id,
            provider=order.provider,
            provider_payment_id=command.provider_payment_id,
            provider_invoice_id=command.provider_invoice_id or order.provider_invoice_id,
            status=PaymentStatus.CREATED,
            amount_minor=order.amount_minor,
            currency=order.currency,
            refunded_amount_minor=0,
            raw_summary={},
        )
        payment, created = establish_payment_identity(db, candidate)
        if not created:
            if payment.order_id == order.id:
                payment = get_payment_by_provider_identity(
                    db,
                    provider_account_id=command.provider_account_id,
                    provider_payment_id=command.provider_payment_id,
                    for_update=True,
                )
                assert payment is not None
            if not _payment_context_matches(payment, order, command):
                return _result(
                    TransitionDisposition.CONFLICT,
                    order_id=command.order_id,
                    order=order,
                    payment=payment,
                    reason_code="payment_identity_conflict",
                )
            disposition = _payment_disposition(payment, command.outcome)
            if disposition != TransitionDisposition.APPLIED:
                return _result(
                    disposition,
                    order_id=command.order_id,
                    order=order,
                    payment=payment,
                    reason_code=_payment_disposition_reason(disposition),
                )

    _apply_payment_outcome(payment, command)
    order_became_paid = _apply_order_payment_outcome(order, command)
    db.flush()
    return _result(
        TransitionDisposition.APPLIED,
        order_id=command.order_id,
        order=order,
        payment=payment,
        order_became_paid=order_became_paid,
    )


def _refund_context_matches(refund: Refund, order: Order, payment: Payment, command: RefundTransitionCommand) -> bool:
    return bool(
        refund.order_id == order.id
        and refund.payment_id == payment.id
        and refund.provider_account_id == order.provider_account_id
        and refund.tenant_id == order.tenant_id
        and refund.region == order.region
        and refund.amount_minor == command.amount_minor
        and refund.currency.upper() == command.currency
        and refund.status == RefundStatus.SUCCEEDED
    )


def _apply_aggregate_order_refund_status(db: Session, order: Order) -> None:
    if order.status == OrderStatus.CANCELED or order.status == OrderStatus.REFUNDED:
        return
    captured_payments = list_payments_for_order_with_statuses(
        db,
        order_id=order.id,
        statuses=_CAPTURED_PAYMENT_STATUSES,
    )
    captured_total = sum(payment.amount_minor for payment in captured_payments)
    refunded_total = sum(payment.refunded_amount_minor for payment in captured_payments)
    order.status = (
        OrderStatus.REFUNDED
        if captured_total > 0 and refunded_total >= captured_total
        else OrderStatus.PARTIALLY_REFUNDED
    )


def apply_refund_transition(db: Session, command: RefundTransitionCommand) -> CommercialTransitionResult:
    order = get_order_by_id(db, command.order_id, for_update=True)
    if order is None:
        return _result(TransitionDisposition.CONFLICT, order_id=command.order_id, reason_code="order_not_found")
    account = get_provider_account_by_id(db, command.provider_account_id)
    if not _provider_context_matches(
        order,
        account,
        provider=command.provider,
        provider_account_id=command.provider_account_id,
    ):
        return _result(
            TransitionDisposition.CONFLICT,
            order_id=command.order_id,
            order=order,
            reason_code="provider_context_mismatch",
        )

    payment = get_payment_by_provider_identity(
        db,
        provider_account_id=command.provider_account_id,
        provider_payment_id=command.provider_payment_id,
    )
    if payment is None or payment.order_id != order.id:
        return _result(
            TransitionDisposition.CONFLICT,
            order_id=command.order_id,
            order=order,
            payment=payment,
            reason_code="payment_context_mismatch",
        )
    payment = get_payment_by_provider_identity(
        db,
        provider_account_id=command.provider_account_id,
        provider_payment_id=command.provider_payment_id,
        for_update=True,
    )
    assert payment is not None
    if (
        payment.provider != command.provider
        or payment.provider_account_id != account.id
        or payment.tenant_id != order.tenant_id
        or payment.region != order.region
        or command.currency != payment.currency.upper()
    ):
        return _result(
            TransitionDisposition.CONFLICT,
            order_id=command.order_id,
            order=order,
            payment=payment,
            reason_code="payment_context_mismatch",
        )

    refund = get_refund_by_provider_identity(
        db,
        provider_account_id=command.provider_account_id,
        provider_refund_id=command.provider_refund_id,
    )
    if refund is not None and refund.payment_id == payment.id:
        refund = get_refund_by_provider_identity(
            db,
            provider_account_id=command.provider_account_id,
            provider_refund_id=command.provider_refund_id,
            for_update=True,
        )
        assert refund is not None
    if refund is not None:
        disposition = (
            TransitionDisposition.DUPLICATE
            if _refund_context_matches(refund, order, payment, command)
            else TransitionDisposition.CONFLICT
        )
        return _result(
            disposition,
            order_id=command.order_id,
            order=order,
            payment=payment,
            refund=refund,
            reason_code=("refund_identity_conflict" if disposition == TransitionDisposition.CONFLICT else None),
        )

    if order.status not in {
        OrderStatus.PAID,
        OrderStatus.PARTIALLY_REFUNDED,
        OrderStatus.REFUNDED,
        OrderStatus.CANCELED,
    }:
        return _result(
            TransitionDisposition.CONFLICT,
            order_id=command.order_id,
            order=order,
            payment=payment,
            reason_code="unsupported_order_status",
        )
    if payment.status not in {PaymentStatus.SUCCEEDED, PaymentStatus.PARTIALLY_REFUNDED}:
        return _result(
            TransitionDisposition.CONFLICT,
            order_id=command.order_id,
            order=order,
            payment=payment,
            reason_code="payment_not_refundable",
        )
    if payment.refunded_amount_minor + command.amount_minor > payment.amount_minor:
        return _result(
            TransitionDisposition.CONFLICT,
            order_id=command.order_id,
            order=order,
            payment=payment,
            reason_code="refund_amount_exceeds_payment",
        )

    candidate = Refund(
        tenant_id=order.tenant_id,
        region=order.region,
        order_id=order.id,
        payment_id=payment.id,
        provider_account_id=order.provider_account_id,
        provider_refund_id=command.provider_refund_id,
        status=RefundStatus.SUCCEEDED,
        amount_minor=command.amount_minor,
        currency=payment.currency,
        reason=command.reason,
        requested_at=command.occurred_at,
        succeeded_at=command.occurred_at,
        metadata_={},
    )
    refund, created = establish_refund_identity(db, candidate)
    if not created:
        if refund.payment_id == payment.id:
            refund = get_refund_by_provider_identity(
                db,
                provider_account_id=command.provider_account_id,
                provider_refund_id=command.provider_refund_id,
                for_update=True,
            )
            assert refund is not None
        disposition = (
            TransitionDisposition.DUPLICATE
            if _refund_context_matches(refund, order, payment, command)
            else TransitionDisposition.CONFLICT
        )
        return _result(
            disposition,
            order_id=command.order_id,
            order=order,
            payment=payment,
            refund=refund,
            reason_code=("refund_identity_conflict" if disposition == TransitionDisposition.CONFLICT else None),
        )

    payment.refunded_amount_minor += command.amount_minor
    payment.status = (
        PaymentStatus.REFUNDED
        if payment.refunded_amount_minor == payment.amount_minor
        else PaymentStatus.PARTIALLY_REFUNDED
    )
    _apply_aggregate_order_refund_status(db, order)
    db.flush()
    return _result(
        TransitionDisposition.APPLIED,
        order_id=command.order_id,
        order=order,
        payment=payment,
        refund=refund,
        refund_created=True,
    )
