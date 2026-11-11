"""Queue selection and locks, separate from business decisions and transactions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import BigInteger, DateTime, Text, exists, func, or_, select
from sqlalchemy.orm import Session

from app.infrastructure.queries import paid_access
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingWorkItem,
    BillingWorkKind,
    BillingWorkState,
    ExternalSubscription,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    User,
    AccessInvalidationOutbox,
    PurchasedAllowance,
)


def observation(db: Session, observation_id: UUID) -> BillingStateObservation | None:
    return db.get(BillingStateObservation, observation_id)


def trust_observation(db: Session, subscription_id: UUID, read_started_at: datetime) -> BillingStateObservation | None:
    """Find the complete read which established the stored trust interval.

    Later complete negative reads need not renew that interval in paid access.
    """
    return db.scalar(
        select(BillingStateObservation)
        .where(
            BillingStateObservation.subscription_id == subscription_id,
            BillingStateObservation.evidence_schema_version == "subscription-reconciliation:v1",
            BillingStateObservation.completeness_classification == "complete",
            BillingStateObservation.result_classification == "COMPLETE_MATCH",
            BillingStateObservation.evidence_document["read_started_at"].as_string().cast(DateTime(timezone=True))
            == read_started_at,
        )
        .order_by(BillingStateObservation.evidence_document["provenance"]["fence"].as_string().cast(BigInteger).desc())
        .limit(1)
    )


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
    sweep_key: str,
    urgent_before: datetime,
    urgent_attempt_before: datetime,
    local_scope: tuple[str, str] | None = None,
    recipient_id: str | None = None,
) -> BillingWorkItem | None:
    account_scope = or_(
        (BillingWorkItem.work_kind == "billing_enrollment_sweep") & (BillingWorkItem.coalescing_key == sweep_key),
        BillingWorkItem.coalescing_key == account,
        BillingWorkItem.coalescing_key.startswith(account + ":", autoescape=True),
        (BillingWorkItem.work_kind == "external_create_recovery")
        & exists().where(
            func.cast(ExternalCreateOperation.create_operation_id, Text) == BillingWorkItem.scope_reference,
            ExternalCreateOperation.customer_id == ExternalBillingCustomer.customer_id,
            ExternalBillingCustomer.external_billing_account_id == account,
        ),
    )
    if local_scope is not None:
        tenant, region = local_scope
        account_scope = or_(
            (BillingWorkItem.work_kind == "billing_enrollment_sweep") & (BillingWorkItem.coalescing_key == sweep_key),
            (BillingWorkItem.work_kind == "subscription_trust_expiry")
            & exists().where(
                func.cast(ExternalSubscription.subscription_id, Text) == BillingWorkItem.scope_reference,
                ExternalSubscription.user_id == User.id,
                User.tenant_id == tenant,
                User.region == region,
            ),
            (BillingWorkItem.work_kind == "external_create_deadline")
            & exists().where(
                func.cast(ExternalCreateOperation.create_operation_id, Text) == BillingWorkItem.scope_reference,
                ExternalCreateOperation.customer_id == ExternalBillingCustomer.customer_id,
                ExternalBillingCustomer.user_id == User.id,
                User.tenant_id == tenant,
                User.region == region,
            ),
            (BillingWorkItem.work_kind == BillingWorkKind.ACCESS_INVALIDATION)
            & exists().where(
                func.cast(User.id, Text) == BillingWorkItem.scope_reference,
                User.tenant_id == tenant,
                User.region == region,
            ),
            (BillingWorkItem.work_kind == BillingWorkKind.ALLOWANCE_EXHAUSTION)
            & exists().where(
                func.cast(PurchasedAllowance.allowance_id, Text) == BillingWorkItem.scope_reference,
                PurchasedAllowance.subscription_id == ExternalSubscription.subscription_id,
                ExternalSubscription.user_id == User.id,
                User.tenant_id == tenant,
                User.region == region,
            ),
        )
    due = BillingWorkItem.next_attempt_at <= now
    query = select(BillingWorkItem).where(
        BillingWorkItem.work_kind.in_(kinds),
        BillingWorkItem.work_state.in_(("pending", "running")),
        account_scope,
        or_(BillingWorkItem.lease_expires_at.is_(None), BillingWorkItem.lease_expires_at <= now),
    )
    if recipient_id is not None:
        query = query.where(BillingWorkItem.recipient_id == recipient_id)
    if urgent is not None:
        # A normal job can become urgent while waiting, independently of another
        # source attempt or an enrollment sweep. Only the queue row is locked.
        trust_due = exists().where(
            ExternalSubscription.external_billing_account_id == account,
            func.cast(ExternalSubscription.subscription_id, Text) == BillingWorkItem.scope_reference,
            ExternalSubscription.projection_valid_until <= urgent_before,
        )
        allowance_end = (
            paid_access.latest_paid_allowance_end(ExternalSubscription.subscription_id)
            .correlate(ExternalSubscription)
            .scalar_subquery()
        )
        paid_scope = (
            ExternalSubscription.external_billing_account_id == account,
            func.cast(ExternalSubscription.subscription_id, Text) == BillingWorkItem.scope_reference,
            BillingProductAccessScope.primary_subscription_id == ExternalSubscription.subscription_id,
            allowance_end <= urgent_before,
        )
        paid_due = exists().where(*paid_scope)
        paid_retry_due = exists().where(
            *paid_scope,
            func.coalesce(BillingWorkItem.last_attempt_started_at, ExternalSubscription.last_authoritative_read_at)
            <= urgent_attempt_before,
        )
        reconciliation = BillingWorkItem.work_kind == "subscription_reconciliation"
        # Also promote rows scheduled under the old normal cadence. Retain the
        # attempt-spacing and live-lease guards; only the queue row is locked.
        due = or_(due, reconciliation & paid_retry_due)
        is_urgent = or_(BillingWorkItem.priority > 0, trust_due, reconciliation & paid_due)
        query = query.where(is_urgent if urgent else ~is_urgent)
    return db.scalar(
        query.where(due)
        .order_by(BillingWorkItem.next_attempt_at, BillingWorkItem.work_item_id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )


def missing_subscriptions(
    db: Session, account: str, tenant: str, region: str, limit: int
) -> list[ExternalSubscription]:
    enrolled = exists().where(
        BillingWorkItem.work_kind == "subscription_reconciliation",
        BillingWorkItem.coalescing_key == account + ":" + func.cast(ExternalSubscription.subscription_id, Text),
        BillingWorkItem.work_state.in_(("pending", "running", "invalid")),
    )
    return list(
        db.scalars(
            select(ExternalSubscription)
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


def by_key(db: Session, kind: str, key: str, *, lock: bool = False) -> BillingWorkItem | None:
    query = select(BillingWorkItem).where(BillingWorkItem.work_kind == kind, BillingWorkItem.coalescing_key == key)
    return db.scalar(query.with_for_update().execution_options(populate_existing=True) if lock else query)


def missing_invalidations(db: Session, tenant: str, region: str, limit: int) -> list[tuple[str, UUID]]:
    enrolled = exists().where(
        BillingWorkItem.work_kind == BillingWorkKind.ACCESS_INVALIDATION,
        BillingWorkItem.recipient_id == AccessInvalidationOutbox.recipient_id,
        BillingWorkItem.scope_reference == func.cast(AccessInvalidationOutbox.user_id, Text),
        BillingWorkItem.work_state.in_((BillingWorkState.PENDING, BillingWorkState.RUNNING, BillingWorkState.INVALID)),
    )
    return [
        (recipient_id, user_id)
        for recipient_id, user_id in db.execute(
            select(AccessInvalidationOutbox.recipient_id, AccessInvalidationOutbox.user_id)
            .where(
                AccessInvalidationOutbox.tenant_id == tenant,
                AccessInvalidationOutbox.region == region,
                AccessInvalidationOutbox.pending_revision > AccessInvalidationOutbox.delivered_revision,
                ~enrolled,
            )
            .order_by(AccessInvalidationOutbox.recipient_id, AccessInvalidationOutbox.user_id)
            .limit(limit)
        )
    ]


def backlog(
    db: Session, account: str | None, tenant: str, region: str, *, sweep_key: str
) -> tuple[int, datetime | None, int]:
    source_scope = (
        or_(
            BillingWorkItem.coalescing_key == account,
            BillingWorkItem.coalescing_key.startswith(account + ":", autoescape=True),
            (BillingWorkItem.work_kind == "external_create_recovery")
            & exists().where(
                func.cast(ExternalCreateOperation.create_operation_id, Text) == BillingWorkItem.scope_reference,
                ExternalCreateOperation.customer_id == ExternalBillingCustomer.customer_id,
                ExternalBillingCustomer.external_billing_account_id == account,
            ),
        )
        if account is not None
        else False
    )
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
                    BillingWorkKind.ACCESS_INVALIDATION,
                    BillingWorkKind.ALLOWANCE_EXHAUSTION,
                )
            ),
            or_(
                (BillingWorkItem.work_kind == "billing_enrollment_sweep")
                & (BillingWorkItem.coalescing_key == sweep_key),
                (BillingWorkItem.work_kind == "subscription_trust_expiry")
                & exists().where(
                    func.cast(ExternalSubscription.subscription_id, Text) == BillingWorkItem.scope_reference,
                    ExternalSubscription.user_id == User.id,
                    User.tenant_id == tenant,
                    User.region == region,
                ),
                (BillingWorkItem.work_kind == "external_create_deadline")
                & exists().where(
                    func.cast(ExternalCreateOperation.create_operation_id, Text) == BillingWorkItem.scope_reference,
                    ExternalCreateOperation.customer_id == ExternalBillingCustomer.customer_id,
                    ExternalBillingCustomer.user_id == User.id,
                    User.tenant_id == tenant,
                    User.region == region,
                ),
                source_scope,
                (BillingWorkItem.work_kind == BillingWorkKind.ALLOWANCE_EXHAUSTION)
                & exists().where(
                    func.cast(PurchasedAllowance.allowance_id, Text) == BillingWorkItem.scope_reference,
                    PurchasedAllowance.subscription_id == ExternalSubscription.subscription_id,
                    ExternalSubscription.user_id == User.id,
                    User.tenant_id == tenant,
                    User.region == region,
                ),
                (BillingWorkItem.work_kind == BillingWorkKind.ACCESS_INVALIDATION)
                & exists().where(
                    func.cast(User.id, Text) == BillingWorkItem.scope_reference,
                    User.tenant_id == tenant,
                    User.region == region,
                ),
            ),
        )
        .group_by(BillingWorkItem.work_state)
    ).all()
    pending = sum(count for state, count, _ in rows if state in {"pending", "running"})
    dates = [due for state, _, due in rows if state in {"pending", "running"}]
    return pending, min(dates) if dates else None, sum(count for state, count, _ in rows if state == "invalid")


def missing_deadlines(db: Session, tenant: str, region: str, limit: int) -> list[ExternalSubscription]:
    recorded = exists().where(
        BillingWorkItem.work_kind == "subscription_trust_expiry",
        BillingWorkItem.scope_reference == func.cast(ExternalSubscription.subscription_id, Text),
    )
    return list(
        db.scalars(
            select(ExternalSubscription)
            .join(User, User.id == ExternalSubscription.user_id)
            .join(
                BillingStateObservation,
                BillingStateObservation.observation_id == ExternalSubscription.latest_observation_id,
            )
            .where(
                User.tenant_id == tenant,
                User.region == region,
                BillingStateObservation.evidence_schema_version.in_(
                    ("subscription-reconciliation:v1", "bound-source-negative:v1")
                ),
                BillingStateObservation.access_scope_id.is_not(None),
                ExternalSubscription.projection_valid_until > ExternalSubscription.last_authoritative_read_at,
                ~recorded,
            )
            .order_by(ExternalSubscription.subscription_id)
            .limit(limit)
        )
    )
