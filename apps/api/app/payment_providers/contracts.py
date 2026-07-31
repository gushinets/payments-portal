from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

from app.models import Order, PaymentProviderAccount

CheckoutExperience = Literal["widget", "redirect", "embedded"]


@dataclass(frozen=True)
class CheckoutAction:
    provider: str
    experience: CheckoutExperience
    mode: str
    public_identifier: str | None
    amount_minor: int
    amount: float
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


class PaymentProviderAdapter(Protocol):
    provider_code: str

    def default_account_fields(self, *, tenant_id: str, region: str) -> dict[str, Any]:
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
        ...

    def webhook_success_response(self, event: NormalizedPaymentEvent) -> dict[str, Any]:
        ...
