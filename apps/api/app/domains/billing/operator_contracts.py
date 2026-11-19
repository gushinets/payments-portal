"""Original-operation proof and explicit privileged review expectations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Annotated, Literal

if TYPE_CHECKING:
    from app.domains.purchases.inventory_contracts import InventoryResult
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, PositiveInt, model_validator

from app.domains.billing.contracts import CustomerOpen
from app.domains.purchases.contracts import FinancialOperation, Purchase
from app.domains.billing.reconciliation_contracts import SubscriptionProof

RESOLUTION_SCHEMA = "billing-operator-resolution:v1"
LATE_REASON = "purchase_late_external_object"
TERMINAL_SCHEMA = "purchase-terminal-resolution:v1"
TERMINAL_REASON = "purchase_terminal_resolution"
TERMINAL_AUDIT_REASONS = (TERMINAL_REASON, LATE_REASON)
ProviderId = Annotated[str, Field(pattern=r"^[1-9][0-9]{0,19}$")]


@dataclass
class AuditedObjects:
    confirmed: set[str] = field(default_factory=set)
    unrelated: set[str] = field(default_factory=set)

    def point_ids(self, operation: FinancialOperation) -> tuple[str, ...]:
        original = self.confirmed | ({operation.bound_id} if operation.bound_id else set())
        if original:
            return tuple(sorted(original))
        if operation.candidate_id and operation.candidate_id not in self.unrelated:
            return (operation.candidate_id,)
        return ()


def retained_agreement_ids(bound_id: str | None, audit: AuditedObjects | None) -> frozenset[str]:
    if bound_id is not None:
        return frozenset({bound_id})
    return frozenset(audit.confirmed) if audit is not None else frozenset()


class LateObjectDisposition(StrEnum):
    CLEAR = "clear"
    NEEDS_ORIGINAL_PROOF = "needs_original_proof"
    OPEN_ORIGINAL = "open_original"
    RELATIONSHIP_CONFLICT = "relationship_conflict"


class LateReviewRef(BaseModel):
    model_config = ConfigDict(frozen=True)
    purchase_intent_id: UUID
    review_case_id: UUID


@dataclass(frozen=True)
class LateObjectResult:
    disposition: LateObjectDisposition
    review: LateReviewRef | None = None


@dataclass(frozen=True)
class LateSubscriptionPoint:
    agreement_id: str
    tariff_id: int
    original_live_proven: bool = False


class LateObjectEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    purchase_intent_id: UUID
    operation_id: UUID
    external_object_id: ProviderId
    read_started_at: AwareDatetime
    latest_read_started_at: AwareDatetime
    latest_read_finished_at: AwareDatetime | None = Field(default=None, exclude_if=lambda value: value is None)
    observed_agreement_id: ProviderId | None = Field(default=None, exclude_if=lambda value: value is None)
    observed_tariff_id: PositiveInt | None = Field(default=None, exclude_if=lambda value: value is None)
    relationship_conflict: bool | None = Field(default=None, exclude_if=lambda value: value is None)
    bound_to_another_operation: bool = Field(default=False, exclude_if=lambda value: not value)

    @model_validator(mode="after")
    def ordered_reads(self) -> LateObjectEvidence:
        if not self.read_started_at <= self.latest_read_started_at <= self.latest_observation_at:
            raise ValueError("reversed late-object reads")
        return self

    @property
    def latest_observation_at(self) -> datetime:
        return self.latest_read_finished_at or self.latest_read_started_at

    def matches_relationship(
        self, earlier: LateObjectEvidence, *, legacy_open_agreement_ids: frozenset[str] = frozenset()
    ) -> bool:
        if legacy_open_agreement_ids and earlier.observed_tariff_id is None:
            # Enrich an open legacy case in place. A closed case needs an exact match.
            if earlier.observed_agreement_id is None:
                return len(legacy_open_agreement_ids) == 1 and self.observed_agreement_id in legacy_open_agreement_ids
            return earlier.observed_agreement_id == self.observed_agreement_id
        return (
            self.observed_agreement_id,
            self.observed_tariff_id,
            self.bound_to_another_operation,
        ) == (
            earlier.observed_agreement_id,
            earlier.observed_tariff_id,
            earlier.bound_to_another_operation,
        )


class ResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    user_id: UUID
    purchase_id: UUID
    case_id: UUID
    resolution: Literal["restore-original", "bind-original", "select-primary"]
    expected_case_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    expected_observation_id: UUID | None = None
    expected_reconciliation_fence: int | None = Field(default=None, ge=0)
    operation_id: UUID | None = None
    expected_operation_fence: UUID | None = None
    reason: str = Field(min_length=1, max_length=500, pattern=r"^[^\x00-\x1f\x7f]+$")
    reference: str = Field(min_length=1, max_length=300, pattern=r"^[^\x00-\x1f\x7f]+$")

    @model_validator(mode="after")
    def require_expectations(self) -> ResolutionRequest:
        restore = self.resolution in {"restore-original", "select-primary"}
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
    related_case_digests: tuple[tuple[UUID, str], ...] = ()
    inventory: InventoryResult | None = None


@dataclass(frozen=True)
class OriginalOperationProof:
    read_started_at: datetime
    read_finished_at: datetime
    request_digest: str
    customer: CustomerOpen
    subscription: SubscriptionProof | None = None
    agreement_close_date: str | None = None
