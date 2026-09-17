"""Provider-neutral commercial transition contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import OrderStatus, PaymentStatus, RefundStatus


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
