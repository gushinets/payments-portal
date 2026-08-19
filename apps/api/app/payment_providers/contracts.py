from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

from app.models import PaymentProviderAccount

CheckoutExperience = Literal["widget", "redirect", "embedded"]


class PrepareCheckoutActionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    merchant_order_id: str
    provider_invoice_id: str
    account_id: str
    description: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CheckoutAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    metadata: dict[str, Any] = Field(default_factory=dict)


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

    def default_account_fields(self, *, tenant_id: str, region: str) -> dict[str, Any]: ...

    def prepare_checkout_action(
        self,
        *,
        provider_account: PaymentProviderAccount,
        checkout: PrepareCheckoutActionInput,
    ) -> CheckoutAction: ...

    def webhook_success_response(self, event: NormalizedPaymentEvent) -> dict[str, Any]: ...
