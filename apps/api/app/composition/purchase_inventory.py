"""One bounded inventory scan for admission, customer work and operator proof."""

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.composition.purchase_inventory_history import (
    ReleasedSubscriptionInventory,
    load_audited_subscription_candidates,
    observe_released_subscription,
    read_inventory_candidate,
    subscription_listing_identities,
)
from app.domains.billing.operator_contracts import LateObjectDisposition
from app.composition.reconciliation import read_subscription_source, reconcile_subscription
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
    audited_candidates = (
        await delegate(load_audited_subscription_candidates, factory, initial[0]) if initial else frozenset()
    )
    audited_ids = {candidate.external_id for candidate in audited_candidates}
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
        return InventoryResult(current, initial, (), (), False, audited_candidates=audited_candidates)
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
        # Reused operator proof contributes completeness but supplies no committed
        # source receipt: only the final audited writer may apply/select it.
        if proof.complete and (committed is None or committed.purchase.state != PurchaseIntentState.MANUAL_REVIEW):
            conclusion = Conclusion.ELIGIBLE if paid_decision(proof) == PaidDecision.GRANT else Conclusion.INELIGIBLE
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
        retired_index = ReleasedSubscriptionInventory()
        await retired_index.load(factory, current.customer_id, rows, delegate)
        products_by_tariff: dict[int, set[str]] = {}
        for purchase in initial:
            selection = purchase.accepted.selection
            products_by_tariff.setdefault(selection.tariff_id, set()).add(selection.product_id)

        def implicated_products(row: Subscription) -> set[str]:
            subscription_id, agreement_id = str(row.subscription_id), str(row.agreement_id)
            bound = bindings.get(subscription_id)
            retired_subscription = retired_index.subscriptions.get(subscription_id)
            retired_agreement = retired_index.agreements.get(agreement_id)
            owners = [bound, agreements.get(agreement_id)]
            owners.extend(history.purchase for history in (retired_subscription, retired_agreement) if history)
            owned = {owner.accepted.selection.product_id for owner in owners if owner is not None}
            # A historical agreement alone cannot establish ownership of this subscription.
            if (
                not owned
                or subscription_id in audited_ids
                or (retired_agreement is not None and bound is None and retired_subscription is None)
            ):
                owned.update(products_by_tariff.get(row.tariff_id, ()))
            return owned & candidates.keys()

        relevant: dict[str, Subscription | None] = {
            str(row.subscription_id): row
            for row in rows
            if str(row.subscription_id) in audited_ids or implicated_products(row) or retired_index.owner(row)
        }
        # Canonical contradictions and audited competitors survive discovery omissions.
        for provider_id in sorted(conflicting_bindings | audited_ids):
            relevant.setdefault(provider_id, None)
        within_read_limit = len(relevant) <= MAX_RELEVANT_SUBSCRIPTIONS
        complete &= within_read_limit
        confirmed_agreements: set[int] = set()
        for provider_id, candidate in relevant.items():
            budget.check()
            known = bindings.get(provider_id)
            owner = agreements.get(str(candidate.agreement_id)) if candidate is not None else None
            history = retired_index.owner(candidate) if candidate is not None else None
            if (
                known is not None
                and provider_id not in conflicting_bindings
                and (owner is None or owner.id == known.id)
                and history is None
            ):
                continue
            unlisted_competitor = candidate is None and known is None
            if candidate is not None:
                affected = implicated_products(candidate)
                agreement_id = str(candidate.agreement_id)
            elif known is not None:
                affected = {known.accepted.selection.product_id}
                agreement_id = next(op.bound_id for op in known.operations if op.kind == Kind.AGREEMENT)
            else:
                affected = set()
                agreement_id = None
            if not within_read_limit:
                for product in candidates if unlisted_competitor else affected:
                    product_complete[product] = False
                continue
            retained_owner = history.purchase if history else owner or known
            for product in affected:
                candidates[product].append(
                    DiscoveredCandidate(
                        identity=provider_id,
                        agreement_id=agreement_id,
                        purchase_id=retained_owner.id if retained_owner else None,
                        conclusion=Conclusion.INCOMPLETE,
                    )
                )
            point, historical_read, rejected_original_agreement_id = None, None, None
            different_receipt_owner = None
            # A permanently bound sibling can never be this purchase's original
            # UNKNOWN candidate, even when LBX now places it on this agreement.
            if candidate is not None and known is None and owner is not None and history is None:
                operation = next(op for op in owner.operations if op.kind == Kind.SUBSCRIPTION)
                if operation.bound_id is None:
                    agreement_conflict = False
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
                            original_pending = False
                        if original_pending and operation.candidate_id in {None, provider_id}:
                            agreement = next(op for op in owner.operations if op.kind == Kind.AGREEMENT)
                            source = await read_subscription_source(
                                client,
                                SubscriptionCandidateSubject(
                                    owner, current, agreement.bound_id, agreement.key, provider_id
                                ),
                                configuration,
                                factory=factory,
                                budget=budget,
                                delegate=delegate,
                            )
                            proof, point = source.proof, source.point
                            agreement_conflict = source.agreement_conflict
                        else:
                            complete = False
                            rejected_original_agreement_id = candidate.agreement_id
                            if original_pending:
                                different_receipt_owner = owner.id
                            proof = None
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
                        # Point reads (or the caller's proven original) establish multiplicity on this agreement.
                        if (point is not None and point.agreement_id == candidate.agreement_id) or (
                            point is None and proof.identity == IdentityProof.MATCH
                        ):
                            if candidate.agreement_id in confirmed_agreements:
                                conflicts.add(owner.id)
                            confirmed_agreements.add(candidate.agreement_id)
                        if (
                            proof.identity == IdentityProof.MATCH
                            and proof.commercial == CommercialProof.MATCH
                            and proof.lifecycle is not None
                        ):
                            # Stage 3 alone may bind this original. Its existence is
                            # never a foreign product, nor authority for another POST.
                            pending.add(owner.id)
                        else:
                            complete = False
                            # A disputed list alone cannot implicate this purchase. Its own
                            # agreement, receipt, or point-confirmed relationship can.
                            if (
                                proof.identity == IdentityProof.CONFLICT or proof.commercial == CommercialProof.MISMATCH
                            ) and (
                                agreement_conflict
                                or operation.candidate_id == provider_id
                                or (point is not None and point.agreement_id == candidate.agreement_id)
                            ):
                                conflicts.add(owner.id)
                        if point is None or point.agreement_id == candidate.agreement_id:
                            continue
                        historical_read = proof.read_started_at, proof.read_finished_at
            if historical_read is None:
                read_started = await delegate(read_source_time, factory)
                point = await read_inventory_candidate(
                    lambda: client.get_subscription(subscription_id=int(provider_id), budget=budget), budget
                )
                if point is None or str(point.subscription_id) != provider_id:
                    complete = False
                    if unlisted_competitor:
                        # With no current point or listing its current tariff is unknown.
                        product_complete = dict.fromkeys(product_complete, False)
                    continue
                historical_read = read_started, await delegate(read_source_time, factory)
            if point.agreement_id == rejected_original_agreement_id:
                if different_receipt_owner is not None:
                    # Its dedicated agreement really has a different subscription from its receipt.
                    conflicts.add(different_receipt_owner)
                continue  # Binding stays blocked. Only a different relationship needs historical inspection.
            listing_disagrees = candidate is not None and (point.agreement_id, point.tariff_id) != (
                candidate.agreement_id,
                candidate.tariff_id,
            )
            complete &= not listing_disagrees
            if history is None or listing_disagrees:
                # A disputed listing cannot establish ownership of a late object.
                history = await retired_index.owner_for_point(
                    factory,
                    current.customer_id,
                    provider_id,
                    str(point.agreement_id),
                    delegate,
                )
            if unlisted_competitor or listing_disagrees or history is not None:
                for product in implicated_products(point) - affected:
                    candidates[product].append(
                        DiscoveredCandidate(
                            identity=provider_id, agreement_id=str(point.agreement_id), conclusion=Conclusion.INCOMPLETE
                        )
                    )
                    affected.add(product)
            if listing_disagrees and known is None and history is None:
                continue
            owner = agreements.get(str(point.agreement_id))
            if known is not None and (owner is None or owner.id == known.id) and history is None:
                continue
            if history is not None:
                if not history.agreement_ids:
                    complete = False
                    continue
                if history.purchase.accepted.provider_origin != configuration.lbx_provider_origin:
                    raise PurchaseInventoryIncomplete()
                try:
                    late_observation = await observe_released_subscription(
                        history.purchase,
                        point,
                        lambda: read_inventory_candidate(
                            lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
                        ),
                        read_started_at=historical_read[0],
                        read_finished_at=historical_read[1],
                        subscription_id=int(provider_id),
                        user_id=int(current.provider_id),
                        factory=factory,
                        delegate=delegate,
                    )
                except LbxResponseInvalid:
                    complete = False
                    continue
                if late_observation.disposition == LateObjectDisposition.CLEAR:
                    if not listing_disagrees:
                        for affected_product in affected:
                            candidates[affected_product][-1] = candidates[affected_product][-1].model_copy(
                                update={"conclusion": Conclusion.INELIGIBLE}
                            )
                    continue
                if late_observation.disposition != LateObjectDisposition.UNRELATED:
                    complete = False
                    if late_observation.disposition == LateObjectDisposition.RELATIONSHIP_CONFLICT:
                        for product in products_by_tariff.get(point.tariff_id, ()):
                            product_complete[product] = False
                    continue
                # Disproof settles the historical case. Apply ordinary admission to the live object below.
            agreement = await read_inventory_candidate(
                lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
            )
            if (
                agreement is None
                or agreement.agreement_id != point.agreement_id
                or agreement.user_id != int(current.provider_id)
            ):
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
        if subscription_listing_identities(rows) != subscription_listing_identities(again):
            await retired_index.load(factory, current.customer_id, again, delegate)
            complete = False
        for product in candidates:
            product_complete[product] &= subscription_listing_identities(
                tuple(row for row in rows if product in implicated_products(row))
            ) == subscription_listing_identities(tuple(row for row in again if product in implicated_products(row)))
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
        audited_candidates=audited_candidates,
    )
