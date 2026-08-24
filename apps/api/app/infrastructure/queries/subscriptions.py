from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.domains.billing.enums import EntitlementStatus, SubscriptionStatus
from app.models import Entitlement, Subscription, SubscriptionEvent


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


def list_account_subscriptions(
    db: Session, *, tenant_id: str, region: str, user_id: uuid.UUID
) -> list[Subscription]:
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


def get_active_entitlement(db: Session, subscription_id: uuid.UUID, *, for_update: bool = False) -> Entitlement | None:
    query = (
        db.query(Entitlement)
        .filter(
            Entitlement.subscription_id == subscription_id,
            Entitlement.status == EntitlementStatus.ACTIVE.value,
        )
        .order_by(Entitlement.created_at.desc())
    )
    return (query.with_for_update() if for_update else query).first()


def get_latest_entitlement_for_subscription(db: Session, subscription_id: uuid.UUID) -> Entitlement | None:
    return (
        db.query(Entitlement)
        .filter(Entitlement.subscription_id == subscription_id)
        .order_by(Entitlement.created_at.desc())
        .first()
    )


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


def list_active_subscriptions_for_user(db: Session, *, tenant_id: str, region: str, user_id: uuid.UUID) -> list[Subscription]:
    return (
        db.query(Subscription)
        .filter(
            Subscription.tenant_id == tenant_id,
            Subscription.region == region,
            Subscription.user_id == user_id,
            Subscription.status.in_(
                (
                    SubscriptionStatus.TRIALING.value,
                    SubscriptionStatus.ACTIVE.value,
                    SubscriptionStatus.PAST_DUE.value,
                    SubscriptionStatus.PAUSED.value,
                )
            ),
        )
        .with_for_update()
        .all()
    )


def get_subscription_for_order(db: Session, order_id: uuid.UUID, *, for_update: bool = False) -> Subscription | None:
    query = (
        db.query(Subscription)
        .join(Entitlement, Entitlement.subscription_id == Subscription.id)
        .filter(Entitlement.order_id == order_id)
        .order_by(Subscription.created_at.desc())
    )
    return (query.with_for_update() if for_update else query).first()


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
                )
            ),
            Subscription.current_period_end <= now,
        )
        .order_by(Subscription.current_period_end.asc())
        .with_for_update(skip_locked=True)
        .limit(batch_size)
        .all()
    )
