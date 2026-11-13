"""Normalized inventory facts and pure product-impact calculation."""

from dataclasses import dataclass, field
from collections import Counter
from datetime import datetime
from uuid import UUID

from app.domains.billing.discovery import DiscoveredCandidate, ProductDiscovery
from app.domains.billing.paid_policy import CandidateConclusion
from app.domains.purchases.contracts import Purchase
from app.models import ExternalCreateOperationKind as Kind


@dataclass(frozen=True)
class InventoryRelationship:
    identity: str
    agreement_id: str
    tariff_id: int | None


def implicated_products(
    purchases: tuple[Purchase, ...], identity: str, agreement_id: str, tariff_id: int | None
) -> frozenset[str]:
    """One owner for accepted tariff, agreement and permanent binding implications."""
    return frozenset(
        purchase.accepted.selection.product_id
        for purchase in purchases
        if purchase.accepted.selection.tariff_id == tariff_id
        or any(
            op.bound_id is not None
            and (
                (op.kind == Kind.SUBSCRIPTION and op.bound_id == identity)
                or (op.kind == Kind.AGREEMENT and op.bound_id == agreement_id)
            )
            for op in purchase.operations
        )
    )


def project_inventory(
    purchases: tuple[Purchase, ...],
    relationships: tuple[InventoryRelationship, ...],
    candidates: tuple[DiscoveredCandidate, ...],
    incomplete: frozenset[str],
    conflicts: frozenset[UUID],
    started_at: datetime,
    finished_at: datetime,
    scopes: dict[str, tuple[UUID | None, datetime | None]],
    *,
    failed: bool,
) -> tuple[ProductDiscovery, ...]:
    """Reduce one scan without dropping earlier implications or consulting storage."""
    known = {candidate.identity: candidate for candidate in candidates}
    identities = sorted({relation.identity for relation in relationships} | set(known))
    impacts: dict[str, set[str]] = {}
    agreements: dict[str, str] = {}
    for relation in relationships:
        impacts.setdefault(relation.identity, set()).update(
            implicated_products(purchases, relation.identity, relation.agreement_id, relation.tariff_id)
        )
        agreements.setdefault(relation.identity, relation.agreement_id)
    owners = {
        op.bound_id: purchase
        for purchase in purchases
        for op in purchase.operations
        if op.kind == Kind.SUBSCRIPTION and op.bound_id is not None
    }
    output = []
    for product in sorted({purchase.accepted.selection.product_id for purchase in purchases}):
        observed = []
        uncertain = False
        for identity in identities:
            if product not in impacts.get(identity, set()):
                continue
            candidate = known.get(identity)
            if candidate is None:
                candidate = DiscoveredCandidate(
                    identity=identity, agreement_id=agreements[identity], conclusion=CandidateConclusion.INCOMPLETE
                )
            owner = owners.get(identity)
            if (
                owner is not None
                and owner.accepted.selection.product_id != product
                and identity not in incomplete
                and candidate.conclusion != CandidateConclusion.INCOMPLETE
            ):
                # A conclusively normalized permanent sibling is already owned.
                # Shared commercial tariffs do not duplicate its primary candidacy.
                continue
            uncertain |= identity in incomplete
            observed.append(candidate)
        conflict = any(item.id in conflicts and item.accepted.selection.product_id == product for item in purchases)
        primary, retired = scopes.get(product, (None, None))
        output.append(
            ProductDiscovery(
                product_id=product,
                read_started_at=started_at,
                read_finished_at=finished_at,
                primary_subscription_id=primary,
                primary_retired_at=retired,
                complete=not failed
                and not conflict
                and not uncertain
                and all(item.conclusion != CandidateConclusion.INCOMPLETE for item in observed),
                candidates=tuple(observed),
            )
        )
    return tuple(output)


@dataclass
class InventoryFacts:
    """One scan's append-only implications and explicit candidate conclusions."""

    purchases: tuple[Purchase, ...]
    relationships: dict[InventoryRelationship, None] = field(default_factory=dict)
    candidates: dict[str, DiscoveredCandidate] = field(default_factory=dict)
    incomplete: set[str] = field(default_factory=set)
    failed: bool = False

    def observe(self, identity: str, agreement_id: str, tariff_id: int | None) -> None:
        self.relationships[InventoryRelationship(identity, agreement_id, tariff_id)] = None

    def relevant(self, identity: str) -> bool:
        return any(
            implicated_products(self.purchases, identity, relation.agreement_id, relation.tariff_id)
            for relation in self.relationships
            if relation.identity == identity
        )

    def include(self, identity: str, agreement_id: str, tariff_id: int | None, owner_id: UUID | None) -> None:
        self.observe(identity, agreement_id, tariff_id)
        self.candidates.setdefault(
            identity,
            DiscoveredCandidate(
                identity=identity,
                agreement_id=agreement_id,
                purchase_id=owner_id,
                conclusion=CandidateConclusion.INCOMPLETE,
            ),
        )

    def conclude(self, identity: str, conclusion: CandidateConclusion) -> None:
        self.candidates[identity] = self.candidates[identity].model_copy(update={"conclusion": conclusion})

    def verify_discovery(
        self, initial: tuple[InventoryRelationship, ...], final: tuple[InventoryRelationship, ...]
    ) -> bool:
        first, last = Counter(initial), Counter(final)
        changed = {item for item in first.keys() | last.keys() if first[item] != last[item]}
        self.incomplete.update(item.identity for item in changed)
        return not changed

    def products(
        self,
        started_at: datetime,
        finished_at: datetime,
        scopes: dict[str, tuple[UUID | None, datetime | None]],
        conflicts: set[UUID],
    ) -> tuple[ProductDiscovery, ...]:
        return project_inventory(
            self.purchases,
            tuple(self.relationships),
            tuple(self.candidates.values()),
            frozenset(self.incomplete),
            frozenset(conflicts),
            started_at,
            finished_at,
            scopes,
            failed=self.failed,
        )
