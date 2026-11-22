"""Canonical and historical point reads for subscription inventory."""

from collections.abc import Awaitable, Callable, Collection
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from app.composition.reconciliation import reconcile_subscription
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.discovery import DiscoveredCandidate
from app.domains.billing.operator_cases import audited_subscription_candidates, audited_subscription_reads
from app.domains.billing.operator_contracts import (
    AuditedSubscriptionCandidate,
    AuditedSubscriptionConclusion,
    AuditedSubscriptionEvidence,
    AuditedSubscriptionObservation,
    LateObjectDisposition,
    LateObjectResult,
    LateSubscriptionPoint,
)
from app.domains.billing.reconciliation import read_source_time
from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof, ReconciliationResult
from app.domains.billing.paid_policy import CandidateConclusion as Conclusion, PaidDecision, paid_decision
from app.domains.billing.terminal_resolution import ReleasedPurchase, record_late_object, released_object_owners
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase
from app.domains.purchases.inventory_contracts import InventoryCandidateProof
from app.infrastructure.preflight import PreflightAdmission, PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import (
    LbxAttemptsExhausted,
    LbxProviderRejected,
    LbxRateLimited,
    LbxResponseInvalid,
    LbxTimeout,
    LbxUnavailable,
)
from app.integrations.lbx.financial import (
    Agreement,
    Subscription,
    agreement_is_closed,
    prove_agreement,
    subscription_lifecycle,
)
from app.integrations.lbx.reconciliation import timely_point
from app.models import ExternalCreateOperationKind as Kind, ExternalSubscriptionLifecycleStatus as Lifecycle
from app.models import PurchaseIntentState


async def read_inventory_candidate[T](read: Callable[[], Awaitable[T]], budget: PreflightBudget) -> T | None:
    """A timely object-local failure preserves its INCOMPLETE candidates only.

    Authentication/scope errors, stale ownership and shared budget/cleanup
    failures retain the outer customer-wide failure boundary.
    """
    try:
        return await timely_point(read, budget)
    except (LbxResponseInvalid, LbxUnavailable, LbxTimeout, LbxRateLimited, LbxAttemptsExhausted, LbxProviderRejected):
        return None


def subscription_listing_identities(rows: tuple[Subscription, ...]) -> list[tuple[int, int, int]]:
    return sorted((row.subscription_id, row.agreement_id, row.tariff_id) for row in rows)


