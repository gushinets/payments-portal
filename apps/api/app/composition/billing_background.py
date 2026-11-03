"""Worker entrypoints into shared GET-only recovery and bounded inventory proof."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.composition.billing import recover_customer
from app.composition.purchases import _inventory, recover_financial
from app.composition.purchase_inventory import MAX_RELEVANT_SUBSCRIPTIONS
from app.composition.sources import SourceResources
from app.core.errors import AppError
from app.core.settings import AppEnv, Settings
from app.core.time import utc_now
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.discovery import persist_discovery
from app.domains.billing.reconciliation_contracts import SubscriptionCandidateSubject
from app.composition.purchase_inventory import read_inventory_points, read_target_inventory
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
    discovery_ids = []
    conflicts = []
    incomplete = False
    # Share successful reads only within this attempt; each purchase still
    # requires its own original ownership and accepted-term proof.
    subscription_points: dict[int, Subscription] = {}
    agreement_points: dict[int, Agreement] = {}
    try:
        for purchase in purchases:
            try:
                try:
                    await _inventory(
                        client,
                        purchase,
                        current,
                        factory,
                        budget=budget,
                        delegate=delegate,
                        inventory=rows,
                        subscription_points=subscription_points,
                        agreement_points=agreement_points,
                    )
                except (LbxError, PurchaseRefused) as error:
                    budget.check()
                    conflict = isinstance(error, LbxScopeMismatch) or (
                        isinstance(error, PurchaseRefused) and error.code == "purchase_existing_subscription_review"
                    )
                    if conflict:
                        conflicts.append(purchase)
                    else:
                        incomplete = True
                # Preserve timely admission conflicts even if the remaining
                # paid discovery times out. Incomplete financial admission
                # must not hide independently proven owned negative facts.
                points = await read_inventory_points(
                    client,
                    purchase,
                    current,
                    budget=budget,
                    rows=rows,
                    subscription_points=subscription_points,
                    agreement_points=agreement_points,
                )
                bindings = {op.kind: op for op in purchase.operations}
                if (
                    Kind.SUBSCRIPTION in bindings
                    and bindings[Kind.SUBSCRIPTION].bound_id
                    and bindings[Kind.AGREEMENT].bound_id
                ):
                    subject = SubscriptionCandidateSubject(
                        purchase,
                        current,
                        bindings[Kind.AGREEMENT].bound_id,
                        bindings[Kind.AGREEMENT].key,
                        bindings[Kind.SUBSCRIPTION].bound_id,
                    )
                    evidence = await read_target_inventory(
                        client,
                        subject,
                        configuration,
                        factory,
                        budget=budget,
                        rows=rows,
                        points=points,
                        read_started_at=started,
                        delegate=delegate,
                    )
                    discovery_ids.append(
                        await delegate(
                            persist_discovery,
                            factory,
                            purchase,
                            current,
                            evidence,
                            work_id=claim.id,
                            generation=claim.generation,
                        )
                    )
            except (LbxError, PurchaseRefused):
                budget.check()
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
            discovery_ids=tuple(discovery_ids),
            clock_skew_seconds=configuration.paid_access_clock_skew_seconds,
            allow_simulated_metering=configuration.app_env != AppEnv.PRODUCTION,
        )
        return
    try:
        again = await client.discover_subscriptions(user_id=int(current.provider_id), budget=budget)
        budget.check()
        stable = {(row.subscription_id, row.agreement_id, row.tariff_id) for row in rows} == {
            (row.subscription_id, row.agreement_id, row.tariff_id) for row in again
        }
    except (LbxError, PreflightDeadlineExceeded, PreflightCleanupPending):
        stable = False
    # Failed, late or changed membership cannot admit a primary or extend paid
    # access. Timely owned negatives still reach the same fenced apply transaction.
    await delegate(
        recovery.apply_inventory,
        factory,
        claim,
        (),
        None if stable else "inventory_incomplete",
        discovery_ids=tuple(discovery_ids),
        clock_skew_seconds=configuration.paid_access_clock_skew_seconds if stable else None,
        allow_simulated_metering=configuration.app_env != AppEnv.PRODUCTION,
    )
