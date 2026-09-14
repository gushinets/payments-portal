from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.billing.service.account import (
    AccountSubscriptionResult,
    get_account_subscription_result,
    list_account_subscription_results,
)
from app.http_dependencies import get_current_session
from app.models import (
    AuthSession,
    EntitlementStatus,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    SubscriptionStatus,
    User,
)

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
    included_product_ids: list[uuid.UUID]


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


def present_account_subscription(
    result: AccountSubscriptionResult,
) -> AccountSubscriptionResponse:
    return AccountSubscriptionResponse(
        subscription_id=result.subscription_id,
        plan=AccountSubscriptionPlanResponse(
            plan_id=result.plan_id,
            code=result.plan_code,
            name=result.plan_name,
            billing_period=result.plan_billing_period,
        ),
        scope=AccountSubscriptionScopeResponse(
            scope_type=result.scope_type,
            product_id=result.product_id,
            bundle_id=result.bundle_id,
            included_product_ids=list(result.included_product_ids),
        ),
        status=result.status,
        renewal_mode=result.renewal_mode,
        current_period=AccountSubscriptionCurrentPeriodResponse(
            starts_at=result.current_period_start,
            ends_at=result.current_period_end,
        ),
        cancellation=AccountSubscriptionCancellationResponse(
            cancel_requested_at=result.cancel_requested_at,
            canceled_at=result.canceled_at,
        ),
        entitlement_validity=AccountSubscriptionEntitlementValidityResponse(
            status=result.entitlement_status,
            valid_from=result.entitlement_valid_from,
            valid_until=result.entitlement_valid_until,
        ),
    )


@router.get("/subscriptions", response_model=AccountSubscriptionsResponse)
def list_subscriptions(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> AccountSubscriptionsResponse:
    user, _ = current
    results = list_account_subscription_results(db, user=user)
    return AccountSubscriptionsResponse(subscriptions=[present_account_subscription(result) for result in results])


@router.get("/subscriptions/{subscription_id}", response_model=AccountSubscriptionResponse)
def get_subscription(
    subscription_id: uuid.UUID,
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> AccountSubscriptionResponse:
    user, _ = current
    result = get_account_subscription_result(
        db,
        user=user,
        subscription_id=subscription_id,
    )
    return present_account_subscription(result)
