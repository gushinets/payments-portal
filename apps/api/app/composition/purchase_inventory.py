"""One bounded inventory scan for admission, customer work and operator proof."""

from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.composition.reconciliation import read_subscription_proof, reconcile_subscription
from app.domains.billing.reconciliation import read_source_time
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.discovery import DiscoveredCandidate, scope_versions
from app.domains.billing.paid_policy import CandidateConclusion as Conclusion, PaidDecision, paid_decision
from app.domains.billing.background_recovery import customer_snapshot
from app.domains.billing.inventory_history import retain_candidate_relationship, retained_subscription_relationships
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.customer_conflicts import record_customer_conflict
from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    ReadInterval,
    IdentityProof,
    SubscriptionCandidateSubject,
    SubscriptionProof,
    SubscriptionRelationship,
)
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete
from app.domains.purchases.inventory_facts import InventoryFacts, InventoryRelationship
from app.domains.purchases.inventory import same_purchase
from app.domains.purchases.inventory_contracts import (
    InventoryCandidateProof,
    InventoryPointHistory,
    InventoryResult,
    InventoryStale,
)
from app.infrastructure.preflight import (
    PreflightAdmission,
    PreflightBudget,
    PreflightCleanupPending,
    PreflightDeadlineExceeded,
)
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import (
    LbxResponseInvalid,
    LbxScopeMismatch,
    LbxUnavailable,
    LbxTimeout,
    LbxRateLimited,
    LbxAttemptsExhausted,
    LbxProviderRejected,
)
from app.integrations.lbx.financial import Agreement, Subscription, agreement_is_closed, subscription_lifecycle
from app.integrations.lbx.reconciliation import MAX_RELEVANT_SUBSCRIPTIONS, source_scope_unproven, timely_point
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from app.models import ExternalSubscriptionLifecycleStatus as Lifecycle


