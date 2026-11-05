"""One source-fact owner; no queue, evidence, authority or paid-state writes."""

from datetime import timedelta
from uuid import UUID

from app.domains.billing.reconciliation_contracts import IdentityProof, SubscriptionProof
from app.models import (
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)

SOURCE_TRUST = timedelta(hours=6)


def apply_negative_facts(sub: ExternalSubscription, lifecycle: Lifecycle, observation_id: UUID) -> None:
    """Restrict only. Terminal, ineligibility and the original trust stay intact."""
    if sub.lifecycle_status != Lifecycle.ENDED:
        sub.lifecycle_status = lifecycle
    sub.financial_access_status = Financial.BLOCKED
    sub.latest_observation_id = observation_id


def apply_source_facts(
    sub: ExternalSubscription,
    proof: SubscriptionProof,
    observation_id: UUID,
    *,
    conflict: bool,
    known_review: bool,
    customer_conflict: bool,
) -> None:
    negative = proof.identity == IdentityProof.MATCH and proof.financial == Financial.BLOCKED
    if negative:
        apply_negative_facts(sub, proof.lifecycle, observation_id)
    if conflict or known_review or customer_conflict:
        sub.commercial_access_status = Commercial.INELIGIBLE
        sub.financial_access_status = Financial.BLOCKED
        if conflict or customer_conflict or proof.complete:
            sub.latest_observation_id = observation_id
    elif proof.complete:
        # This branch alone can renew source trust or restore eligibility.
        sub.lifecycle_status = proof.lifecycle
        sub.financial_access_status = proof.financial
        sub.commercial_access_status = Commercial.ELIGIBLE
        sub.last_authoritative_read_at = proof.read_started_at
        sub.projection_valid_until = proof.read_started_at + SOURCE_TRUST
        sub.latest_observation_id = observation_id
