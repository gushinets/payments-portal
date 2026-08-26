from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utc_now
from app.domains.billing.enums import (
    EntitlementStatus,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    SubscriptionStatus,
)
from app.domains.identity.session import get_current_session
from app.infrastructure.queries.plans import get_plan_by_id, list_plans_by_ids
from app.infrastructure.queries.subscriptions import (
    get_account_subscription,
    get_relevant_entitlement_for_subscription,
    list_relevant_entitlements_for_subscriptions,
    list_account_subscriptions,
)
from app.models import AuthSession, Entitlement, Plan, Subscription, User

router = APIRouter(prefix="/api/account", tags=["account"])


class AccountSubscriptionPlanResponse(BaseModel):
    plan_id: uuid.UUID
    code: str
    name: str
    billing_period: str


class AccountSubscriptionScopeResponse(BaseModel):
    scope_type: SubscriptionScopeType
    product_id: uuid.UUID | None
    bundle_id: uuid.UUID | None


class AccountSubscriptionCurrentPeriodResponse(BaseModel):
    starts_at: datetime
    ends_at: datetime


class AccountSubscriptionCancellationResponse(BaseModel):
    cancel_requested_at: datetime | None
    canceled_at: datetime | None


class AccountSubscriptionEntitlementValidityResponse(BaseModel):
    status: EntitlementStatus | None
    valid_from: datetime | None
    valid_until: datetime | None


class AccountSubscriptionResponse(BaseModel):
    subscription_id: uuid.UUID
    plan: AccountSubscriptionPlanResponse
    scope: AccountSubscriptionScopeResponse
    status: SubscriptionStatus
    renewal_mode: SubscriptionRenewalMode
    current_period: AccountSubscriptionCurrentPeriodResponse
    cancellation: AccountSubscriptionCancellationResponse
    entitlement_validity: AccountSubscriptionEntitlementValidityResponse


class AccountSubscriptionsResponse(BaseModel):
    subscriptions: list[AccountSubscriptionResponse]


def present_loaded_account_subscription(
    *,
    subscription: Subscription,
    plan: Plan,
    entitlement: Entitlement | None,
) -> AccountSubscriptionResponse:
    return AccountSubscriptionResponse(
        subscription_id=subscription.id,
        plan=AccountSubscriptionPlanResponse(
            plan_id=plan.id,
            code=plan.code,
            name=plan.name,
            billing_period=plan.billing_period,
        ),
        scope=AccountSubscriptionScopeResponse(
            scope_type=SubscriptionScopeType(subscription.scope_type),
            product_id=subscription.product_id,
            bundle_id=subscription.bundle_id,
        ),
        status=SubscriptionStatus(subscription.status),
        renewal_mode=SubscriptionRenewalMode(subscription.renewal_mode),
        current_period=AccountSubscriptionCurrentPeriodResponse(
            starts_at=subscription.current_period_start,
            ends_at=subscription.current_period_end,
        ),
        cancellation=AccountSubscriptionCancellationResponse(
            cancel_requested_at=subscription.cancel_requested_at,
            canceled_at=subscription.canceled_at,
        ),
        entitlement_validity=AccountSubscriptionEntitlementValidityResponse(
            status=(EntitlementStatus(entitlement.status) if entitlement is not None else None),
            valid_from=entitlement.valid_from if entitlement is not None else None,
            valid_until=entitlement.valid_until if entitlement is not None else None,
        ),
    )


def present_account_subscription(
    db: Session,
    *,
    subscription: Subscription,
    plan: Plan | None = None,
    entitlement: Entitlement | None = None,
) -> AccountSubscriptionResponse:
    plan = plan or get_plan_by_id(db, subscription.plan_id)
    if plan is None:
        raise HTTPException(status_code=500, detail={"code": "subscription_plan_missing"})

    entitlement = entitlement or get_relevant_entitlement_for_subscription(db, subscription.id, now=utc_now())
    return present_loaded_account_subscription(subscription=subscription, plan=plan, entitlement=entitlement)


@router.get("/subscriptions", response_model=AccountSubscriptionsResponse)
def list_subscriptions(
    current: tuple[User, AuthSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> AccountSubscriptionsResponse:
    user, _ = current
    subscriptions = list_account_subscriptions(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
    )
    plan_ids = {subscription.plan_id for subscription in subscriptions}
    plans_by_id = {
        plan.id: plan for plan in list_plans_by_ids(db, tenant_id=user.tenant_id, region=user.region, plan_ids=plan_ids)
    }
    entitlements_by_subscription_id = list_relevant_entitlements_for_subscriptions(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        subscription_ids={subscription.id for subscription in subscriptions},
        now=utc_now(),
    )
    presented_subscriptions: list[AccountSubscriptionResponse] = []
    for subscription in subscriptions:
        plan = plans_by_id.get(subscription.plan_id)
        if plan is None:
            raise HTTPException(status_code=500, detail={"code": "subscription_plan_missing"})
        presented_subscriptions.append(
            present_loaded_account_subscription(
                subscription=subscription,
                plan=plan,
                entitlement=entitlements_by_subscription_id.get(subscription.id),
            )
        )
    return AccountSubscriptionsResponse(subscriptions=presented_subscriptions)


@router.get("/subscriptions/{subscription_id}", response_model=AccountSubscriptionResponse)
def get_subscription(
    subscription_id: uuid.UUID,
    current: tuple[User, AuthSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
) -> AccountSubscriptionResponse:
    user, _ = current
    subscription = get_account_subscription(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        subscription_id=subscription_id,
    )
    if subscription is None:
        raise HTTPException(status_code=404, detail={"code": "subscription_not_found"})

    return present_account_subscription(db, subscription=subscription)
