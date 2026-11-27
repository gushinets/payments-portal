"""Provider-neutral proof handed from Integration to shared Application apply."""

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.paid_cycles import CalendarEvidence
from app.domains.billing.work_contracts import WorkAttemptOutcome
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.contracts import Purchase
from app.models import (
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)

if TYPE_CHECKING:
    from app.models import ExternalSubscription

RECONCILIATION_SCHEMA = "subscription-reconciliation:v2"
RECONCILIATION_READ_SCHEMAS = ("subscription-reconciliation:v1", RECONCILIATION_SCHEMA)


class CommercialProof(StrEnum):
    MATCH = "COMPLETE_MATCH"
    MISMATCH = "COMPLETE_MISMATCH"
    INCOMPLETE = "INCOMPLETE"


class IdentityProof(StrEnum):
    MATCH = "match"
    CONFLICT = "conflict"
    INCOMPLETE = "incomplete"


class SubscriptionLifecycleReason(StrEnum):
    WAITING = "waiting"
    INACTIVE = "inactive"
    ACTIVE = "active"
    FINANCIAL_BLOCK = "financial_block"
    ADMINISTRATIVE_BLOCK = "administrative_block"
    ENDED = "ended"


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

    def accepts_read(self, subscription: "ExternalSubscription", proof: "SubscriptionProof", now: datetime) -> bool:
        """Check a source read against the current locked subscription lease."""
        lease_expires_at = subscription.reconciliation_lease_expires_at
        return (
            subscription.reconciliation_lease_owner == self.owner
            and subscription.reconciliation_fencing_token == self.fence
            and lease_expires_at is not None
            and as_utc(lease_expires_at) > now
            and self.claimed_at <= proof.read_started_at <= proof.read_finished_at <= now
            and proof.read_finished_at < self.lease_expires_at
        )


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


class ReconciliationClaimBusy(BillingRefused):
    """Local contention prevented the attempt from acquiring its source lease."""


class ReconciliationWakeupHandled(Exception):
    """A covered or deferred Widget claim ended without a source read."""

    def __init__(self, outcome: WorkAttemptOutcome) -> None:
        self.outcome = outcome
        super().__init__(outcome)
