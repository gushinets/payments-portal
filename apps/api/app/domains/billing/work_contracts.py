"""Concrete durable billing execution contracts; no HTTP or provider vocabulary."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID


class WorkLane(StrEnum):
    URGENT = "urgent"
    NORMAL = "normal"
    LOCAL = "local"


@dataclass(frozen=True)
class WorkClaim:
    id: UUID
    kind: str
    reference: str
    owner: str
    generation: int
    started_at: datetime
    expires_at: datetime
