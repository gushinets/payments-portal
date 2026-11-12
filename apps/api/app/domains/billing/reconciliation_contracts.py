"""Provider-neutral proof handed from Integration to shared Application apply."""

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.paid_cycles import CalendarEvidence
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
class SubscriptionCandidateSubject:
    """Original possible-send candidate; no canonical local subscription yet."""

    purchase: Purchase
    customer: CustomerOpen
    agreement_id: str
    agreement_key: str
    provider_subscription_id: str


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
    established_calendar: CalendarEvidence | None = None


@dataclass(frozen=True)
class SubscriptionRelationship:
    """Observed point relationships; never authority to replace accepted bindings."""

    agreement_id: str
    tariff_id: int


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
    cycle: CalendarEvidence | None = None
    access_end_at: datetime | None = None
    point_relationship: SubscriptionRelationship | None = None

    def document(self) -> dict[str, object]:
        """Redacted JSON evidence shared by preparation and authoritative apply."""
        return {
            **asdict(self),
            "read_started_at": self.read_started_at.isoformat(),
            "read_finished_at": self.read_finished_at.isoformat(),
            "cycle": self.cycle.model_dump(mode="json") if self.cycle else None,
            "access_end_at": self.access_end_at.isoformat() if self.access_end_at else None,
        }


@dataclass(frozen=True)
class ReconciliationResult:
    """Returned only after the shared observation/fact transaction commits."""

    observation_id: UUID
    subject: ReconciliationSubject
    proof: SubscriptionProof
    purchase: Purchase
