"""Concrete durable billing execution contracts; no HTTP or provider vocabulary."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class WorkLane(StrEnum):
    URGENT = "urgent"
    NORMAL = "normal"
    LOCAL = "local"
    DELIVERY = "delivery"


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
