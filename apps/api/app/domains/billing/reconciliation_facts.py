"""Shared canonical subscription fact transitions for fenced source applications."""

from app.domains.billing.reconciliation_contracts import SubscriptionProof, IdentityProof, CommercialProof
from app.models import (
    ExternalSubscription,
    BillingStateObservation,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
)
from datetime import timedelta

SOURCE_TRUST = timedelta(hours=6)


def source_conflict(current: ExternalSubscription, proof: SubscriptionProof) -> str | None:
    customer_conflict = "customer_identity_conflict" in proof.reasons
    if proof.identity == IdentityProof.CONFLICT and (
        not customer_conflict or "subscription_identity_conflict" in proof.reasons
    ):
        return "subscription_identity_conflict"
    if current.lifecycle_status == Lifecycle.ENDED and proof.lifecycle not in {None, Lifecycle.ENDED}:
        return "subscription_terminal_revival_conflict"
    if proof.identity == IdentityProof.MATCH and proof.commercial == CommercialProof.MISMATCH:
        return "subscription_commercial_mismatch"
    return None


def apply_source_facts(
    current: ExternalSubscription,
    proof: SubscriptionProof,
    observation: BillingStateObservation,
    *,
    conflict: bool,
    known_review: bool,
    customer_conflict: bool,
) -> None:
    if (
        proof.identity == IdentityProof.MATCH
        and proof.financial == Financial.BLOCKED
        and current.lifecycle_status != Lifecycle.ENDED
    ):
        current.lifecycle_status = proof.lifecycle
    if conflict or known_review or customer_conflict:
        current.commercial_access_status = Commercial.INELIGIBLE
        current.financial_access_status = Financial.BLOCKED
        if conflict or customer_conflict or proof.complete:
            current.latest_observation_id = observation.observation_id
    elif proof.financial == Financial.BLOCKED:
        current.lifecycle_status = proof.lifecycle
        current.financial_access_status = Financial.BLOCKED
        current.latest_observation_id = observation.observation_id
    if proof.complete and not conflict and not known_review and not customer_conflict:
        current.lifecycle_status = proof.lifecycle
        current.financial_access_status = proof.financial
        current.commercial_access_status = Commercial.ELIGIBLE
        current.last_authoritative_read_at = proof.read_started_at
        current.projection_valid_until = proof.read_started_at + SOURCE_TRUST
        current.latest_observation_id = observation.observation_id
