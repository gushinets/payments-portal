from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import case
from sqlalchemy.orm import Session

from app.domains.billing.enums import (
    EntitlementStatus,
    SubscriptionEventType,
    SubscriptionStatus,
)
from app.models import Entitlement, Subscription, SubscriptionEvent


ORDER_LOOKUP_SUBSCRIPTION_EVENT_TYPES = (
    SubscriptionEventType.PAID_PERIOD_ACTIVATED.value,
    SubscriptionEventType.LEGACY_ACCESS_MIGRATED.value,
)


def get_subscription_by_id(db: Session, subscription_id: uuid.UUID, *, for_update: bool = False) -> Subscription | None:
    query = db.query(Subscription).filter(Subscription.id == subscription_id)
    return (query.with_for_update() if for_update else query).first()


def get_account_subscription(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
    subscription_id: uuid.UUID,
) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(
            Subscription.id == subscription_id,
            Subscription.tenant_id == tenant_id,
            Subscription.region == region,
            Subscription.user_id == user_id,
        )
        .first()
    )


def list_account_subscriptions(db: Session, *, tenant_id: str, region: str, user_id: uuid.UUID) -> list[Subscription]:
    return (
        db.query(Subscription)
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.region == region,
            Subscription.user_id == user_id,
        )
        .order_by(Subscription.current_period_end.desc(), Subscription.created_at.desc())
        .all()
    )


def get_subscription_event_by_operation_key(db: Session, key: str) -> SubscriptionEvent | None:
    return db.query(SubscriptionEvent).filter(SubscriptionEvent.operation_idempotency_key == key).first()


def get_subscription_for_event(db: Session, event: SubscriptionEvent) -> Subscription | None:
    return get_subscription_by_id(db, event.subscription_id)


def get_current_entitlement(
    db: Session,
    subscription_id: uuid.UUID,
    *,
    now: datetime,
    for_update: bool = False,
) -> Entitlement | None:
    query = (
        db.query(Entitlement)
        .filter(
            Entitlement.subscription_id == subscription_id,
            Entitlement.status == EntitlementStatus.ACTIVE.value,
            Entitlement.valid_from <= now,
            Entitlement.valid_until > now,
        )
        .order_by(Entitlement.valid_until.desc(), Entitlement.created_at.desc())
    )
    return (query.with_for_update() if for_update else query).first()


def get_latest_entitlement_for_subscription(db: Session, subscription_id: uuid.UUID) -> Entitlement | None:
    return (
        db.query(Entitlement)
        .filter(Entitlement.subscription_id == subscription_id)
        .order_by(Entitlement.valid_until.desc(), Entitlement.valid_from.desc(), Entitlement.created_at.desc())
        .first()
    )


def get_relevant_entitlement_for_subscription(
    db: Session,
    subscription_id: uuid.UUID,
    *,
    now: datetime,
) -> Entitlement | None:
    current = get_current_entitlement(db, subscription_id, now=now)
    if current is not None:
        return current
    future = (
        db.query(Entitlement)
        .filter(
            Entitlement.subscription_id == subscription_id,
            Entitlement.status == EntitlementStatus.ACTIVE.value,
            Entitlement.valid_from > now,
        )
        .order_by(Entitlement.valid_from.asc(), Entitlement.valid_until.asc(), Entitlement.created_at.asc())
        .first()
    )
    return future or get_latest_entitlement_for_subscription(db, subscription_id)


def list_entitlements_for_order(
    db: Session,
    order_id: uuid.UUID,
    *,
    for_update: bool = False,
) -> list[Entitlement]:
    query = (
        db.query(Entitlement)
        .filter(Entitlement.order_id == order_id)
        .order_by(Entitlement.valid_from.asc(), Entitlement.created_at.asc())
    )
    return (query.with_for_update() if for_update else query).all()


def list_active_or_future_entitlements_for_subscription(
    db: Session,
    subscription_id: uuid.UUID,
    *,
    now: datetime,
    for_update: bool = False,
) -> list[Entitlement]:
    query = (
        db.query(Entitlement)
        .filter(
            Entitlement.subscription_id == subscription_id,
            Entitlement.status == EntitlementStatus.ACTIVE.value,
            Entitlement.valid_until > now,
        )
        .order_by(Entitlement.valid_from.asc(), Entitlement.created_at.asc())
    )
    return (query.with_for_update() if for_update else query).all()


