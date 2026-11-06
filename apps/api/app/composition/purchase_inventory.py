"""One bounded inventory scan for admission, customer work and operator proof."""

from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.composition.reconciliation import read_subscription_proof, reconcile_subscription
from app.domains.billing.reconciliation import read_source_time
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.discovery import DiscoveredCandidate, ProductDiscovery, scope_versions
from app.domains.billing.paid_policy import CandidateConclusion as Conclusion, PaidDecision, paid_decision
from app.domains.billing.background_recovery import customer_snapshot
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.customer_conflicts import record_customer_conflict
from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    IdentityProof,
    SubscriptionCandidateSubject,
)
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete
from app.domains.purchases.inventory import same_purchase
from app.domains.purchases.inventory_contracts import InventoryCandidateProof, InventoryResult, InventoryStale
from app.infrastructure.preflight import (
    PreflightAdmission,
    PreflightBudget,
    PreflightCleanupPending,
    PreflightDeadlineExceeded,
)
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxResponseInvalid, LbxScopeMismatch
from app.integrations.lbx.financial import Subscription, agreement_is_closed, subscription_lifecycle
from app.integrations.lbx.reconciliation import MAX_RELEVANT_SUBSCRIPTIONS, timely_point
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from app.models import ExternalSubscriptionLifecycleStatus as Lifecycle, PurchaseIntentState


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
    candidates = {purchase.accepted.selection.product_id: [] for purchase in initial}
    product_complete = dict.fromkeys(candidates, True)
    sources = []
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
    if len(bindings) > MAX_RELEVANT_SUBSCRIPTIONS:
        return InventoryResult(current, initial, (), (), False)
    # Canonical reads belong to their existing lease, including when absent from
    # discovery or already in review. Commit timely negatives before later I/O.
    for provider_id, purchase in bindings.items():
        product = purchase.accepted.selection.product_id
        conclusion = Conclusion.INCOMPLETE
        committed = None
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
                product_complete[product] = False
                candidates[product].append(
                    DiscoveredCandidate(
                        identity=provider_id,
                        agreement_id=next(op.bound_id for op in purchase.operations if op.kind == Kind.AGREEMENT),
                        purchase_id=purchase.id,
                        conclusion=conclusion,
                    )
                )
                continue
        if proof.identity == IdentityProof.CONFLICT and "subscription_identity_conflict" in proof.reasons:
            conflicting_bindings.add(provider_id)
        if committed is not None:
            if proof.complete and committed.purchase.state != PurchaseIntentState.MANUAL_REVIEW:
                conclusion = (
                    Conclusion.ELIGIBLE if paid_decision(proof) == PaidDecision.GRANT else Conclusion.INELIGIBLE
                )
            elif proof.identity == IdentityProof.MATCH and proof.lifecycle == Lifecycle.ENDED:
                conclusion = Conclusion.INELIGIBLE
        product_complete[product] &= conclusion != Conclusion.INCOMPLETE
        candidates[product].append(
            DiscoveredCandidate(
                identity=provider_id,
                agreement_id=next(op.bound_id for op in purchase.operations if op.kind == Kind.AGREEMENT),
                purchase_id=purchase.id,
                conclusion=conclusion,
                subscription_id=committed.subject.subscription_id if committed else None,
                observation_id=committed.observation_id if committed else None,
                fence=committed.subject.fence if committed else None,
            )
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
        rows = await timely_point(
            lambda: client.discover_subscriptions(user_id=int(current.provider_id), budget=budget), budget
        )
        tariffs = {purchase.accepted.selection.tariff_id for purchase in initial}
        relevant: dict[str, Subscription | None] = {
            str(row.subscription_id): row
            for row in rows
            if (row.tariff_id in tariffs or str(row.subscription_id) in bindings or str(row.agreement_id) in agreements)
        }
        # Canonical contradictions need point checks even when discovery omits
        # the known ID. Do not invent listing fields or treat it as UNKNOWN.
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
                continue
            affected = (
                {owner.accepted.selection.product_id}
                if owner is not None
                else {
                    item.accepted.selection.product_id
                    for item in initial
                    if candidate is not None and item.accepted.selection.tariff_id == candidate.tariff_id
                }
            )
            for product in affected:
                candidates[product].append(
                    DiscoveredCandidate(
                        identity=provider_id,
                        agreement_id=str(candidate.agreement_id),
                        purchase_id=owner.id if owner else None,
                        conclusion=Conclusion.INCOMPLETE,
                    )
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
                            # Stage 3 alone may bind this original. Its existence is
                            # never a foreign product, nor authority for another POST.
                            pending.add(owner.id)
                        elif proof.identity == IdentityProof.CONFLICT or proof.commercial == CommercialProof.MISMATCH:
                            conflicts.add(owner.id)
                            complete = False
                        else:
                            complete = False
                        continue
            point = await timely_point(
                lambda: client.get_subscription(subscription_id=int(provider_id), budget=budget), budget
            )
            if candidate is not None and (point.agreement_id, point.tariff_id) != (
                candidate.agreement_id,
                candidate.tariff_id,
            ):
                complete = False
                if known is None:
                    continue
            owner = agreements.get(str(point.agreement_id))
            if known is not None and (owner is None or owner.id == known.id):
                continue
            agreement = await timely_point(
                lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
            )
            if agreement.user_id != int(current.provider_id):
                complete = False
                continue
            if agreement_is_closed(agreement) or subscription_lifecycle(point)[0] == Lifecycle.ENDED:
                for product in affected:
                    candidates[product][-1] = candidates[product][-1].model_copy(
                        update={"conclusion": Conclusion.INELIGIBLE}
                    )
                continue
            if owner is not None:
                conflicts.add(owner.id)
            if known is not None:
                conflicts.add(known.id)
            conflicts.update(
                purchase.id for purchase in initial if purchase.accepted.selection.tariff_id == point.tariff_id
            )
        again = await timely_point(
            lambda: client.discover_subscriptions(user_id=int(current.provider_id), budget=budget), budget
        )
        if _identities(rows) != _identities(again):
            complete = False
        for product in candidates:

            def relevant_to_product(row: Subscription) -> bool:
                bound = bindings.get(str(row.subscription_id)) or agreements.get(str(row.agreement_id))
                if bound is not None:
                    return bound.accepted.selection.product_id == product
                return any(
                    item.accepted.selection.product_id == product and item.accepted.selection.tariff_id == row.tariff_id
                    for item in initial
                )

            product_complete[product] &= _identities(tuple(filter(relevant_to_product, rows))) == _identities(
                tuple(filter(relevant_to_product, again))
            )
    except InventoryStale:
        raise
    except (AppError, PreflightDeadlineExceeded, PreflightCleanupPending):
        complete = False
        product_complete = dict.fromkeys(product_complete, False)
    for purchase in initial:
        if purchase.id in conflicts:
            product_complete[purchase.accepted.selection.product_id] = False
    finished = await delegate(read_source_time, factory)
    products = tuple(
        ProductDiscovery(
            product_id=product,
            read_started_at=started,
            read_finished_at=finished,
            primary_subscription_id=scope_state.get(product, (None, None))[0],
            primary_retired_at=scope_state.get(product, (None, None))[1],
            complete=product_complete[product] and all(item.conclusion != Conclusion.INCOMPLETE for item in observed),
            candidates=tuple(observed),
        )
        for product, observed in sorted(candidates.items())
    )
    return InventoryResult(
        current,
        tuple(versions.values()),
        tuple(sorted(conflicts)),
        tuple(sorted(pending)),
        complete,
        products=products,
        sources=tuple(sources),
    )


def _identities(rows: tuple[Subscription, ...]) -> list[tuple[int, int, int]]:
    return sorted((row.subscription_id, row.agreement_id, row.tariff_id) for row in rows)
