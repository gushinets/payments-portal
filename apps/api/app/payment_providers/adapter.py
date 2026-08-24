from __future__ import annotations

from typing import Any, Protocol

from app.models import Order, PaymentProviderAccount
from app.payment_providers.contracts import (
    CancelRecurringSubscriptionRequest,
    CancelRecurringSubscriptionResult,
    CheckoutAction,
    CreateRecurringSubscriptionRequest,
    CreateRecurringSubscriptionResult,
    NormalizedPaymentEvent,
    RefundRequest,
    RefundResult,
    TransactionLookupRequest,
    TransactionLookupResult,
    UpdateRecurringSubscriptionRequest,
    UpdateRecurringSubscriptionResult,
)


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
