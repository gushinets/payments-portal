"""Shared GET-only financial recovery used by worker and privileged CLI."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.composition.sources import SourceResources
from app.core.settings import Settings
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.customer_conflicts import record_customer_conflict
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase, PurchaseRefused
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.errors import LbxScopeMismatch, LbxResponseInvalid
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State


async def recover_financial(
    sources: SourceResources,
    configuration: Settings,
    *,
    factory: SessionFactory,
    user_id: UUID,
    purchase_id: UUID,
    operation_id: UUID | None = None,
    work_claim: WorkClaim | None = None,
    budget: PreflightBudget | None = None,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
) -> Purchase:
    """Shared GET-only recovery; background callers cannot acquire send authority."""
    from app.composition.reconciliation import _budget
    from app.composition.purchases import _connection, _operation, _recover_one

    purchase = await delegate(service.inspect_purchase, factory, configuration, user_id, purchase_id)
    _connection(purchase, configuration)
    if not purchase.held or sources.billing is None:
        raise PurchaseRefused("purchase_scope_released", 409)
    await delegate(service.verify_original_consent, factory, purchase)
    async with _budget(sources.billing, budget) as active_budget:
        current = await delegate(service.customer_for_purchase, factory, configuration, purchase)
        # Paired identity is rechecked without clearing a customer conflict or
        # completing a different consumer's customer-recovery job.
        point = await sources.require_lbx().get_user(user_id=int(current.provider_id), budget=active_budget)
        if point.outer_id is None:
            raise LbxResponseInvalid()
        if str(point.user_id) != current.provider_id or point.outer_id != current.outer_key:
            await delegate(record_customer_conflict, factory, current, work_claim)
            raise LbxScopeMismatch()
        for kind in (Kind.AGREEMENT, Kind.SUBSCRIPTION):
            purchase = await delegate(service.read_purchase, factory, user_id, purchase_id)
            operation = _operation(purchase, kind)
            if operation_id is not None and operation.id != operation_id:
                continue
            # Bound objects are now reconciled through the lifecycle seam. In
            # particular an ended subscription must not pass preparation proof.
            if operation.state in {State.PENDING, State.PROVEN_NOT_SENT, State.BOUND}:
                continue
            if not await _recover_one(
                sources.require_lbx(),
                purchase,
                operation,
                current,
                factory,
                budget=active_budget,
                work_claim=work_claim,
                delegate=delegate,
            ):
                break
        return await delegate(service.read_purchase, factory, user_id, purchase_id)
