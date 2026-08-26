"""Provider-neutral lifecycle command contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.time import utc_now
from app.domains.billing.enums import ProviderSubscriptionState


class LifecycleCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_idempotency_key: str = Field(min_length=1, max_length=255)
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_occurrence(self) -> LifecycleCommand:
        if self.occurred_at is None:
            self.occurred_at = utc_now()
        elif self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at_must_be_timezone_aware")
        return self


class StartTrialCommand(LifecycleCommand):
    tenant_id: str
    region: str
    user_id: uuid.UUID
    plan_id: uuid.UUID


class ActivatePaidPeriodCommand(LifecycleCommand):
    order_id: uuid.UUID
    payment_id: uuid.UUID
    webhook_event_id: uuid.UUID


class EnableAutomaticRenewalCommand(LifecycleCommand):
    subscription_id: uuid.UUID
    provider_account_id: uuid.UUID
    provider_subscription_id: str = Field(min_length=1, max_length=255)
    recurring_consent_acceptance_id: uuid.UUID


class ApplyRenewalPaymentCommand(LifecycleCommand):
    subscription_id: uuid.UUID
    succeeded: bool
    order_id: uuid.UUID
    payment_id: uuid.UUID
    webhook_event_id: uuid.UUID
    paid_at: datetime | None = None

    @field_validator("paid_at")
    @classmethod
    def require_aware_paid_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("paid_at_must_be_timezone_aware")
        return value


class ApplyProviderSubscriptionStateCommand(LifecycleCommand):
    subscription_id: uuid.UUID
    provider_state: ProviderSubscriptionState


class RequestCancellationCommand(LifecycleCommand):
    subscription_id: uuid.UUID


class ApplyRefundCommand(LifecycleCommand):
    order_id: uuid.UUID
    refund_id: uuid.UUID
    amount_minor: int = Field(gt=0)


class ExpireDueSubscriptionsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: datetime | None = None
    batch_size: int = Field(default=100, gt=0, le=1000)

    @model_validator(mode="after")
    def normalize_now(self) -> ExpireDueSubscriptionsCommand:
        if self.now is None:
            self.now = utc_now()
        elif self.now.tzinfo is None:
            raise ValueError("now_must_be_timezone_aware")
        return self
