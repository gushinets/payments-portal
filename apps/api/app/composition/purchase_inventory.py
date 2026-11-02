"""Shared bounded customer discovery/point reads for admission and paid primary."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.discovery import DiscoveredCandidate, ProductDiscovery
from app.domains.billing.paid_policy import CandidateConclusion, PaidDecision, paid_decision
from app.domains.billing.reconciliation_contracts import (
    ReconciliationSubject,
    SubscriptionCandidateSubject,
    SubscriptionProof,
)
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.inventory import inventory_purchase, other_inventory_purchase
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete, PurchaseRefused
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxResponseInvalid, LbxScopeMismatch, LbxError
from app.integrations.lbx.financial import (
    Agreement,
    Subscription,
    inventory_terminal,
    prove_agreement,
    prove_effective_terms,
)
from app.integrations.lbx.reconciliation import read_subscription_proof
from app.models import ExternalCreateOperationKind as Kind, PurchaseIntentState

MAX_RELEVANT_SUBSCRIPTIONS = 20


def _bound(purchase: Purchase, kind: Kind) -> str | None:
    return next(op.bound_id for op in purchase.operations if op.kind == kind)


async def read_inventory_points(
    client: LbxServerClient,
    purchase: Purchase,
    customer: CustomerOpen,
    *,
    budget: PreflightBudget,
    rows: tuple[Subscription, ...],
    subscription_points: dict[int, Subscription] | None = None,
    agreement_points: dict[int, Agreement] | None = None,
) -> tuple[tuple[Subscription, Agreement], ...]:
    subscription_points = {} if subscription_points is None else subscription_points
    agreement_points = {} if agreement_points is None else agreement_points
    relevant = [row for row in rows if row.tariff_id == purchase.accepted.selection.tariff_id]
    if len(relevant) > MAX_RELEVANT_SUBSCRIPTIONS:
        raise PurchaseInventoryIncomplete()
    result = []
    for candidate in relevant:
        budget.check()
        point = subscription_points.get(candidate.subscription_id)
        if point is None:
            point = await client.get_subscription(subscription_id=candidate.subscription_id, budget=budget)
            subscription_points[candidate.subscription_id] = point
        if (point.subscription_id, point.agreement_id, point.tariff_id) != (
            candidate.subscription_id,
            candidate.agreement_id,
            candidate.tariff_id,
        ):
            raise PurchaseInventoryIncomplete()
        agreement = agreement_points.get(point.agreement_id)
        if agreement is None:
            agreement = await client.get_agreement(agreement_id=point.agreement_id, budget=budget)
            agreement_points[point.agreement_id] = agreement
        if agreement.user_id != int(customer.provider_id):
            raise LbxScopeMismatch()
        result.append((point, agreement))
    return tuple(result)


def _identities(rows: tuple[Subscription, ...]) -> set[tuple[int, int, int]]:
    return {(row.subscription_id, row.agreement_id, row.tariff_id) for row in rows}


async def inventory(
    client: LbxServerClient,
    purchase: Purchase,
    customer: CustomerOpen,
    factory: SessionFactory,
    *,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
    inventory: tuple[Subscription, ...] | None = None,
    subscription_points: dict[int, Subscription] | None = None,
    agreement_points: dict[int, Agreement] | None = None,
) -> None:
    rows = (
        inventory
        if inventory is not None
        else await client.discover_subscriptions(user_id=int(customer.provider_id), budget=budget)
    )
    relevant = [row for row in rows if row.tariff_id == purchase.accepted.selection.tariff_id]
    if len(relevant) > MAX_RELEVANT_SUBSCRIPTIONS:
        raise PurchaseInventoryIncomplete()
    subscription_points = {} if subscription_points is None else subscription_points
    agreement_points = {} if agreement_points is None else agreement_points
    for candidate in relevant:
        # Apply each checked point before another candidate can exhaust the
        # shared budget; paid discovery reuses these same attempt-local reads.
        points = await read_inventory_points(
            client,
            purchase,
            customer,
            budget=budget,
            rows=(candidate,),
            subscription_points=subscription_points,
            agreement_points=agreement_points,
        )
        point, agreement = points[0]
        try:
            terminal = inventory_terminal(point)
        except LbxResponseInvalid:
            raise PurchaseInventoryIncomplete() from None
        if not terminal and str(point.subscription_id) != _bound(purchase, Kind.SUBSCRIPTION):
            other = await delegate(
                other_inventory_purchase, factory, purchase, point.subscription_id, point.agreement_id
            )
            if other is None:
                raise PurchaseRefused("purchase_existing_subscription_review", 409)
            prove_agreement(
                agreement,
                user_id=int(customer.provider_id),
                seller_id=other.accepted.seller_id,
                number=next(op.key for op in other.operations if op.kind == Kind.AGREEMENT),
            )
            prove_effective_terms(
                point, agreement_id=point.agreement_id, selection=other.accepted.selection, offer=other.accepted.offer
            )
            if other.state != PurchaseIntentState.LINKED:
                raise PurchaseInventoryIncomplete()
    if inventory is None and _identities(rows) != _identities(
        await client.discover_subscriptions(user_id=int(customer.provider_id), budget=budget)
    ):
        raise PurchaseInventoryIncomplete()


async def read_target_inventory(
    client: LbxServerClient,
    subject: ReconciliationSubject | SubscriptionCandidateSubject,
    configuration: Settings,
    factory: SessionFactory,
    *,
    budget: PreflightBudget,
    proof: SubscriptionProof | None = None,
    rows: tuple[Subscription, ...] | None = None,
    points: tuple[tuple[Subscription, Agreement], ...] | None = None,
    read_started_at: datetime | None = None,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
) -> ProductDiscovery:
    started = read_started_at or utc_now()
    purchase, customer = subject.purchase, subject.customer
    candidates = []
    linked_proof = None
    complete = True
    try:
        initial = (
            rows
            if rows is not None
            else await client.discover_subscriptions(user_id=int(customer.provider_id), budget=budget)
        )
        if points is None:
            points = await read_inventory_points(client, purchase, customer, budget=budget, rows=initial)
        # Preserve the linked point proof before unrelated candidates can make
        # discovery incomplete. Completeness gates admission, not owned negatives.
        for point, agreement in sorted(
            points,
            key=lambda item: (
                (str(item[0].subscription_id), str(item[0].agreement_id))
                != (subject.provider_subscription_id, subject.agreement_id)
            ),
        ):
            own = (
                str(point.subscription_id) == subject.provider_subscription_id
                and str(point.agreement_id) == subject.agreement_id
            )
            original_purchase = purchase if own else None
            agreement_key = subject.agreement_key
            if not own:
                if inventory_terminal(point):
                    # Canonical point and customer ownership are already proven.
                    # An ended source cannot compete, even without Portal consent.
                    candidates.append(
                        DiscoveredCandidate(
                            identity=str(point.subscription_id),
                            agreement_id=str(point.agreement_id),
                            conclusion=CandidateConclusion.INELIGIBLE,
                            reads=("subscription", "agreement"),
                            reasons=("ended",),
                        )
                    )
                    continue
                other = await delegate(inventory_purchase, factory, purchase, point.subscription_id, point.agreement_id)
                if other is not None:
                    prove_agreement(
                        agreement,
                        user_id=int(customer.provider_id),
                        seller_id=other.accepted.seller_id,
                        number=next(op.key for op in other.operations if op.kind == Kind.AGREEMENT),
                    )
                    prove_effective_terms(
                        point,
                        agreement_id=point.agreement_id,
                        selection=other.accepted.selection,
                        offer=other.accepted.offer,
                    )
                    if other.state != PurchaseIntentState.LINKED:
                        raise PurchaseInventoryIncomplete()
                    if other.accepted.selection.product_id != purchase.accepted.selection.product_id:
                        continue  # Permanent original evidence proves another product.
                    original_purchase = other
                    agreement_key = next(op.key for op in other.operations if op.kind == Kind.AGREEMENT)
            candidate_subject = SubscriptionCandidateSubject(
                original_purchase or purchase,
                customer,
                str(point.agreement_id),
                agreement_key,
                str(point.subscription_id),
            )
            observed = await read_subscription_proof(
                client,
                candidate_subject,
                configuration,
                budget=budget,
                point_reads=(point, agreement),
                read_started_at=started,
            )
            # Own point proof must agree with the earlier claim's proof. A
            # transition during discovery cannot authorize the older conclusion.
            if own:
                linked_proof = observed
            decision = paid_decision(observed)
            if own and proof is not None and (decision != paid_decision(proof) or observed.calendar != proof.calendar):
                complete = False
            conclusion = CandidateConclusion.INCOMPLETE
            if observed.complete:
                conclusion = (
                    CandidateConclusion.ELIGIBLE if decision == PaidDecision.GRANT else CandidateConclusion.INELIGIBLE
                )
            if original_purchase is None:
                # Unknown same-tariff objects have no original accepted meaning.
                # Never classify them as irrelevant using today's tariff alone.
                conclusion = CandidateConclusion.INCOMPLETE
            complete = complete and conclusion != CandidateConclusion.INCOMPLETE
            candidates.append(
                DiscoveredCandidate(
                    identity=str(point.subscription_id),
                    agreement_id=str(point.agreement_id),
                    purchase_id=original_purchase.id if original_purchase else None,
                    accepted_fingerprint=original_purchase.accepted.offer.fingerprint if original_purchase else None,
                    conclusion=conclusion,
                    reads=observed.reads,
                    reasons=observed.reasons,
                    calendar=observed.calendar,
                )
            )
        if rows is None and _identities(initial) != _identities(
            await client.discover_subscriptions(user_id=int(customer.provider_id), budget=budget)
        ):
            complete = False
        budget.check()
    except (LbxError, PurchaseRefused, PreflightDeadlineExceeded):
        complete = False
    return ProductDiscovery(
        read_started_at=started,
        read_finished_at=utc_now(),
        complete=complete,
        candidates=tuple(candidates),
        linked_proof=linked_proof,
    )