async def collect_inventory(
    client: LbxServerClient,
    admission: PreflightAdmission,
    configuration: Settings,
    *,
    factory: SessionFactory,
    customer: CustomerOpen,
    budget: PreflightBudget,
    expected: Purchase | None = None,
    reuse: InventoryCandidateProof | None = None,
    work_claim: WorkClaim | None = None,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
) -> InventoryResult:
    budget.check()
    started = await delegate(read_source_time, factory)
    current, initial = await delegate(customer_snapshot, factory, configuration, customer.customer_id)
    if (current.operation_id, current.fence, current.provider_id, current.outer_key) != (
        customer.operation_id,
        customer.fence,
        customer.provider_id,
        customer.outer_key,
    ):
        raise InventoryStale()
    versions = {purchase.id: purchase for purchase in initial}
    if expected is not None and (expected.id not in versions or not same_purchase(versions[expected.id], expected)):
        raise InventoryStale()
    if reuse is not None and not same_purchase(versions[reuse.purchase.id], reuse.purchase):
        raise InventoryStale()
    scope_state = await delegate(scope_versions, factory, initial[0]) if initial else {}
    facts = InventoryFacts(initial)
    sources = []
    point_history: dict[str, InventoryPointHistory] = {}
    conflicts, pending = set(), set()
    complete = True
    conflicting_bindings: set[str] = set()
    bindings = {
        operation.bound_id: purchase
        for purchase in initial
        for operation in purchase.operations
        if operation.kind == Kind.SUBSCRIPTION and operation.bound_id is not None
    }
    agreements = {
        operation.bound_id: purchase
        for purchase in initial
        for operation in purchase.operations
        if operation.kind == Kind.AGREEMENT and operation.bound_id is not None
    }

    async def retain_relationship(provider_id: str, agreement_id: str, tariff_id: int, interval: ReadInterval) -> None:
        if known := bindings.get(provider_id):
            point_history[provider_id] = await delegate(
                retain_candidate_relationship,
                factory,
                known,
                point_history[provider_id],
                SubscriptionRelationship(agreement_id, tariff_id),
                interval,
            )

    if len(bindings) > MAX_RELEVANT_SUBSCRIPTIONS:
        return InventoryResult(current, initial, (), (), False)
    # Canonical reads belong to their existing lease, including when absent from
    # discovery or already in review. Commit timely negatives before later I/O.
    for provider_id, purchase in bindings.items():
        agreement_id = next(op.bound_id for op in purchase.operations if op.kind == Kind.AGREEMENT)
        conclusion = Conclusion.INCOMPLETE
        committed = None
        proof: SubscriptionProof | None = None
        if reuse is not None and purchase.id == reuse.purchase.id:
            assert reuse.proof is not None
            proof = reuse.proof
        else:
            try:
                identity = await delegate(service.linked_subscription_id, factory, purchase)
                result = await reconcile_subscription(
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
                versions[purchase.id] = result.purchase
                sources.append(result)
                committed = result
                proof = result.proof
            except AppError:
                complete = False
        # Capture retained read implications after the canonical attempt;
        # later discovery facts carry their own independent I/O intervals.
        history = await delegate(retained_subscription_relationships, factory, purchase)
        point_history[provider_id] = history
        retained = history.relationships
        for relationship in retained:
            facts.observe(provider_id, relationship.agreement_id, relationship.tariff_id)
        facts.observe(provider_id, agreement_id, purchase.accepted.selection.tariff_id)
        if proof is None:
            facts.incomplete.add(provider_id)
            facts.candidates[provider_id] = DiscoveredCandidate(
                identity=provider_id,
                agreement_id=agreement_id,
                purchase_id=purchase.id,
                conclusion=conclusion,
            )
            continue
        relationship = proof.point_relationship
        facts.failed |= source_scope_unproven(proof)
        expected_relationship = (agreement_id, purchase.accepted.selection.tariff_id)
        disagreement = any((item.agreement_id, item.tariff_id) != expected_relationship for item in retained)
        if relationship is not None:
            disagreement |= (relationship.agreement_id, relationship.tariff_id) != expected_relationship
            facts.observe(provider_id, relationship.agreement_id, relationship.tariff_id)
        if disagreement:
            complete = False
        if proof.identity == IdentityProof.CONFLICT and "subscription_identity_conflict" in proof.reasons:
            conflicting_bindings.add(provider_id)
        # Reused operator proof contributes completeness but supplies no committed
        # source receipt: only the final audited writer may apply/select it.
        # Review blocks this source's primary selection, not proof of its ownership
        # or an independent product that happens to share its accepted tariff.
        if proof.complete:
            conclusion = Conclusion.ELIGIBLE if paid_decision(proof) == PaidDecision.GRANT else Conclusion.INELIGIBLE
        elif proof.identity == IdentityProof.MATCH and proof.lifecycle == Lifecycle.ENDED:
            conclusion = Conclusion.INELIGIBLE
        if disagreement or conclusion == Conclusion.INCOMPLETE:
            facts.incomplete.add(provider_id)
        facts.candidates[provider_id] = DiscoveredCandidate(
            identity=provider_id,
            agreement_id=next(op.bound_id for op in purchase.operations if op.kind == Kind.AGREEMENT),
            purchase_id=purchase.id,
            conclusion=conclusion,
            subscription_id=committed.subject.subscription_id if committed else None,
            observation_id=committed.observation_id if committed else None,
            fence=committed.subject.fence if committed else None,
        )
        # Inventory needs original ownership, applicable terms and lifecycle,
        # not a complete paid-cycle calendar for an already bound object.
        if (
            proof.identity != IdentityProof.MATCH
            or proof.commercial == CommercialProof.INCOMPLETE
            or proof.lifecycle is None
        ):
            complete = False
    try:
        if reuse is None:
            try:
                user = await timely_point(
                    lambda: client.get_user(user_id=int(current.provider_id), budget=budget), budget
                )
            except LbxScopeMismatch:
                await delegate(record_customer_conflict, factory, current, work_claim)
                raise
            if user.outer_id is None:
                raise LbxResponseInvalid()
            if user.outer_id != current.outer_key:
                await delegate(record_customer_conflict, factory, current, work_claim, provider_id=current.provider_id)
                raise LbxScopeMismatch()
        listing_started = await delegate(read_source_time, factory)
        rows = await timely_point(
            lambda: client.discover_subscriptions(user_id=int(current.provider_id), budget=budget), budget
        )
        listing_interval = ReadInterval(listing_started, await delegate(read_source_time, factory))
        for row in rows:
            facts.observe(str(row.subscription_id), str(row.agreement_id), row.tariff_id)
            await retain_relationship(str(row.subscription_id), str(row.agreement_id), row.tariff_id, listing_interval)
        relevant: dict[str, Subscription | None] = {
            str(row.subscription_id): row for row in rows if facts.relevant(str(row.subscription_id))
        }
        # Recheck contradictory bound IDs even when discovery omits them.
        for provider_id in conflicting_bindings:
            relevant.setdefault(provider_id, None)
        if len(relevant) > MAX_RELEVANT_SUBSCRIPTIONS:
            raise PurchaseInventoryIncomplete()
        counts = Counter(row.agreement_id for row in rows)
        for provider_id, candidate in relevant.items():
            budget.check()
            known = bindings.get(provider_id)
            owner = agreements.get(str(candidate.agreement_id)) if candidate is not None else None
            if (
                known is not None
                and provider_id not in conflicting_bindings
                and (owner is None or owner.id == known.id)
            ):
                canonical = facts.candidates[provider_id]
                agreement_id = next(op.bound_id for op in known.operations if op.kind == Kind.AGREEMENT)
                disagreement = candidate is not None and (str(candidate.agreement_id), candidate.tariff_id) != (
                    agreement_id,
                    known.accepted.selection.tariff_id,
                )
                if disagreement:
                    complete = False
                if disagreement or canonical.conclusion == Conclusion.INCOMPLETE:
                    facts.observe(provider_id, agreement_id, known.accepted.selection.tariff_id)
                    if candidate is not None:
                        facts.observe(provider_id, str(candidate.agreement_id), candidate.tariff_id)
                    facts.incomplete.add(provider_id)
                continue

            def include_candidate(agreement_id: str, tariff_id: int | None) -> None:
                owner = agreements.get(agreement_id)
                facts.include(provider_id, agreement_id, tariff_id, owner.id if owner else None)

            include_candidate(
                str(candidate.agreement_id)
                if candidate is not None
                else next(op.bound_id for op in known.operations if op.kind == Kind.AGREEMENT),
                candidate.tariff_id if candidate is not None else None,
            )
            # A permanently bound sibling can never be this purchase's original
            # UNKNOWN candidate, even when LBX now places it on this agreement.
            if candidate is not None and known is None and owner is not None:
                operation = next(op for op in owner.operations if op.kind == Kind.SUBSCRIPTION)
                if counts[candidate.agreement_id] == 1 and operation.bound_id is None:
                    if (
                        reuse is not None
                        and owner.id == reuse.purchase.id
                        and str(candidate.subscription_id) == reuse.provider_id
                    ):
                        proof = reuse.proof
                    elif operation.state in {State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW}:
                        from app.composition.purchase_recovery import original_command

                        try:
                            original_pending = await delegate(
                                financial.original_request,
                                factory,
                                owner,
                                operation,
                                original_command(owner, operation, current),
                            )
                        except AppError:
                            complete = False
                            continue
                        if not original_pending:
                            complete = False
                            continue
                        if operation.candidate_id not in {None, str(candidate.subscription_id)}:
                            conflicts.add(owner.id)
                            complete = False
                            continue
                        agreement = next(op for op in owner.operations if op.kind == Kind.AGREEMENT)
                        proof = await read_subscription_proof(
                            client,
                            SubscriptionCandidateSubject(
                                owner, current, agreement.bound_id, agreement.key, str(candidate.subscription_id)
                            ),
                            configuration,
                            factory=factory,
                            budget=budget,
                            delegate=delegate,
                        )
                    else:
                        proof = None
                    if proof is not None:
                        facts.failed |= source_scope_unproven(proof)
                        # Retain the actual point facts even when terms/policy
                        # cannot be proven. Reuse never needs another point GET.
                        include_candidate(str(candidate.agreement_id), owner.accepted.selection.tariff_id)
                        if proof.point_relationship is not None:
                            include_candidate(proof.point_relationship.agreement_id, proof.point_relationship.tariff_id)
                        if (
                            "customer_identity_conflict" in proof.reasons
                            or "customer_original_key_mismatch" in proof.reasons
                        ):
                            await delegate(
                                record_customer_conflict,
                                factory,
                                current,
                                work_claim,
                                provider_id=current.provider_id
                                if "customer_original_key_mismatch" in proof.reasons
                                else None,
                            )
                            # The customer writer invalidated every source fence.
                            # Never apply this snapshot as a purchase-only review.
                            raise InventoryStale()
                        if (
                            proof.identity == IdentityProof.MATCH
                            and proof.commercial == CommercialProof.MATCH
                            and proof.lifecycle is not None
                        ):
                            # Matching original proof establishes these point
                            # relationships even when discovery disagrees.
                            agreement_id = next(op.bound_id for op in owner.operations if op.kind == Kind.AGREEMENT)
                            include_candidate(agreement_id, owner.accepted.selection.tariff_id)
                            if (str(candidate.agreement_id), candidate.tariff_id) != (
                                agreement_id,
                                owner.accepted.selection.tariff_id,
                            ):
                                complete = False
                            # Stage 3 alone may bind this original. Its existence is
                            # never a foreign product, nor authority for another POST.
                            pending.add(owner.id)
                        else:
                            if proof.identity == IdentityProof.CONFLICT or proof.commercial == CommercialProof.MISMATCH:
                                conflicts.add(owner.id)
                            complete = False
                        continue
            point_started = await delegate(read_source_time, factory)
            point = await _candidate_point(
                lambda: client.get_subscription(subscription_id=int(provider_id), budget=budget), budget
            )
            if point is None:
                complete = False
                continue
            await retain_relationship(
                provider_id,
                str(point.agreement_id),
                point.tariff_id,
                ReadInterval(point_started, await delegate(read_source_time, factory)),
            )
            include_candidate(str(point.agreement_id), point.tariff_id)
            if known is not None:
                # This bound object already contradicted its canonical proof or
                # discovery ownership. A later terminal read cannot clear any
                # newly implicated product's uncertainty.
                facts.incomplete.add(provider_id)
            if candidate is not None and (point.agreement_id, point.tariff_id) != (
                candidate.agreement_id,
                candidate.tariff_id,
            ):
                complete = False
                facts.incomplete.add(provider_id)
                if known is None:
                    continue
            owner = agreements.get(str(point.agreement_id))
            if known is not None and (owner is None or owner.id == known.id):
                continue
            agreement = await _candidate_point(
                lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
            )
            if agreement is None:
                complete = False
                continue
            if agreement.user_id != int(current.provider_id):
                complete = False
                continue
            conclusion = _candidate_conclusion(agreement, point)
            if conclusion != Conclusion.ELIGIBLE:
                facts.conclude(provider_id, conclusion)
                if conclusion == Conclusion.INCOMPLETE:
                    complete = False
                continue
            if owner is not None:
                conflicts.add(owner.id)
            if known is not None:
                conflicts.add(known.id)
            conflicts.update(
                purchase.id for purchase in initial if purchase.accepted.selection.tariff_id == point.tariff_id
            )
        listing_started = await delegate(read_source_time, factory)
        again = await timely_point(
            lambda: client.discover_subscriptions(user_id=int(current.provider_id), budget=budget), budget
        )
        listing_interval = ReadInterval(listing_started, await delegate(read_source_time, factory))
        for row in again:
            facts.observe(str(row.subscription_id), str(row.agreement_id), row.tariff_id)
            await retain_relationship(str(row.subscription_id), str(row.agreement_id), row.tariff_id, listing_interval)
        complete &= facts.verify_discovery(_relationships(rows), _relationships(again))
    except InventoryStale:
        raise
    except (AppError, PreflightDeadlineExceeded, PreflightCleanupPending):
        complete = False
        facts.failed = True
    finished = await delegate(read_source_time, factory)
    products = facts.products(started, finished, scope_state, conflicts)
    return InventoryResult(
        current,
        tuple(versions.values()),
        tuple(sorted(conflicts)),
        tuple(sorted(pending)),
        complete,
        products=products,
        sources=tuple(sources),
        point_history=tuple(point_history.values()),
    )


async def _candidate_point[T](read: Callable[[], Awaitable[T]], budget: PreflightBudget) -> T | None:
    """A timely object-local failure preserves its INCOMPLETE candidates only.

    Authentication/scope errors, stale ownership and shared budget/cleanup
    failures retain the outer customer-wide failure boundary.
    """
    try:
        return await timely_point(read, budget)
    except (LbxResponseInvalid, LbxUnavailable, LbxTimeout, LbxRateLimited, LbxAttemptsExhausted, LbxProviderRejected):
        return None


def _relationships(rows: tuple[Subscription, ...]) -> tuple[InventoryRelationship, ...]:
    return tuple(InventoryRelationship(str(row.subscription_id), str(row.agreement_id), row.tariff_id) for row in rows)


def _candidate_conclusion(agreement: Agreement, point: Subscription) -> Conclusion:
    """Object-local normalization shares the read failure's product blast radius."""
    try:
        terminal = agreement_is_closed(agreement) or subscription_lifecycle(point)[0] == Lifecycle.ENDED
    except LbxResponseInvalid:
        return Conclusion.INCOMPLETE
    return Conclusion.INELIGIBLE if terminal else Conclusion.ELIGIBLE
