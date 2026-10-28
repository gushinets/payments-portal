"""Worker entrypoints into shared GET-only recovery and bounded inventory proof."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.composition.billing import recover_customer
from app.composition.purchases import MAX_RELEVANT_SUBSCRIPTIONS, _inventory, recover_financial
from app.composition.sources import SourceResources
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.customer_conflicts import record_customer_conflict
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import PurchaseRefused
from app.infrastructure.preflight import PreflightAdmission, PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxScopeMismatch, LbxResponseInvalid
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State


async def recover_operation(
    client: LbxServerClient,
    admission: PreflightAdmission,
    configuration: Settings,
    *,
    factory: SessionFactory,
    claim: WorkClaim,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    kind, user_id, purchase_id, current, state = await delegate(recovery.subject, factory, configuration, claim)
    if state in {State.PENDING, State.PROVEN_NOT_SENT, State.BOUND}:
        await delegate(recovery.finish_recovery, factory, claim)
        return
    try:
        if kind == Kind.CUSTOMER:
            await recover_customer(client, factory, current, budget=budget, work_claim=claim, delegate=delegate)
        else:
            await recover_financial(
                SourceResources(admission, None, client, billing=admission),
                configuration,
                factory=factory,
                user_id=user_id,
                purchase_id=purchase_id,
                operation_id=UUID(claim.reference),
                work_claim=claim,
                budget=budget,
                delegate=delegate,
            )
    except AppError as error:
        # Local contention is retryable queue work, never a source result or
        # proof of no-send. Shared apply owns any authoritative conflict.
        await delegate(
            work.retry_work, factory, claim, error=error.code if error.code == "billing_busy" else "recovery_incomplete"
        )
        return
    await delegate(recovery.finish_recovery, factory, claim)


async def inventory_customer(
    client: LbxServerClient,
    configuration: Settings,
    *,
    factory: SessionFactory,
    claim: WorkClaim,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    try:
        await _inventory_customer(client, configuration, factory=factory, claim=claim, budget=budget, delegate=delegate)
    except AppError as error:
        await delegate(
            work.retry_work,
            factory,
            claim,
            error="billing_busy" if error.code == "billing_busy" else "inventory_incomplete",
        )


async def _inventory_customer(
    client: LbxServerClient,
    configuration: Settings,
    *,
    factory: SessionFactory,
    claim: WorkClaim,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    current, purchases = await delegate(recovery.customer_snapshot, factory, configuration, UUID(claim.reference))
    point = await client.get_user(user_id=int(current.provider_id), budget=budget)
    if point.outer_id is None:
        raise LbxResponseInvalid()
    if str(point.user_id) != current.provider_id or point.outer_id != current.outer_key:
        await delegate(record_customer_conflict, factory, current, claim)
        raise LbxScopeMismatch()
    rows = await client.discover_subscriptions(user_id=int(current.provider_id), budget=budget)
    tariffs = {purchase.accepted.selection.tariff_id for purchase in purchases}
    if sum(row.tariff_id in tariffs for row in rows) > MAX_RELEVANT_SUBSCRIPTIONS:
        await delegate(recovery.apply_inventory, factory, claim, (), "inventory_incomplete")
        return
    conflicts = []
    incomplete = False
    for purchase in purchases:
        try:
            await _inventory(client, purchase, current, factory, budget=budget, delegate=delegate, inventory=rows)
        except (LbxScopeMismatch, PurchaseRefused) as error:
            budget.check()
            conflict = isinstance(error, LbxScopeMismatch) or error.code == "purchase_existing_subscription_review"
            if conflict:
                conflicts.append(purchase)
            else:
                incomplete = True
    # Evaluate every product before changing any purchase's ownership proof.
    # Completing work on the first conflict would starve later product scopes.
    if conflicts or incomplete:
        budget.check()
        await delegate(
            recovery.apply_inventory,
            factory,
            claim,
            tuple(conflicts),
            "inventory_conflict" if conflicts else "inventory_incomplete",
        )
        return
    again = await client.discover_subscriptions(user_id=int(current.provider_id), budget=budget)
    if {(row.subscription_id, row.agreement_id, row.tariff_id) for row in rows} != {
        (row.subscription_id, row.agreement_id, row.tariff_id) for row in again
    }:
        await delegate(recovery.apply_inventory, factory, claim, (), "inventory_incomplete")
        return
    budget.check()
    await delegate(recovery.apply_inventory, factory, claim, (), None)
