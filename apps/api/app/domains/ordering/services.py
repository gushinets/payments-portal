from __future__ import annotations

from sqlalchemy.orm import Session

from app.domains.billing.schemas import BundleStatus, PlanScopeType, ProductStatus
from app.domains.ordering.exceptions import SellablePlanResolutionError
from app.domains.ordering.schemas import ResolveSellablePlanInput, SellablePlan
from app.infrastructure.queries.plan import (
    get_active_plan_by_code,
    get_bundle_by_id,
    get_product_by_id,
)


def resolve_checkout_sellable_plan(
    db: Session,
    *,
    payload: ResolveSellablePlanInput,
) -> SellablePlan:
    plan = get_active_plan_by_code(
        db,
        tenant_id=payload.tenant_id,
        region=payload.region,
        plan_code=payload.plan_code,
    )
    if plan is None:
        raise SellablePlanResolutionError(
            reason="plan_not_found",
            payload=payload,
        )

    if plan.scope_type == PlanScopeType.PRODUCT.value:
        product = get_product_by_id(db, product_id=plan.product_id)
        if product is None or product.status != ProductStatus.ACTIVE.value or product.code != payload.entrypoint_code:
            raise SellablePlanResolutionError(
                reason="invalid_product_plan",
                payload=payload,
                plan=plan,
            )
    elif plan.scope_type == PlanScopeType.BUNDLE.value:
        bundle = get_bundle_by_id(db, bundle_id=plan.bundle_id)
        if bundle is None or bundle.status != BundleStatus.ACTIVE.value or bundle.code != payload.entrypoint_code:
            raise SellablePlanResolutionError(
                reason="invalid_bundle_plan",
                payload=payload,
                plan=plan,
            )
    elif plan.scope_type == PlanScopeType.ALL_ACCESS.value:
        if payload.entrypoint_code not in {PlanScopeType.ALL_ACCESS.value, plan.code}:
            raise SellablePlanResolutionError(
                reason="entrypoint_scope_mismatch",
                payload=payload,
                plan=plan,
            )
    else:
        raise SellablePlanResolutionError(
            reason="unsupported_scope_type",
            payload=payload,
            plan=plan,
        )

    return SellablePlan.model_validate(plan)
