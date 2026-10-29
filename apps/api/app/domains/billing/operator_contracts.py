"""Explicit expectations for the two privileged, proof-based review resolutions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.purchases.contracts import Purchase
from app.domains.billing.reconciliation_contracts import SubscriptionProof

RESOLUTION_SCHEMA = "billing-operator-resolution:v1"


class ResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    user_id: UUID
    purchase_id: UUID
    case_id: UUID
    resolution: Literal["restore-original", "bind-original"]
    expected_case_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    expected_observation_id: UUID | None = None
    expected_reconciliation_fence: int | None = Field(default=None, ge=0)
    operation_id: UUID | None = None
    expected_operation_fence: UUID | None = None
    reason: str = Field(min_length=1, max_length=500, pattern=r"^[^\x00-\x1f\x7f]+$")
    reference: str = Field(min_length=1, max_length=300, pattern=r"^[^\x00-\x1f\x7f]+$")

    @model_validator(mode="after")
    def require_expectations(self) -> ResolutionRequest:
        restore = self.resolution == "restore-original"
        if restore:
            valid = (
                self.expected_observation_id is not None
                and self.expected_reconciliation_fence is not None
                and self.operation_id is None
                and self.expected_operation_fence is None
            )
        else:
            valid = (
                self.operation_id is not None
                and self.expected_operation_fence is not None
                and self.expected_observation_id is None
                and self.expected_reconciliation_fence is None
            )
        if not valid:
            raise ValueError("resolution expectations required")
        return self


@dataclass(frozen=True)
class ReviewResolution:
    request: ResolutionRequest
    principal: str
    purchase: Purchase
    operation_digest: str
    customer_digest: str
    saved_request: dict | None
    before: dict
    started_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class OriginalOperationProof:
    read_started_at: datetime
    read_finished_at: datetime
    request_digest: str
    subscription: SubscriptionProof | None = None
