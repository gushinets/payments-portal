"""Scoped pre-I/O witnesses and negative-only readback contracts."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.reconciliation_contracts import CommercialProof
from app.domains.purchases.contracts import FinancialOperation, FinancialRequestDocument, Purchase
from app.models import ExternalSubscriptionLifecycleStatus as Lifecycle

NEGATIVE_SCHEMA = "bound-source-negative:v1"


@dataclass(frozen=True)
class BoundReadbackSubject:
    purchase: Purchase
    customer: CustomerOpen
    tenant_id: str
    region: str
    legal_acceptance_event_id: UUID
    agreement_id: str
    agreement_key: str
    provider_subscription_id: str
    subscription_id: UUID
    fence: int
    supporting_observation_id: UUID | None
    captured_at: datetime
    deadline: datetime


@dataclass(frozen=True)
class OriginalCreateReadbackSubject:
    purchase: Purchase
    customer: CustomerOpen
    tenant_id: str
    region: str
    legal_acceptance_event_id: UUID
    agreement_id: str
    agreement_key: str
    operation: FinancialOperation
    saved_command: FinancialRequestDocument
    original_send_at: datetime
    original_deadline: datetime
    captured_at: datetime
    deadline: datetime
    # No canonical subscription/fence/support exists in this variant.


type ReadbackSubject = BoundReadbackSubject | OriginalCreateReadbackSubject


class NegativeBasis(StrEnum):
    AGREEMENT = "agreement"
    SUBSCRIPTION = "subscription"


@dataclass(frozen=True)
class BoundSourceNegative:
    agreement_id: str
    provider_subscription_id: str
    basis: NegativeBasis
    lifecycle: Lifecycle
    read_started_at: datetime
    read_finished_at: datetime
    reads: tuple[str, ...]
    reasons: tuple[str, ...]
    commercial: CommercialProof


@dataclass(frozen=True)
class ScopedReadbackFinding:
    subject: ReadbackSubject
    negative: BoundSourceNegative | None
    reasons: tuple[str, ...] = ()
    candidate_id: str | None = None


@dataclass(frozen=True)
class OriginalCreateProof:
    """Integration-proven unique original candidate and effective terms.

    Negative state or receipt alone cannot construct this proof. Operator use
    additionally requires its existing authorized full original proof.
    """

    provider_subscription_id: str
    agreement_id: str
    command: FinancialRequestDocument
    read_started_at: datetime
    read_finished_at: datetime
    reads: tuple[str, ...]
    negative: BoundSourceNegative | None


class ReadbackApplyResult(StrEnum):
    APPLIED_NEGATIVE = "APPLIED_NEGATIVE"
    HINT_ONLY = "HINT_ONLY"
    SUPERSEDED = "SUPERSEDED"


class ReadbackRecheck(Exception):
    """Internal decision: rollback/close the unit before one bounded reread."""
