"""Worker entrypoints into shared GET-only recovery and bounded inventory proof."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.composition.billing import recover_customer
from app.composition.purchases import recover_financial
from app.composition.purchase_inventory import collect_inventory
from app.composition.sources import SourceResources
from app.core.errors import AppError
from app.domains.billing.contracts import BillingRefused
from app.core.settings import AppEnv, Settings
from app.domains.billing.discovery import persist_discoveries
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.preflight import (
    PreflightAdmission,
    PreflightBudget,
)
from app.integrations.lbx.client import LbxServerClient
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
    admission: PreflightAdmission,
    configuration: Settings,
    *,
    factory: SessionFactory,
    claim: WorkClaim,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    try:
        await _inventory_customer(
            client, admission, configuration, factory=factory, claim=claim, budget=budget, delegate=delegate
        )
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
    admission: PreflightAdmission,
    configuration: Settings,
    *,
    factory: SessionFactory,
    claim: WorkClaim,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    current, _ = await delegate(recovery.customer_snapshot, factory, configuration, UUID(claim.reference))
    result = await collect_inventory(
        client,
        admission,
        configuration,
        factory=factory,
        customer=current,
        budget=budget,
        work_claim=claim,
        delegate=delegate,
    )
    reason = (
        "inventory_conflict"
        if result.conflicts
        else ("inventory_incomplete" if not result.complete or result.pending else None)
    )
    result = await delegate(persist_discoveries, factory, claim, result)
    await delegate(
        recovery.apply_inventory,
        factory,
        claim,
        result,
        reason,
        clock_skew_seconds=configuration.paid_access_clock_skew_seconds,
        allow_simulated_metering=configuration.app_env != AppEnv.PRODUCTION,
    )
