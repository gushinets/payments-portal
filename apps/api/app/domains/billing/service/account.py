from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domains.billing.errors import (
    SubscriptionNotFoundError,
    SubscriptionPlanMissingError,
)
from app.infrastructure.queries.plans import get_plan_by_id, list_plans_by_ids
from app.infrastructure.queries.subscriptions import (
    get_account_subscription,
    get_relevant_entitlement_for_subscription,
    list_account_subscriptions,
    list_current_bundle_product_ids,
    list_relevant_entitlements_for_subscriptions,
)
from app.models import (
    BillingPeriod,
    Entitlement,
    EntitlementStatus,
    Plan,
    Subscription,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    SubscriptionStatus,
    User,
)


@dataclass(frozen=True)
class AccountSubscriptionResult:
    subscription_id: uuid.UUID
    plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    plan_billing_period: BillingPeriod
    scope_type: SubscriptionScopeType
    product_id: uuid.UUID | None
    bundle_id: uuid.UUID | None
    included_product_ids: tuple[uuid.UUID, ...]
    status: SubscriptionStatus
    renewal_mode: SubscriptionRenewalMode
    current_period_start: datetime
    current_period_end: datetime
    cancel_requested_at: datetime | None
    canceled_at: datetime | None
    entitlement_status: EntitlementStatus | None
    entitlement_valid_from: datetime | None
    entitlement_valid_until: datetime | None


def list_account_subscription_results(
    db: Session,
    *,
    user: User,
) -> list[AccountSubscriptionResult]:
    subscriptions = list_account_subscriptions(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
    )
    plan_ids = {subscription.plan_id for subscription in subscriptions}
    plans_by_id = {
        plan.id: plan
        for plan in list_plans_by_ids(
            db,
            tenant_id=user.tenant_id,
            region=user.region,
            plan_ids=plan_ids,
        )
    }
    now = utc_now()
    entitlements_by_subscription_id = list_relevant_entitlements_for_subscriptions(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        subscription_ids={subscription.id for subscription in subscriptions},
        now=now,
    )
    included_product_ids_by_bundle = list_current_bundle_product_ids(
        db,
        tenant_id=user.tenant_id,
        bundle_ids={subscription.bundle_id for subscription in subscriptions if subscription.bundle_id is not None},
        now=now,
    )

    results: list[AccountSubscriptionResult] = []
    for subscription in subscriptions:
        plan = plans_by_id.get(subscription.plan_id)
        if plan is None:
            raise SubscriptionPlanMissingError()
        results.append(
            _account_subscription_result(
                subscription=subscription,
                plan=plan,
                entitlement=entitlements_by_subscription_id.get(subscription.id),
                included_product_ids=included_product_ids_by_bundle.get(subscription.bundle_id, []),
            )
        )
    return results


def get_account_subscription_result(
    db: Session,
    *,
    user: User,
    subscription_id: uuid.UUID,
) -> AccountSubscriptionResult:
    subscription = get_account_subscription(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        subscription_id=subscription_id,
    )
    if subscription is None:
        raise SubscriptionNotFoundError()

    plan = get_plan_by_id(db, subscription.plan_id)
    if plan is None:
        raise SubscriptionPlanMissingError()

    now = utc_now()
    entitlement = get_relevant_entitlement_for_subscription(db, subscription.id, now=now)
    included_product_ids_by_bundle = list_current_bundle_product_ids(
        db,
        tenant_id=subscription.tenant_id,
        bundle_ids={subscription.bundle_id} if subscription.bundle_id is not None else set(),
        now=now,
    )
    return _account_subscription_result(
        subscription=subscription,
        plan=plan,
        entitlement=entitlement,
        included_product_ids=included_product_ids_by_bundle.get(subscription.bundle_id, []),
    )


def _account_subscription_result(
    *,
    subscription: Subscription,
    plan: Plan,
    entitlement: Entitlement | None,
    included_product_ids: list[uuid.UUID],
) -> AccountSubscriptionResult:
    return AccountSubscriptionResult(
        subscription_id=subscription.id,
        plan_id=plan.id,
        plan_code=plan.code,
        plan_name=plan.name,
        plan_billing_period=plan.billing_period,
        scope_type=subscription.scope_type,
        product_id=subscription.product_id,
        bundle_id=subscription.bundle_id,
        included_product_ids=tuple(included_product_ids),
        status=subscription.status,
        renewal_mode=subscription.renewal_mode,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_requested_at=subscription.cancel_requested_at,
        canceled_at=subscription.canceled_at,
        entitlement_status=entitlement.status if entitlement is not None else None,
        entitlement_valid_from=entitlement.valid_from if entitlement is not None else None,
        entitlement_valid_until=entitlement.valid_until if entitlement is not None else None,
    )
