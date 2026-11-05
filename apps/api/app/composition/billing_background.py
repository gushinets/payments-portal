"""Worker entrypoints into shared GET-only recovery and bounded inventory proof."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID
from datetime import timedelta
from app.core.time import utc_now
from app.domains.billing.inventory_readback import capture_inventory

from app.composition.billing import recover_customer
from app.composition.purchases import MAX_RELEVANT_SUBSCRIPTIONS, _inventory, recover_financial
from app.composition.sources import SourceResources
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.customer_conflicts import record_customer_conflict
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import PurchaseRefused
from app.infrastructure.preflight import (
    PreflightAdmission,
    PreflightBudget,
    PreflightCleanupPending,
    PreflightDeadlineExceeded,
)
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxError, LbxScopeMismatch, LbxResponseInvalid
from app.integrations.lbx.financial import Agreement, Subscription
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
        saved = await delegate(
            work.retry_work, factory, claim, error=error.code if error.code == "billing_busy" else "recovery_incomplete"
        )
        if not saved:
            raise BillingRefused("billing_work_stale", 409) from error
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
        saved = await delegate(
            work.retry_work,
            factory,
            claim,
            error="billing_busy" if error.code == "billing_busy" else "inventory_incomplete",
        )
        if not saved:
            raise BillingRefused("billing_work_stale", 409) from error


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
    subjects = await delegate(
        capture_inventory,
        factory,
        configuration,
        current.customer_id,
        deadline=utc_now() + timedelta(seconds=budget.remaining_seconds()),
    )
    started = utc_now()
    point = await client.get_user(user_id=int(current.provider_id), budget=budget)
    if point.outer_id is None:
        raise LbxResponseInvalid()
    if str(point.user_id) != current.provider_id or point.outer_id != current.outer_key:
        await delegate(record_customer_conflict, factory, current, claim, provider_id=str(point.user_id))
        raise LbxScopeMismatch()
    rows = await client.discover_subscriptions(user_id=int(current.provider_id), budget=budget)
    tariffs = {purchase.accepted.selection.tariff_id for purchase in purchases}
    if sum(row.tariff_id in tariffs for row in rows) > MAX_RELEVANT_SUBSCRIPTIONS:
        await delegate(recovery.apply_inventory, factory, claim, (), "inventory_incomplete")
        return
    conflicts = []
    findings = {}
    incomplete = False
    # Share successful reads only within this attempt; each purchase still
    # requires its own original ownership and accepted-term proof.
    subscription_points: dict[int, Subscription] = {}
    agreement_points: dict[int, Agreement] = {}
    try:
        for purchase in purchases:
            try:
                result = await _inventory(
                    client,
                    purchase,
                    current,
                    factory,
                    budget=budget,
                    delegate=delegate,
                    inventory=rows,
                    subscription_points=subscription_points,
                    agreement_points=agreement_points,
                    subjects=subjects,
                    user=point,
                    read_started_at=started,
                )
                findings.update((item.subject.purchase.id, item) for item in result.findings)
                result.require_complete()
            except (LbxError, PurchaseRefused) as error:
                budget.check()
                conflict = isinstance(error, LbxScopeMismatch) or (
                    isinstance(error, PurchaseRefused) and error.code == "purchase_existing_subscription_review"
                )
                if conflict:
                    conflicts.append(purchase)
                else:
                    incomplete = True
        budget.check()
    except (PreflightDeadlineExceeded, PreflightCleanupPending):
        # Keep conflicts proved within the read window; no late result is adopted.
        incomplete = True
    # Evaluate every product before changing any purchase's ownership proof.
    # Completing work on the first conflict would starve later product scopes.
    if conflicts or incomplete:
        await delegate(
            recovery.apply_inventory,
            factory,
            claim,
            tuple(conflicts),
            "inventory_conflict" if conflicts else "inventory_incomplete",
            configuration=configuration,
            findings=tuple(findings.values()),
        )
        return
    try:
        again = await client.discover_subscriptions(user_id=int(current.provider_id), budget=budget)
        budget.check()
    except AppError:
        await delegate(
            recovery.apply_inventory,
            factory,
            claim,
            (),
            "inventory_incomplete",
            configuration=configuration,
            findings=tuple(findings.values()),
        )
        return
    if {(row.subscription_id, row.agreement_id, row.tariff_id) for row in rows} != {
        (row.subscription_id, row.agreement_id, row.tariff_id) for row in again
    }:
        await delegate(
            recovery.apply_inventory,
            factory,
            claim,
            (),
            "inventory_incomplete",
            configuration=configuration,
            findings=tuple(findings.values()),
        )
        return
    budget.check()
    await delegate(
        recovery.apply_inventory,
        factory,
        claim,
        (),
        None,
        configuration=configuration,
        findings=tuple(findings.values()),
    )
