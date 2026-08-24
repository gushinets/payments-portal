from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

from app.integrations.cloudpayments.payload import normalized_recurrent_status, parse_bool, parse_int
from app.payment_providers.contracts import NormalizedPaymentEvent

EVENT_TYPES_BY_ENDPOINT = {
    "check": "payment.check",
    "pay": "payment.succeeded",
    "fail": "payment.failed",
    "refund": "payment.refunded",
    "confirm": "payment.succeeded",
    "cancel": "payment.canceled",
    "recurrent": "subscription.updated",
}


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _without_empty_values(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


def cloudpayments_event_idempotency_key(
    endpoint: str,
    provider_event_id: str | None,
    invoice_id: str | None,
    transaction_id: str | None,
    refund_id: str | None,
    payload_hash: str,
) -> str:
    if endpoint == "recurrent":
        return f"cloudpayments:recurrent:payload:{payload_hash}"
    if provider_event_id:
        return f"cloudpayments:event:{provider_event_id}"
    if endpoint == "refund" and refund_id:
        return f"cloudpayments:refund:{refund_id}"
    if transaction_id:
        return f"cloudpayments:{endpoint}:transaction:{transaction_id}"
    if invoice_id:
        return f"cloudpayments:{endpoint}:invoice:{invoice_id}:{payload_hash}"
    return f"cloudpayments:{endpoint}:payload:{payload_hash}"


class CloudPaymentsWebhookPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_event_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("EventId", "NotificationId", "Id"),
    )
    invoice_id: str | None = Field(default=None, validation_alias="InvoiceId")
    transaction_id: str | None = Field(default=None, validation_alias="TransactionId")
    payment_transaction_id: str | None = Field(default=None, validation_alias="PaymentTransactionId")
    refund_id: str | None = Field(default=None, validation_alias="RefundId")
    account_id: str | None = Field(default=None, validation_alias="AccountId")
    currency: str | None = Field(default=None, validation_alias="Currency")
    status: str | None = Field(default=None, validation_alias="Status")
    subscription_id: str | None = Field(default=None, validation_alias="Id")
    email: str | None = Field(default=None, validation_alias="Email")
    description: str | None = Field(default=None, validation_alias="Description")
    require_confirmation: bool | None = Field(default=None, validation_alias="RequireConfirmation")
    start_at: str | None = Field(default=None, validation_alias="StartDate")
    interval: str | None = Field(default=None, validation_alias="Interval")
    period: int | None = Field(default=None, validation_alias="Period")
    successful_payments_count: int | None = Field(default=None, validation_alias="SuccessfulTransactionsNumber")
    failed_payments_count: int | None = Field(default=None, validation_alias="FailedTransactionsNumber")
    max_periods: int | None = Field(default=None, validation_alias="MaxPeriods")
    last_transaction_at: str | None = Field(default=None, validation_alias="LastTransactionDate")
    next_transaction_at: str | None = Field(default=None, validation_alias="NextTransactionDate")

    @field_validator(
        "provider_event_id",
        "invoice_id",
        "transaction_id",
        "payment_transaction_id",
        "refund_id",
        "account_id",
        "currency",
        "status",
        "subscription_id",
        "email",
        "description",
        "start_at",
        "last_transaction_at",
        "next_transaction_at",
        mode="before",
    )
    @classmethod
    def normalize_optional_string(cls, value: Any) -> str | None:
        return _optional_string(value)

    @field_validator("status", mode="after")
    @classmethod
    def normalize_status(cls, value: str | None) -> str | None:
        return value.lower() if value is not None else None

    @field_validator("interval", mode="before")
    @classmethod
    def normalize_interval(cls, value: Any) -> str | None:
        normalized = _optional_string(value)
        return normalized.lower() if normalized is not None else None

    @field_validator(
        "period",
        "successful_payments_count",
        "failed_payments_count",
        "max_periods",
        mode="before",
    )
    @classmethod
    def normalize_optional_int(cls, value: Any) -> int | None:
        return parse_int(value)

    @field_validator("require_confirmation", mode="before")
    @classmethod
    def normalize_optional_bool(cls, value: Any) -> bool | None:
        return parse_bool(value)

    def to_normalized_event(
        self,
        *,
        endpoint: str,
        payload_hash: str,
        safe_payload: dict[str, Any],
        safe_headers: dict[str, Any],
        verified: bool,
        amount_minor: int | None,
        amount: Decimal | None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> NormalizedPaymentEvent:
        transaction_id = self.transaction_id
        refund_id = self.refund_id
        if endpoint == "refund":
            refund_id = refund_id or transaction_id
            transaction_id = self.payment_transaction_id or transaction_id

        normalized_safe_payload = dict(safe_payload)
        if endpoint == "recurrent":
            normalized_safe_payload["_normalized"] = _without_empty_values(
                {
                    "subscription_id": self.subscription_id,
                    "account_id": self.account_id,
                    "email": self.email,
                    "description": self.description,
                    "status": normalized_recurrent_status(self.status),
                    "amount_minor": amount_minor,
                    "currency": self.currency,
                    "require_confirmation": self.require_confirmation,
                    "start_at": self.start_at,
                    "interval": self.interval,
                    "period": self.period,
                    "successful_payments_count": self.successful_payments_count,
                    "failed_payments_count": self.failed_payments_count,
                    "max_periods": self.max_periods,
                    "last_transaction_at": self.last_transaction_at,
                    "next_transaction_at": self.next_transaction_at,
                }
            )

        event_type = (
            "payment.authorized"
            if endpoint == "pay" and self.status == "authorized"
            else EVENT_TYPES_BY_ENDPOINT.get(endpoint, endpoint)
        )

        return NormalizedPaymentEvent(
            endpoint=endpoint,
            event_type=event_type,
            provider_event_id=self.provider_event_id,
            idempotency_key=cloudpayments_event_idempotency_key(
                endpoint,
                self.provider_event_id,
                self.invoice_id,
                transaction_id,
                refund_id,
                payload_hash,
            ),
            payload_hash=payload_hash,
            invoice_id=self.invoice_id,
            transaction_id=transaction_id,
            refund_id=refund_id,
            account_id=self.account_id,
            amount_minor=amount_minor,
            amount=amount,
            currency=self.currency,
            safe_payload=normalized_safe_payload,
            safe_headers=safe_headers,
            verified=verified,
            error_code=error_code,
            error_message=error_message,
        )
