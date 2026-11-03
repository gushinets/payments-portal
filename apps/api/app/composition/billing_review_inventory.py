"""Bounded GET-only competition proof for an explicit original-purchase resolution."""

from app.core.time import utc_now
from app.domains.billing import operator_inventory
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.operator_contracts import InventoryPurchase, ReviewInventoryProof, ReviewResolution
from app.domains.billing.operator_review import digest
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import PurchaseRefused
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.financial import NewSubscription, inventory_terminal, prove_agreement, prove_effective_terms
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State, PurchaseIntentState
from starlette.concurrency import run_in_threadpool


def _owner(
    subjects: tuple[InventoryPurchase, ...],
    resolution: ReviewResolution,
    provider_id: str,
    agreement_id: str,
    original_id: str,
) -> InventoryPurchase:
    for subject in subjects:
        purchase = subject.purchase
        operations = {op.kind: op for op in purchase.operations}
        agreement, subscription = operations.get(Kind.AGREEMENT), operations.get(Kind.SUBSCRIPTION)
        if agreement is None or subscription is None or agreement.bound_id != agreement_id:
            continue
        target = purchase.id == resolution.purchase.id
        expected = original_id if target else subscription.bound_id
        if expected != provider_id and not (
            not target
            and expected is None
            and subject.original_request is not None
            and subscription.candidate_id in {None, provider_id}
        ):
            continue
        if not target and (
            agreement.state != State.BOUND
            or subscription.state not in {State.BOUND, State.MANUAL_REVIEW}
            or purchase.state not in {PurchaseIntentState.LINKED, PurchaseIntentState.MANUAL_REVIEW}
            or (subject.reviews and not subject.review_group_supported)
            or (purchase.state == PurchaseIntentState.MANUAL_REVIEW and not subject.reviews)
        ):
            raise PurchaseRefused("purchase_inventory_incomplete", 409)
        return subject
    raise PurchaseRefused("purchase_existing_subscription_review", 409)


async def read_review_inventory(
    client: LbxServerClient,
    factory: SessionFactory,
    resolution: ReviewResolution,
    current: CustomerOpen,
    original_id: str,
    *,
    budget: PreflightBudget,
) -> ReviewInventoryProof:
    started = utc_now()

    def load() -> tuple[InventoryPurchase, ...]:
        with factory() as db:
            return operator_inventory.snapshot(db, current.customer_id)

    subjects = await run_in_threadpool(load)
    if not any(item.purchase == resolution.purchase for item in subjects):
        raise PurchaseRefused("billing_review_stale", 409)
    rows = await client.discover_subscriptions(user_id=int(current.provider_id), budget=budget)
    relevant = [row for row in rows if row.tariff_id == resolution.purchase.accepted.selection.tariff_id]
    # Same bound as ordinary purchase/inventory discovery, no unbounded source loop.
    from app.composition.purchases import MAX_RELEVANT_SUBSCRIPTIONS

    if len(relevant) > MAX_RELEVANT_SUBSCRIPTIONS:
        raise PurchaseRefused("purchase_inventory_incomplete", 409)
    if sum(str(row.subscription_id) == original_id for row in relevant) != 1:
        raise PurchaseRefused("purchase_inventory_incomplete", 409)
    for candidate in relevant:
        point = await client.get_subscription(subscription_id=candidate.subscription_id, budget=budget)
        # The canonical point URL selects the subscription (ADR 0005). These
        # relationship fields must still agree with discovery from this attempt.
        if (point.agreement_id, point.tariff_id) != (candidate.agreement_id, candidate.tariff_id):
            raise PurchaseRefused("purchase_inventory_incomplete", 409)
        agreement = await client.get_agreement(agreement_id=point.agreement_id, budget=budget)
        if agreement.user_id != int(current.provider_id):
            raise PurchaseRefused("purchase_existing_subscription_review", 409)
        if inventory_terminal(point):
            continue
        subject = _owner(subjects, resolution, str(candidate.subscription_id), str(point.agreement_id), original_id)
        purchase = subject.purchase
        if (
            purchase.account_id != resolution.purchase.account_id
            or purchase.accepted.provider_origin != resolution.purchase.accepted.provider_origin
        ):
            raise PurchaseRefused("billing_review_stale", 409)
        agreement_op = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
        if subject.original_request is not None:
            # Another inventory-reviewed UNKNOWN may prove ownership without
            # being adopted or resolved by this command. Its original possible
            # send and a unique candidate under the dedicated agreement are required.
            selection = purchase.accepted.selection
            subscription_op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
            expected_request = NewSubscription(
                agreement_id=point.agreement_id,
                tariff_id=selection.tariff_id,
                period_id=selection.period_id,
                tariff_service_id=selection.tariff_service_id,
                quantity=selection.quantity,
                outer_id=subscription_op.key,
            ).request_document()
            if (
                subject.original_request != expected_request
                or sum(row.agreement_id == point.agreement_id for row in rows) != 1
            ):
                raise PurchaseRefused("purchase_inventory_incomplete", 409)
        prove_agreement(
            agreement, user_id=int(current.provider_id), seller_id=purchase.accepted.seller_id, number=agreement_op.key
        )
        prove_effective_terms(
            point, agreement_id=point.agreement_id, selection=purchase.accepted.selection, offer=purchase.accepted.offer
        )
    again = await client.discover_subscriptions(user_id=int(current.provider_id), budget=budget)
    membership = sorted((row.subscription_id, row.agreement_id, row.tariff_id) for row in rows)
    if membership != sorted((row.subscription_id, row.agreement_id, row.tariff_id) for row in again):
        raise PurchaseRefused("purchase_inventory_incomplete", 409)
    budget.check()
    return ReviewInventoryProof(started, utc_now(), subjects, digest(membership), len(relevant))
