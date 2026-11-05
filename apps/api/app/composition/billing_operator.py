"""Privileged entrypoints reuse the worker's proof, fenced apply and bind paths."""

from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.composition.purchases import _connection
from app.composition.purchase_recovery import recover_one
from app.composition.reconciliation import reconcile_subscription
from app.composition.sources import SourceResources
from app.core.settings import Settings
from app.domains.billing.operator_contracts import ResolutionRequest
from app.domains.billing.operator_diagnostics import purchase_subscription
from app.domains.billing.operator_review import prepare_resolution
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseRefused


async def reconcile_purchase(
    sources: SourceResources, configuration: Settings, *, factory: SessionFactory, user_id: UUID, purchase_id: UUID
) -> UUID:
    subscription_id = await run_in_threadpool(purchase_subscription, factory, configuration, user_id, purchase_id)
    result = await reconcile_subscription(
        sources.require_lbx(), sources.billing, configuration, factory=factory, subscription_id=subscription_id
    )
    return result.observation_id


async def resolve_review(
    sources: SourceResources,
    configuration: Settings,
    *,
    factory: SessionFactory,
    request: ResolutionRequest,
    principal: str,
) -> dict:
    if sources.billing is None:
        raise PurchaseRefused("purchase_billing_not_configured", 503)
    resolution = await run_in_threadpool(
        prepare_resolution,
        factory,
        configuration,
        request,
        principal,
        io_timeout_seconds=sources.billing.policy.total_timeout_seconds,
    )
    if isinstance(resolution, dict):
        return resolution
    purchase = resolution.purchase
    _connection(purchase, configuration)
    if request.resolution == "restore-original":
        result = await reconcile_subscription(
            sources.require_lbx(),
            sources.billing,
            configuration,
            factory=factory,
            subscription_id=UUID(resolution.before["subscription_id"]),
            resolution=resolution,
        )
        return {
            "review_case_id": str(request.case_id),
            "outcome": "resolved",
            "observation_id": str(result.observation_id),
        }
    operation = next(op for op in purchase.operations if op.id == request.operation_id)
    async with sources.billing.operation(bound_scope=False) as budget:
        customer = await run_in_threadpool(service.customer_for_purchase, factory, configuration, purchase)
        await recover_one(
            sources, configuration, purchase, operation, customer, factory, budget=budget, resolution=resolution
        )
    return {"review_case_id": str(request.case_id), "outcome": "resolved"}
