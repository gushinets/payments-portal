"""Queue selection and locks, separate from business decisions and transactions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, exists, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    BillingStateObservation,
    BillingWorkItem,
    ExternalSubscription,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationKind,
    PurchaseIntent,
    User,
)


def observation(db: Session, observation_id: UUID) -> BillingStateObservation | None:
    return db.get(BillingStateObservation, observation_id)


def item(db: Session, identity: UUID) -> BillingWorkItem | None:
    return db.scalar(
        select(BillingWorkItem)
        .where(BillingWorkItem.work_item_id == identity)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def claimable(
    db: Session,
    kinds: tuple[str, ...],
    now: datetime,
    *,
    urgent: bool | None,
    account: str,
    trust_urgent_before: datetime,
) -> BillingWorkItem | None:
    query = select(BillingWorkItem).where(
        BillingWorkItem.work_kind.in_(kinds),
        BillingWorkItem.work_state.in_(("pending", "running")),
        BillingWorkItem.next_attempt_at <= now,
        or_(
            BillingWorkItem.coalescing_key == account,
            BillingWorkItem.coalescing_key.startswith(account + ":", autoescape=True),
            (BillingWorkItem.work_kind == "external_create_recovery")
            & exists().where(
                func.cast(ExternalCreateOperation.create_operation_id, Text) == BillingWorkItem.scope_reference,
                ExternalCreateOperation.customer_id == ExternalBillingCustomer.customer_id,
                ExternalBillingCustomer.external_billing_account_id == account,
            ),
        ),
        or_(BillingWorkItem.lease_expires_at.is_(None), BillingWorkItem.lease_expires_at <= now),
    )
    if urgent is not None:
        # A normal job can become urgent while waiting, independently of another
        # source attempt or an enrollment sweep. Only the queue row is locked.
        trust_due = exists().where(
            ExternalSubscription.external_billing_account_id == account,
            func.cast(ExternalSubscription.subscription_id, Text) == BillingWorkItem.scope_reference,
            ExternalSubscription.projection_valid_until <= trust_urgent_before,
        )
        is_urgent = or_(BillingWorkItem.priority > 0, trust_due)
        query = query.where(is_urgent if urgent else ~is_urgent)
    return db.scalar(
        query.order_by(BillingWorkItem.next_attempt_at, BillingWorkItem.work_item_id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def missing_subscriptions(db: Session, account: str, tenant: str, region: str, limit: int) -> list[UUID]:
    enrolled = exists().where(
        BillingWorkItem.work_kind == "subscription_reconciliation",
        BillingWorkItem.coalescing_key == account + ":" + func.cast(ExternalSubscription.subscription_id, Text),
        BillingWorkItem.work_state.in_(("pending", "running", "invalid")),
    )
    return list(
        db.scalars(
            select(ExternalSubscription.subscription_id)
            .join(User, User.id == ExternalSubscription.user_id)
            .where(
                ExternalSubscription.external_billing_account_id == account,
                User.tenant_id == tenant,
                User.region == region,
                ExternalSubscription.purchase_intent_id.is_not(None),
                ExternalSubscription.external_subscription_id.is_not(None),
                ExternalSubscription.external_agreement_id.is_not(None),
                ~enrolled,
            )
            .order_by(ExternalSubscription.subscription_id)
            .limit(limit)
        )
    )


def enrollment_subject(
    db: Session, identity: UUID
) -> tuple[ExternalSubscription, PurchaseIntent, ExternalBillingCustomer, ExternalCreateOperation | None] | None:
    return db.execute(
        select(ExternalSubscription, PurchaseIntent, ExternalBillingCustomer, ExternalCreateOperation)
        .join(PurchaseIntent, PurchaseIntent.purchase_intent_id == ExternalSubscription.purchase_intent_id)
        .join(ExternalBillingCustomer, ExternalBillingCustomer.customer_id == ExternalSubscription.customer_id)
        .outerjoin(
            ExternalCreateOperation,
            (ExternalCreateOperation.customer_id == ExternalBillingCustomer.customer_id)
            & (ExternalCreateOperation.operation_kind == ExternalCreateOperationKind.CUSTOMER),
        )
        .where(ExternalSubscription.subscription_id == identity)
    ).first()


def by_key(db: Session, kind: str, key: str) -> BillingWorkItem | None:
    return db.scalar(
        select(BillingWorkItem).where(BillingWorkItem.work_kind == kind, BillingWorkItem.coalescing_key == key)
    )


def backlog(db: Session, account: str) -> tuple[int, datetime | None, int]:
    rows = db.execute(
        select(BillingWorkItem.work_state, func.count(), func.min(BillingWorkItem.next_attempt_at))
        .where(
            BillingWorkItem.work_kind.in_(
                (
                    "subscription_reconciliation",
                    "subscription_trust_expiry",
                    "billing_enrollment_sweep",
                    "external_create_recovery",
                    "external_create_deadline",
                    "customer_inventory",
                )
            ),
            or_(
                BillingWorkItem.coalescing_key == account,
                BillingWorkItem.coalescing_key.startswith(account + ":", autoescape=True),
                (BillingWorkItem.work_kind == "external_create_recovery")
                & exists().where(
                    func.cast(ExternalCreateOperation.create_operation_id, Text) == BillingWorkItem.scope_reference,
                    ExternalCreateOperation.customer_id == ExternalBillingCustomer.customer_id,
                    ExternalBillingCustomer.external_billing_account_id == account,
                ),
            ),
        )
        .group_by(BillingWorkItem.work_state)
    ).all()
    pending = sum(count for state, count, _ in rows if state in {"pending", "running"})
    dates = [due for state, _, due in rows if state in {"pending", "running"}]
    return pending, min(dates) if dates else None, sum(count for state, count, _ in rows if state == "invalid")


def missing_deadlines(db: Session, account: str, limit: int) -> list[ExternalSubscription]:
    recorded = exists().where(
        BillingWorkItem.work_kind == "subscription_trust_expiry",
        BillingWorkItem.coalescing_key == account + ":" + func.cast(ExternalSubscription.subscription_id, Text),
    )
    return list(
        db.scalars(
            select(ExternalSubscription)
            .join(
                BillingStateObservation,
                BillingStateObservation.observation_id == ExternalSubscription.latest_observation_id,
            )
            .where(
                ExternalSubscription.external_billing_account_id == account,
                BillingStateObservation.evidence_schema_version == "subscription-reconciliation:v1",
                BillingStateObservation.access_scope_id.is_not(None),
                ExternalSubscription.projection_valid_until > ExternalSubscription.last_authoritative_read_at,
                ~recorded,
            )
            .order_by(ExternalSubscription.subscription_id)
            .limit(limit)
        )
    )
