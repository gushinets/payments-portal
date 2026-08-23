from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer

CheckoutExperience = Literal["widget", "redirect", "embedded"]


class OperationOutcome(StrEnum):
    """Итог выполнения операции на стороне провайдера."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RetryDisposition(StrEnum):
    """Признак, можно ли безопасно повторить запрос к провайдеру."""

    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"


class TransactionStatus(StrEnum):
    """Нормализованный статус платежной операции."""

    PENDING = "pending"
    AUTHORIZED = "authorized"
    SUCCEEDED = "succeeded"
    CANCELED = "canceled"
    FAILED = "failed"
    REFUNDED = "refunded"
    UNKNOWN = "unknown"


class RefundStatus(StrEnum):
    """Нормализованный статус возврата."""

    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"


class RecurringSubscriptionStatus(StrEnum):
    """Нормализованный статус регулярного списания."""

    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    ENDED = "ended"
    FAILED = "failed"
    UNKNOWN = "unknown"


class ProviderContractModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class CheckoutAction(ProviderContractModel):
    """Data returned to the client to start checkout with a payment provider."""

    provider: str
    experience: CheckoutExperience
    mode: str
    public_identifier: str | None
    amount_minor: int
    amount: Decimal
    currency: str
    merchant_order_id: str
    provider_invoice_id: str
    account_id: str
    description: str | None = None
    metadata: dict[str, Any] | None = None

    @field_serializer("amount", when_used="json")
    def serialize_amount(self, value: Decimal) -> float:
        return float(value)

    def as_response(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["metadata"] = self.metadata or {}
        return payload


class NormalizedPaymentEvent(ProviderContractModel):
    """Safe normalized representation of an incoming provider webhook event."""

    endpoint: str
    event_type: str
    provider_event_id: str | None
    idempotency_key: str
    payload_hash: str
    invoice_id: str | None
    transaction_id: str | None
    refund_id: str | None
    account_id: str | None
    amount_minor: int | None
    amount: Decimal | None
    currency: str | None
    safe_payload: dict[str, Any]
    safe_headers: dict[str, Any]
    verified: bool
    error_code: str | None = None
    error_message: str | None = None


class ProviderFailure(ProviderContractModel):
    """Safe error details returned from a provider operation."""

    code: str
    message_safe: str | None = None


class OperationResultMeta(ProviderContractModel):
    """Shared execution metadata for a server-side provider operation."""

    outcome: OperationOutcome
    retry_disposition: RetryDisposition
    idempotency_key: str | None = None
    failure: ProviderFailure | None = None


class TransactionLookupRequest(ProviderContractModel):
    """Identifiers and commercial facts used to reconcile a provider transaction."""

    provider_payment_id: str | None = None
    provider_invoice_id: str | None = None
    merchant_order_id: str | None = None
    expected_amount_minor: int = Field(gt=0)
    expected_currency: str = Field(min_length=3, max_length=3)


class TransactionLookupResult(ProviderContractModel):
    """Safe normalized result of a provider transaction lookup."""

    provider: str
    provider_account_id: str
    provider_payment_id: str | None
    provider_invoice_id: str | None
    merchant_order_id: str | None
    status: TransactionStatus
    amount_minor: int | None
    amount: Decimal | None
    currency: str | None
    meta: OperationResultMeta


class RefundRequest(ProviderContractModel):
    """Command payload for issuing a provider refund."""

    provider_payment_id: str
    amount_minor: int
    amount: Decimal
    currency: str
    reason: str | None = None
    idempotency_key: str | None = None


class RefundResult(ProviderContractModel):
    """Safe normalized result of a provider refund operation."""

    provider: str
    provider_account_id: str
    provider_payment_id: str
    provider_refund_id: str | None
    status: RefundStatus
    amount_minor: int
    amount: Decimal
    currency: str
    meta: OperationResultMeta


class CreateRecurringSubscriptionRequest(ProviderContractModel):
    """Command payload for creating a recurring provider subscription."""

    payment_method_reference: str
    account_id: str
    description: str
    amount_minor: int
    amount: Decimal
    currency: str
    interval_unit: str
    interval_count: int
    require_confirmation: bool
    email: str | None = None
    start_at: str | None = None
    max_periods: int | None = None
    idempotency_key: str | None = None


class CreateRecurringSubscriptionResult(ProviderContractModel):
    """Safe normalized result of recurring subscription creation."""

    provider: str
    provider_account_id: str
    provider_subscription_id: str | None
    account_id: str
    status: RecurringSubscriptionStatus
    amount_minor: int | None
    amount: Decimal | None
    currency: str | None
    interval_unit: str | None
    interval_count: int | None
    meta: OperationResultMeta


class UpdateRecurringSubscriptionRequest(ProviderContractModel):
    """Command payload for updating a recurring provider subscription."""

    provider_subscription_id: str
    description: str | None = None
    amount_minor: int | None = None
    amount: Decimal | None = None
    currency: str | None = None
    interval_unit: str | None = None
    interval_count: int | None = None
    require_confirmation: bool | None = None
    start_at: str | None = None
    email: str | None = None
    max_periods: int | None = None
    idempotency_key: str | None = None


class UpdateRecurringSubscriptionResult(ProviderContractModel):
    """Safe normalized result of recurring subscription update."""

    provider: str
    provider_account_id: str
    provider_subscription_id: str
    status: RecurringSubscriptionStatus
    amount_minor: int | None
    amount: Decimal | None
    currency: str | None
    interval_unit: str | None
    interval_count: int | None
    meta: OperationResultMeta


class CancelRecurringSubscriptionRequest(ProviderContractModel):
    """Command payload for canceling a recurring provider subscription."""

    provider_subscription_id: str
    idempotency_key: str | None = None


class CancelRecurringSubscriptionResult(ProviderContractModel):
    """Safe normalized result of recurring subscription cancellation."""

    provider: str
    provider_account_id: str
    provider_subscription_id: str
    status: RecurringSubscriptionStatus
    meta: OperationResultMeta