@dataclass
class AuditedCompetitors:
    customer: CustomerOpen
    candidates: frozenset[AuditedSubscriptionCandidate] = frozenset()
    observations: dict[str, AuditedSubscriptionObservation] = field(default_factory=dict)
    updates: dict[str, tuple[datetime, AuditedSubscriptionEvidence]] = field(default_factory=dict, init=False)
    case_ids: dict[str, tuple[UUID, ...]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        matches: dict[str, list[UUID]] = {}
        for candidate in self.candidates:
            matches.setdefault(candidate.external_id, []).append(candidate.review_case_id)
        self.case_ids = {external_id: tuple(sorted(ids)) for external_id, ids in matches.items()}

    def retired_ids(self) -> set[str]:
        return {
            external_id
            for external_id, observation in self.observations.items()
            if observation.evidence.conclusion != AuditedSubscriptionConclusion.CONTRADICTED
            and observation.evidence.review_case_ids == self.case_ids[external_id]
        }

    def record(
        self,
        external_id: str,
        agreement_id: str,
        tariff_id: int,
        finished: datetime,
        conclusion: AuditedSubscriptionConclusion,
    ) -> None:
        self.updates[external_id] = (
            finished,
            AuditedSubscriptionEvidence(
                customer_id=self.customer.customer_id,
                provider_customer_id=self.customer.provider_id,
                external_id=external_id,
                agreement_id=agreement_id,
                tariff_id=tariff_id,
                review_case_ids=self.case_ids[external_id],
                conclusion=conclusion,
            ),
        )

    def observe(self, external_id: str, point: Subscription, agreement: Agreement | None, finished: datetime) -> None:
        agreement_id = str(point.agreement_id)
        conclusion = AuditedSubscriptionConclusion.CONTRADICTED
        if agreement is None:
            previous = self.observations.get(external_id)
            if previous is None or (agreement_id, point.tariff_id) == (
                previous.evidence.agreement_id,
                previous.evidence.tariff_id,
            ):
                return
        elif agreement.user_id == int(self.customer.provider_id):
            if agreement_is_closed(agreement):
                conclusion = AuditedSubscriptionConclusion.AGREEMENT_CLOSED
            elif subscription_lifecycle(point)[0] == Lifecycle.ENDED:
                conclusion = AuditedSubscriptionConclusion.ENDED
        self.record(external_id, agreement_id, point.tariff_id, finished, conclusion)

    async def read_omitted(
        self,
        client: LbxServerClient,
        factory: SessionFactory,
        external_id: str,
        budget: PreflightBudget,
        delegate: Callable[..., Awaitable[Any]],
    ) -> None:
        point = await read_inventory_candidate(
            lambda: client.get_subscription(subscription_id=int(external_id), budget=budget), budget
        )
        if point is None:
            return
        agreement = await read_inventory_candidate(
            lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
        )
        self.observe(external_id, point, agreement, await delegate(read_source_time, factory))


def load_audited_competitors(factory: SessionFactory, customer: CustomerOpen, purchase: Purchase) -> AuditedCompetitors:
    with factory() as db:
        candidates = audited_subscription_candidates(db, purchase.customer_id, purchase.account_id)
        return AuditedCompetitors(customer, candidates, audited_subscription_reads(db, customer, purchase, candidates))


@dataclass
class BoundSubscriptionInventory:
    candidates: dict[str, list[DiscoveredCandidate]]
    product_complete: dict[str, bool]
    sources: list[ReconciliationResult] = field(default_factory=list)
    conflicting_bindings: set[str] = field(default_factory=set)
    complete: bool = True


async def read_bound_subscriptions(
    client: LbxServerClient,
    admission: PreflightAdmission,
    configuration: Settings,
    *,
    factory: SessionFactory,
    versions: dict[UUID, Purchase],
    bindings: dict[str, Purchase],
    audited: AuditedCompetitors,
    budget: PreflightBudget,
    reuse: InventoryCandidateProof | None,
    work_claim: WorkClaim | None,
    delegate: Callable[..., Awaitable[Any]],
) -> BoundSubscriptionInventory:
    candidates: dict[str, list[DiscoveredCandidate]] = {
        purchase.accepted.selection.product_id: [] for purchase in versions.values()
    }
    inventory = BoundSubscriptionInventory(candidates, dict.fromkeys(candidates, True))
    # Canonical reads use their existing lease, even if absent from discovery or already in review.
    for provider_id, purchase in bindings.items():
        product = purchase.accepted.selection.product_id
        agreement_id = next(op.bound_id for op in purchase.operations if op.kind == Kind.AGREEMENT)
        conclusion = Conclusion.INCOMPLETE
        committed = None
        if reuse is not None and purchase.id == reuse.purchase.id:
            assert reuse.proof is not None
            proof = reuse.proof
        else:
            try:
                identity = await delegate(service.linked_subscription_id, factory, purchase)
                committed = await reconcile_subscription(
                    client,
                    admission,
                    configuration,
                    factory=factory,
                    subscription_id=identity,
                    budget=budget,
                    work_claim=work_claim,
                    delegate=delegate,
                    expected=purchase,
                )
                versions[purchase.id] = committed.purchase
                inventory.sources.append(committed)
                proof = committed.proof
            except AppError:
                inventory.complete = inventory.product_complete[product] = False
                candidates[product].append(
                    DiscoveredCandidate(
                        identity=provider_id,
                        agreement_id=agreement_id,
                        purchase_id=purchase.id,
                        conclusion=conclusion,
                    )
                )
                continue
        if proof.identity == IdentityProof.CONFLICT and "subscription_identity_conflict" in proof.reasons:
            inventory.conflicting_bindings.add(provider_id)
        if (
            provider_id in audited.case_ids
            and proof.identity == IdentityProof.MATCH
            and proof.lifecycle
            in {
                Lifecycle.ACTIVE,
                Lifecycle.INACTIVE,
            }
        ):
            audited.record(
                provider_id,
                agreement_id,
                purchase.accepted.selection.tariff_id,
                proof.read_finished_at,
                AuditedSubscriptionConclusion.CONTRADICTED,
            )
        # Reused operator proof has no committed source receipt. Only the final audited writer may apply it.
        if proof.complete and (committed is None or committed.purchase.state != PurchaseIntentState.MANUAL_REVIEW):
            conclusion = Conclusion.ELIGIBLE if paid_decision(proof) == PaidDecision.GRANT else Conclusion.INELIGIBLE
        elif proof.identity == IdentityProof.MATCH and proof.lifecycle == Lifecycle.ENDED:
            conclusion = Conclusion.INELIGIBLE
        inventory.product_complete[product] &= conclusion != Conclusion.INCOMPLETE
        candidates[product].append(
            DiscoveredCandidate(
                identity=provider_id,
                agreement_id=agreement_id,
                purchase_id=purchase.id,
                conclusion=conclusion,
                subscription_id=committed.subject.subscription_id if committed else None,
                observation_id=committed.observation_id if committed else None,
                fence=committed.subject.fence if committed else None,
            )
        )
        # A bound candidate needs original ownership, applicable terms and lifecycle for admission.
        inventory.complete &= (
            proof.identity == IdentityProof.MATCH
            and proof.commercial != CommercialProof.INCOMPLETE
            and proof.lifecycle is not None
        )
    return inventory


@dataclass
class ReleasedSubscriptionInventory:
    agreements: dict[str, ReleasedPurchase] = field(default_factory=dict)
    subscriptions: dict[str, ReleasedPurchase] = field(default_factory=dict)
    _checked_agreements: set[str] = field(default_factory=set, init=False)
    _checked_subscriptions: set[str] = field(default_factory=set, init=False)

    async def load(
        self,
        factory: SessionFactory,
        customer_id: UUID,
        rows: tuple[Subscription, ...],
        delegate: Callable[..., Awaitable[Any]],
    ) -> None:
        await self._load_ids(
            factory,
            customer_id,
            {str(row.agreement_id) for row in rows},
            {str(row.subscription_id) for row in rows},
            delegate,
        )

    async def owner_for_point(
        self,
        factory: SessionFactory,
        customer_id: UUID,
        subscription_id: str,
        agreement_id: str,
        delegate: Callable[..., Awaitable[Any]],
    ) -> ReleasedPurchase | None:
        await self._load_ids(factory, customer_id, {agreement_id}, {subscription_id}, delegate)
        return self.subscriptions.get(subscription_id) or self.agreements.get(agreement_id)

    async def _load_ids(
        self,
        factory: SessionFactory,
        customer_id: UUID,
        agreements: set[str],
        subscriptions: set[str],
        delegate: Callable[..., Awaitable[Any]],
    ) -> None:
        agreements = agreements - self._checked_agreements
        subscriptions = subscriptions - self._checked_subscriptions
        if not (agreements or subscriptions):
            return
        owners = await delegate(
            released_object_owners,
            factory,
            customer_id,
            tuple(agreements),
            tuple(subscriptions),
        )
        self._checked_agreements.update(agreements)
        self._checked_subscriptions.update(subscriptions)
        for owner in owners:
            self.agreements.update((identity, owner) for identity in owner.agreement_ids)
            self.subscriptions.update((identity, owner) for identity in owner.subscription_ids)

    def owner(self, row: Subscription) -> ReleasedPurchase | None:
        return self.subscriptions.get(str(row.subscription_id)) or self.agreements.get(str(row.agreement_id))

    def implicated_products(
        self,
        subscription_id: str,
        row: Subscription,
        bindings: dict[str, Purchase],
        agreements: dict[str, Purchase],
        products_by_tariff: dict[int, set[str]],
        audited_ids: Collection[str],
    ) -> set[str]:
        agreement_id = str(row.agreement_id)
        bound = bindings.get(subscription_id)
        retired_subscription = self.subscriptions.get(subscription_id)
        retired_agreement = self.agreements.get(agreement_id)
        owners = [bound, agreements.get(agreement_id)]
        owners.extend(history.purchase for history in (retired_subscription, retired_agreement) if history)
        products = {owner.accepted.selection.product_id for owner in owners if owner is not None}
        # A historical agreement alone cannot establish ownership of this subscription.
        if (
            not products
            or subscription_id in audited_ids
            or (retired_agreement is not None and bound is None and retired_subscription is None)
        ):
            products.update(products_by_tariff.get(row.tariff_id, ()))
        return products


async def observe_released_subscription(
    purchase: Purchase,
    point: Subscription,
    read_agreement: Callable[[], Awaitable[Agreement | None]],
    *,
    read_started_at: datetime,
    read_finished_at: datetime,
    subscription_id: int,
    user_id: int,
    factory: SessionFactory,
    delegate: Callable[..., Awaitable[Any]],
) -> LateObjectResult:
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    observation = LateSubscriptionPoint(str(point.agreement_id), point.tariff_id)

    async def record(observed: LateSubscriptionPoint, finished: datetime) -> LateObjectResult:
        return await delegate(
            record_late_object,
            factory,
            purchase,
            operation.id,
            str(subscription_id),
            read_started_at,
            read_finished_at=finished,
            subscription_point=observed,
        )

    result = await record(observation, read_finished_at)
    if result.disposition != LateObjectDisposition.NEEDS_ORIGINAL_PROOF:
        return result
    # Confirmation of a possible original requires a provider read. The writer
    # rechecks the permanent binding after that read.
    agreement = await read_agreement()
    if agreement is None:
        raise LbxResponseInvalid()
    original = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    prove_agreement(agreement, user_id=user_id, seller_id=purchase.accepted.seller_id, number=original.key)
    if agreement_is_closed(agreement) or subscription_lifecycle(point)[0] == Lifecycle.ENDED:
        return LateObjectResult(LateObjectDisposition.CLEAR)
    finished = await delegate(read_source_time, factory)
    return await record(replace(observation, original_live_proven=True), finished)
