"""Provider-neutral proof handed from Integration to shared Application apply."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domains.billing.contracts import CustomerOpen
from app.domains.purchases.contracts import Purchase
from app.models import (
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)

RECONCILIATION_SCHEMA = "subscription-reconciliation:v1"


class CommercialProof(StrEnum):
    MATCH = "COMPLETE_MATCH"
    MISMATCH = "COMPLETE_MISMATCH"
    INCOMPLETE = "INCOMPLETE"


class IdentityProof(StrEnum):
    MATCH = "match"
    CONFLICT = "conflict"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class ReconciliationSubject:
    subscription_id: UUID
    purchase: Purchase
    customer: CustomerOpen
    agreement_id: str
    agreement_key: str
    provider_subscription_id: str
    owner: str
    fence: int
    lease_expires_at: datetime
    claimed_at: datetime


@dataclass(frozen=True)
class SubscriptionProof:
    read_started_at: datetime
    read_finished_at: datetime
    identity: IdentityProof
    commercial: CommercialProof
    lifecycle: Lifecycle | None
    financial: Financial | None
    calendar: dict[str, str | None]
    calendar_complete: bool
    complete: bool
    reasons: tuple[str, ...]
    # Names of successful point reads, never payloads or credentials.
    reads: tuple[str, ...]
