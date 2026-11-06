"""One bounded inventory scan for admission, customer work and operator proof."""

from collections import Counter
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.composition.reconciliation import reconcile_subscription
from app.core.errors import AppError
from app.core.settings import Settings
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
from app.integrations.lbx.reconciliation import read_subscription_proof, timely_point
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from app.models import ExternalSubscriptionLifecycleStatus as Lifecycle

MAX_RELEVANT_SUBSCRIPTIONS = 20


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
    conflicts, pending = set(), set()
    complete = True
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
                proof = result.proof
            except AppError:
                complete = False
                continue
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
        relevant = tuple(
            row
            for row in rows
            if (row.tariff_id in tariffs or str(row.subscription_id) in bindings or str(row.agreement_id) in agreements)
        )
        if len(relevant) > MAX_RELEVANT_SUBSCRIPTIONS:
            raise PurchaseInventoryIncomplete()
        counts = Counter(row.agreement_id for row in rows)
        for candidate in relevant:
            budget.check()
            if str(candidate.subscription_id) in bindings:
                continue
            owner = agreements.get(str(candidate.agreement_id))
            if owner is not None:
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
                            budget=budget,
                        )
                    else:
                        proof = None
                    if proof is not None:
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
                lambda: client.get_subscription(subscription_id=candidate.subscription_id, budget=budget), budget
            )
            if (point.agreement_id, point.tariff_id) != (candidate.agreement_id, candidate.tariff_id):
                complete = False
                continue
            agreement = await timely_point(
                lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
            )
            if agreement.user_id != int(current.provider_id):
                complete = False
                continue
            if agreement_is_closed(agreement) or subscription_lifecycle(point)[0] == Lifecycle.ENDED:
                continue
            conflicts.update(
                purchase.id for purchase in initial if purchase.accepted.selection.tariff_id == point.tariff_id
            )
        again = await timely_point(
            lambda: client.discover_subscriptions(user_id=int(current.provider_id), budget=budget), budget
        )
        if _identities(rows) != _identities(again):
            complete = False
    except (AppError, PreflightDeadlineExceeded, PreflightCleanupPending):
        complete = False
    return InventoryResult(
        current, tuple(versions.values()), tuple(sorted(conflicts)), tuple(sorted(pending)), complete
    )


def _identities(rows: tuple[Subscription, ...]) -> list[tuple[int, int, int]]:
    return sorted((row.subscription_id, row.agreement_id, row.tariff_id) for row in rows)