def list_due_entitlements_for_subscription(
    db: Session,
    subscription_id: uuid.UUID,
    *,
    now: datetime,
    for_update: bool = False,
) -> list[Entitlement]:
    query = (
        db.query(Entitlement)
        .filter(
            Entitlement.subscription_id == subscription_id,
            Entitlement.status == EntitlementStatus.ACTIVE.value,
            Entitlement.valid_until <= now,
        )
        .order_by(Entitlement.valid_until.asc(), Entitlement.created_at.asc())
    )
    return (query.with_for_update() if for_update else query).all()


def get_active_entitlement_for_scope(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
    scope_type: str,
    product_id: uuid.UUID | None,
    bundle_id: uuid.UUID | None,
    now: datetime,
) -> Entitlement | None:
    return (
        db.query(Entitlement)
        .filter(
            Entitlement.tenant_id == tenant_id,
            Entitlement.region == region,
            Entitlement.user_id == user_id,
            Entitlement.scope_type == scope_type,
            Entitlement.product_id == product_id,
            Entitlement.bundle_id == bundle_id,
            Entitlement.status == EntitlementStatus.ACTIVE.value,
            Entitlement.valid_from <= now,
            Entitlement.valid_until > now,
        )
        .order_by(Entitlement.valid_until.desc(), Entitlement.created_at.desc())
        .first()
    )


def get_trial_for_scope(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
    scope_type: str,
    product_id: uuid.UUID | None,
    bundle_id: uuid.UUID | None,
) -> Subscription | None:
    return (
        db.query(Subscription)
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.region == region,
            Subscription.user_id == user_id,
            Subscription.trial_start_at.is_not(None),
            Subscription.scope_type == scope_type,
            Subscription.product_id == product_id,
            Subscription.bundle_id == bundle_id,
        )
        .with_for_update()
        .first()
    )


def get_live_subscription_for_scope(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
    scope_type: str,
    product_id: uuid.UUID | None,
    bundle_id: uuid.UUID | None,
    for_update: bool = False,
) -> Subscription | None:
    query = (
        db.query(Subscription)
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.region == region,
            Subscription.user_id == user_id,
            Subscription.scope_type == scope_type,
            Subscription.product_id == product_id,
            Subscription.bundle_id == bundle_id,
            Subscription.status.in_(SubscriptionStatus.live_values()),
        )
        .order_by(Subscription.created_at.desc())
    )
    return (query.with_for_update() if for_update else query).first()


def list_active_subscriptions_for_user(
    db: Session, *, tenant_id: str, region: str, user_id: uuid.UUID
) -> list[Subscription]:
    return (
        db.query(Subscription)
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.region == region,
            Subscription.user_id == user_id,
            Subscription.status.in_(SubscriptionStatus.live_values()),
        )
        .with_for_update()
        .all()
    )


def get_subscription_for_order(db: Session, order_id: uuid.UUID, *, for_update: bool = False) -> Subscription | None:
    event_type_rank = case(
        (SubscriptionEvent.event_type == SubscriptionEventType.PAID_PERIOD_ACTIVATED.value, 0),
        else_=1,
    )
    query = (
        db.query(Subscription)
        .join(SubscriptionEvent, SubscriptionEvent.subscription_id == Subscription.id)
        .filter(
            SubscriptionEvent.order_id == order_id,
            SubscriptionEvent.event_type.in_(ORDER_LOOKUP_SUBSCRIPTION_EVENT_TYPES),
        )
        .order_by(
            SubscriptionEvent.occurred_at.desc(),
            event_type_rank.asc(),
            SubscriptionEvent.id.desc(),
            Subscription.created_at.desc(),
            Subscription.id.desc(),
        )
    )
    return (query.with_for_update(of=Subscription) if for_update else query).first()


def list_due_subscriptions(db: Session, *, now: datetime, batch_size: int) -> list[Subscription]:
    return (
        db.query(Subscription)
        .filter(
            Subscription.status.in_(
                (
                    SubscriptionStatus.TRIALING.value,
                    SubscriptionStatus.ACTIVE.value,
                    SubscriptionStatus.PAST_DUE.value,
                    SubscriptionStatus.PAUSED.value,
                    SubscriptionStatus.CANCELED.value,
                )
            ),
            Subscription.current_period_end <= now,
        )
        .order_by(Subscription.current_period_end.asc())
        .with_for_update(skip_locked=True)
        .limit(batch_size)
        .all()
    )
