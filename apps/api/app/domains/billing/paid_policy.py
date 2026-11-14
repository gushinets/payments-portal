"""Pure paid eligibility and primary policy; no vendor codes or storage I/O."""

from dataclasses import dataclass
from enum import StrEnum

from app.core.settings import AppEnv
from app.domains.catalog.contracts import SourceProvenance
from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof, SubscriptionProof
from app.models import ExternalSubscriptionFinancialAccessStatus as Financial
from app.models import ExternalSubscriptionLifecycleStatus as Lifecycle


class PaidDecision(StrEnum):
    GRANT = "grant"
    DENY = "deny"
    KEEP = "keep"


class MeteringPolicy(StrEnum):
    CONFIGURED_ONLY = "configured_only"
    NONPRODUCTION = "nonproduction"

    @classmethod
    def for_environment(cls, environment: AppEnv) -> "MeteringPolicy":
        return cls.CONFIGURED_ONLY if environment == AppEnv.PRODUCTION else cls.NONPRODUCTION

    def permits(self, provenance: SourceProvenance | None) -> bool:
        return provenance in self.provenances

    @property
    def provenances(self) -> tuple[SourceProvenance, ...]:
        return (
            (SourceProvenance.CONFIGURED_SOURCE, SourceProvenance.SIMULATED)
            if self == self.NONPRODUCTION
            else (SourceProvenance.CONFIGURED_SOURCE,)
        )


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
