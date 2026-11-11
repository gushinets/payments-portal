"""Concrete durable billing execution contracts; no HTTP or provider vocabulary."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import TypedDict
from uuid import UUID


class WorkLane(StrEnum):
    URGENT = "urgent"
    NORMAL = "normal"
    LOCAL = "local"
    DELIVERY = "delivery"


class WorkAttemptOutcome(StrEnum):
    COMPLETED = "completed"
    PARKED = "parked"
    RETRY = "retry"
    REFUSED = "refused"
    FAILED = "failed"


class InvalidationFailureCode(StrEnum):
    AUTHENTICATION_FAILED = "kernel_invalidation_authentication_failed"
    SCOPE_FORBIDDEN = "kernel_invalidation_scope_forbidden"
    UNAVAILABLE = "kernel_invalidation_unavailable"
    CONTRACT_INVALID = "kernel_invalidation_contract_invalid"
    TIMEOUT = "kernel_invalidation_timeout"


class InvalidationSchedulingStatus(StrEnum):
    UNSCHEDULED = "unscheduled"


class InvalidationInspection(TypedDict):
    user_id: str
    pending_revision: int
    delivered_revision: int
    attempt_count: int
    last_error_classification: str | None
    # Operator output preserves raw retained queue states, including unknown
    # history. ANY-800 owns the legacy queue's storage/reader conversion.
    work_state: str
    next_attempt_at: str


@dataclass(frozen=True)
class WorkClaim:
    id: UUID
    kind: str
    reference: str
    owner: str
    generation: int
    started_at: datetime
    expires_at: datetime


@dataclass(frozen=True)
class InvalidationDelivery:
    tenant_id: str
    region: str
    user_id: UUID
    revision: int


@dataclass(frozen=True)
class RecoveryEscalation:
    """Allowlisted local references for one durable uncertain-create case."""

    operation_id: UUID
    operation_kind: str
    case_id: UUID
