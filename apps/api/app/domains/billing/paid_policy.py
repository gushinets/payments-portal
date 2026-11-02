"""Pure paid eligibility and primary policy; no vendor codes or storage I/O."""

from dataclasses import dataclass
from enum import StrEnum

from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof, SubscriptionProof
from app.models import ExternalSubscriptionFinancialAccessStatus as Financial
from app.models import ExternalSubscriptionLifecycleStatus as Lifecycle


class PaidDecision(StrEnum):
    GRANT = "grant"
    DENY = "deny"
    KEEP = "keep"


def paid_decision(proof: SubscriptionProof, *, review: bool = False) -> PaidDecision:
    if review or proof.identity == IdentityProof.CONFLICT:
        return PaidDecision.DENY
    if proof.identity == IdentityProof.MATCH:
        if proof.commercial == CommercialProof.MISMATCH or proof.financial == Financial.BLOCKED:
            return PaidDecision.DENY
        if proof.lifecycle in {Lifecycle.INACTIVE, Lifecycle.ENDED}:
            return PaidDecision.DENY
        if proof.complete and proof.commercial == CommercialProof.MATCH:
            if proof.lifecycle == Lifecycle.ACTIVE and proof.financial == Financial.ALLOWED:
                return PaidDecision.GRANT
    return PaidDecision.KEEP


class CandidateConclusion(StrEnum):
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class PrimaryCandidate:
    identity: str
    conclusion: CandidateConclusion


def first_primary(linked: str, candidates: tuple[PrimaryCandidate, ...], *, complete: bool) -> bool:
    """The caller unions persisted discovery with every local nonterminal source."""
    return (
        complete
        and bool(candidates)
        and all(item.conclusion != CandidateConclusion.INCOMPLETE for item in candidates)
        and [item.identity for item in candidates if item.conclusion == CandidateConclusion.ELIGIBLE] == [linked]
    )
