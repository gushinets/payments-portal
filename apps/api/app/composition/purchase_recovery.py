"""Shared GET-only financial recovery used by worker and privileged CLI."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.composition.purchase_observation import prepared_subscription_observation
from app.composition.sources import SourceResources
from app.core.settings import Settings
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.customer_conflicts import record_customer_conflict
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import FinancialOperation, Purchase, PurchaseRefused
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxError, LbxScopeMismatch, LbxResponseInvalid
from app.integrations.lbx.financial import LbxFinancialEnded
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State


async def _recover_one(
    client: LbxServerClient,
    purchase: Purchase,
    operation: FinancialOperation,
    customer: CustomerOpen,
    factory: SessionFactory,
    *,
    budget: PreflightBudget,
    work_claim: WorkClaim | None = None,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
    payment_presentation: bool = False,
) -> bool:
    from app.composition.purchases import _find_financial

    try:
        found = await _find_financial(client, purchase, operation, customer, budget=budget)
    except LbxScopeMismatch as error:
        if payment_presentation and operation.state == State.BOUND and isinstance(error, LbxFinancialEnded):
            # A previously bound object ending is not a financial identity conflict.
            raise PurchaseRefused("purchase_not_prepared", 409) from None
        await delegate(financial.financial_pending, factory, purchase, operation, conflict=True, work_claim=work_claim)
        return False
    except LbxError as error:
        facts = error.response_facts
        await delegate(
            financial.financial_pending,
            factory,
            purchase,
            operation,
            work_claim=work_claim,
            failure_facts={
                "code": error.code,
                "http_status": facts.http_status if facts else None,
                "lbx_code": facts.lbx_code if facts else None,
                "reason": facts.reason if facts else "unknown",
            },
        )
        return False
    if found is None:
        if operation.state not in {State.PENDING, State.PROVEN_NOT_SENT}:
            await delegate(financial.financial_pending, factory, purchase, operation, work_claim=work_claim)
        return False
    # No absent/unsent financial operation is adopted from a coincidental object.
    if operation.state in {State.PENDING, State.PROVEN_NOT_SENT}:
        await delegate(financial.financial_pending, factory, purchase, operation, conflict=True, work_claim=work_claim)
        return False
    budget.check()
    provider_id, point = found
    await delegate(
        financial.bind_financial,
        factory,
        purchase,
        operation,
        provider_id,
        work_claim=work_claim,
        observation=prepared_subscription_observation(point, purchase) if point else None,
    )
    return True


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
    from app.composition.purchases import _connection, _operation

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
            await delegate(record_customer_conflict, factory, current, work_claim, provider_id=str(point.user_id))
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
