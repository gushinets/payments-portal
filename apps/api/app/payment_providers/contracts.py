from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

from app.models import Order, PaymentProviderAccount

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


class PaymentProviderConfigurationError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class CheckoutAction:
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

    def as_response(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "experience": self.experience,
            "mode": self.mode,
            "public_identifier": self.public_identifier,
            "amount_minor": self.amount_minor,
            "amount": self.amount,
            "currency": self.currency,
            "merchant_order_id": self.merchant_order_id,
            "provider_invoice_id": self.provider_invoice_id,
            "account_id": self.account_id,
            "description": self.description,
            "metadata": self.metadata or {},
        }


@dataclass(frozen=True)
class NormalizedPaymentEvent:
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


@dataclass(frozen=True)
class ProviderFailure:
    """Safe error details returned from a provider operation."""

    code: str
    message_safe: str | None = None


@dataclass(frozen=True)
class OperationResultMeta:
    """Shared execution metadata for a server-side provider operation."""

    outcome: OperationOutcome
    retry_disposition: RetryDisposition
    idempotency_key: str | None = None
    failure: ProviderFailure | None = None


@dataclass(frozen=True)
class TransactionLookupRequest:
    """Identifiers used to find and reconcile a provider transaction."""

    provider_account_id: str
    provider_payment_id: str | None = None
    provider_invoice_id: str | None = None
    merchant_order_id: str | None = None


@dataclass(frozen=True)
class TransactionLookupResult:
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


@dataclass(frozen=True)
class RefundRequest:
    """Command payload for issuing a provider refund."""

    provider_account_id: str
    provider_payment_id: str
    amount_minor: int
    amount: Decimal
    currency: str
    reason: str | None = None
    idempotency_key: str | None = None


@dataclass(frozen=True)
class RefundResult:
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


@dataclass(frozen=True)
class CreateRecurringSubscriptionRequest:
    """Command payload for creating a recurring provider subscription."""

    provider_account_id: str
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


@dataclass(frozen=True)
class CreateRecurringSubscriptionResult:
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


@dataclass(frozen=True)
class UpdateRecurringSubscriptionRequest:
    """Command payload for updating a recurring provider subscription."""

    provider_account_id: str
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


@dataclass(frozen=True)
class UpdateRecurringSubscriptionResult:
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


@dataclass(frozen=True)
class CancelRecurringSubscriptionRequest:
    """Command payload for canceling a recurring provider subscription."""

    provider_account_id: str
    provider_subscription_id: str
    idempotency_key: str | None = None


@dataclass(frozen=True)
class CancelRecurringSubscriptionResult:
    """Safe normalized result of recurring subscription cancellation."""

    provider: str
    provider_account_id: str
    provider_subscription_id: str
    status: RecurringSubscriptionStatus
    meta: OperationResultMeta


class PaymentProviderAdapter(Protocol):
    """Provider-neutral contract for server-side payment operations."""

    provider_code: str

    def default_account_fields(self, *, tenant_id: str, region: str) -> dict[str, Any]:
        """Return safe default fields for a provider account record."""
        ...

    def prepare_checkout_action(
        self,
        *,
        provider_account: PaymentProviderAccount,
        order: Order,
        account_id: str,
        description: str | None,
        metadata: dict[str, Any],
    ) -> CheckoutAction:
        """Build the client-facing checkout action for an order."""
        ...

    def lookup_transaction(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: TransactionLookupRequest,
    ) -> TransactionLookupResult:
        """Look up and normalize provider transaction state."""
        ...

    def refund_payment(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: RefundRequest,
    ) -> RefundResult:
        """Issue a refund through the provider and normalize the result."""
        ...

    def create_recurring_subscription(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: CreateRecurringSubscriptionRequest,
    ) -> CreateRecurringSubscriptionResult:
        """Create a recurring subscription and normalize the result."""
        ...

    def update_recurring_subscription(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: UpdateRecurringSubscriptionRequest,
    ) -> UpdateRecurringSubscriptionResult:
        """Update a recurring subscription and normalize the result."""
        ...

    def cancel_recurring_subscription(
        self,
        *,
        provider_account: PaymentProviderAccount,
        request: CancelRecurringSubscriptionRequest,
    ) -> CancelRecurringSubscriptionResult:
        """Cancel a recurring subscription and normalize the result."""
        ...

    def webhook_success_response(self, event: NormalizedPaymentEvent) -> dict[str, Any]:
        """Build the provider-specific success response for a webhook event."""
        ...
