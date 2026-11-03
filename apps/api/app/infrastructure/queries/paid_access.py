"""Focused paid projection reads and locks. Caller owns user lock/transaction."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, SQLColumnExpression, Select, exists, or_, select, Text, cast
from sqlalchemy.orm import Session

from app.models import (
    ManualReviewCase,
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    ExternalSubscription,
    PaidAccessState,
    PurchasedAllowance,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    PurchaseIntent,
    BillingWorkItem,
    User,
)


def scopes(db: Session, user_id: UUID) -> list[BillingProductAccessScope]:
    return list(
        db.scalars(
            select(BillingProductAccessScope)
            .where(BillingProductAccessScope.user_id == user_id)
            .order_by(BillingProductAccessScope.product_id)
            .with_for_update()
        )
    )


def subscriptions(db: Session, user_id: UUID, product_id: str) -> list[ExternalSubscription]:
    return list(
        db.scalars(
            select(ExternalSubscription)
            .where(ExternalSubscription.user_id == user_id, ExternalSubscription.product_id == product_id)
            .order_by(ExternalSubscription.subscription_id)
            .with_for_update()
        )
    )


def allowances(db: Session, subscription_id: UUID, component: str, metric: str) -> list[PurchasedAllowance]:
    return list(
        db.scalars(
            select(PurchasedAllowance)
            .where(
                PurchasedAllowance.subscription_id == subscription_id,
                PurchasedAllowance.source_component_id == component,
                PurchasedAllowance.metric_key == metric,
            )
            .order_by(PurchasedAllowance.created_at, PurchasedAllowance.allowance_id)
        )
    )


def latest_paid_allowance_end(subscription_id: UUID | SQLColumnExpression[UUID]) -> Select[tuple[datetime | None]]:
    """Keep the latest issued cycle relevant after effective metering expires.

    Match issuance ordering. Calendar-only cycles return no UTC bound, while
    legacy UTC rows without proven calendar meaning never establish urgency.
    """
    return (
        select(PurchasedAllowance.period_end)
        .where(
            PurchasedAllowance.subscription_id == subscription_id,
            PurchasedAllowance.cycle_schema_version.in_(("calendar:v1", "timestamp:v1")),
        )
        .order_by(PurchasedAllowance.created_at.desc(), PurchasedAllowance.allowance_id.desc())
        .limit(1)
    )


def state(db: Session, user_id: UUID) -> PaidAccessState | None:
    return db.scalar(select(PaidAccessState).where(PaidAccessState.user_id == user_id).with_for_update())


def outbox(db: Session, user_id: UUID) -> AccessInvalidationOutbox | None:
    return db.scalar(
        select(AccessInvalidationOutbox).where(AccessInvalidationOutbox.user_id == user_id).with_for_update()
    )


def discovery(db: Session, identity: UUID) -> BillingStateObservation | None:
    return db.get(BillingStateObservation, identity)


def metric_review(db: Session, reference: str, kind: str = "subscription_metric") -> ManualReviewCase | None:
    return db.scalar(
        select(ManualReviewCase).where(
            ManualReviewCase.scope_kind == kind,
            ManualReviewCase.scope_reference == reference,
            ManualReviewCase.case_state == "open",
        )
    )


def metric_cycle_allowances(
    db: Session, subscription_id: UUID, metric: str, cycle_key: str
) -> list[PurchasedAllowance]:
    return list(
        db.scalars(
            select(PurchasedAllowance).where(
                PurchasedAllowance.subscription_id == subscription_id,
                PurchasedAllowance.metric_key == metric,
                PurchasedAllowance.provider_cycle_key == cycle_key,
            )
        )
    )


def scope_id(db: Session, user_id: UUID, product_id: str) -> UUID | None:
    return db.scalar(
        select(BillingProductAccessScope.access_scope_id).where(
            BillingProductAccessScope.user_id == user_id, BillingProductAccessScope.product_id == product_id
        )
    )


def dependencies(
    db: Session, sub: ExternalSubscription
) -> tuple[ExternalBillingCustomer | None, PurchaseIntent | None, list[ExternalCreateOperation]]:
    customer = db.get(ExternalBillingCustomer, sub.customer_id)
    purchase = db.get(PurchaseIntent, sub.purchase_intent_id) if sub.purchase_intent_id else None
    operations = list(
        db.scalars(
            select(ExternalCreateOperation)
            .where(
                ExternalCreateOperation.customer_id == sub.customer_id,
                or_(
                    ExternalCreateOperation.purchase_intent_id == sub.purchase_intent_id,
                    ExternalCreateOperation.purchase_intent_id.is_(None),
                ),
            )
            .order_by(ExternalCreateOperation.create_operation_id)
        )
    )
    return customer, purchase, operations


def missing_deadline_users(
    db: Session, tenant: str, region: str, limit: int, *, allow_simulated_metering: bool = True
) -> list[UUID]:
    """Persisted scope/identity, independent of today's source account setting."""
    scheduled = exists().where(
        BillingWorkItem.work_kind == "subscription_trust_expiry",
        BillingWorkItem.scope_reference == cast(BillingProductAccessScope.primary_subscription_id, Text),
        BillingWorkItem.work_state.in_(("pending", "running")),
        BillingWorkItem.next_attempt_at <= BillingProductAccessScope.effective_access_until,
    )
    needs_repair = ~scheduled
    if not allow_simulated_metering:
        simulated = exists().where(
            ExternalSubscription.subscription_id == BillingProductAccessScope.primary_subscription_id,
            ExternalSubscription.purchase_intent_id == PurchaseIntent.purchase_intent_id,
            PurchaseIntent.accepted_snapshot["technical_terms"]["provenance"].as_string() == "SIMULATED",
        )
        needs_repair = or_(
            needs_repair, simulated & (BillingProductAccessScope.effective_access_document["allowances"] != [])
        )
    return list(
        db.scalars(
            select(BillingProductAccessScope.user_id)
            .join(User, User.id == BillingProductAccessScope.user_id)
            .where(
                User.tenant_id == tenant,
                User.region == region,
                BillingProductAccessScope.effective_access_document.is_not(None),
                BillingProductAccessScope.effective_access_document != JSON.NULL,
                needs_repair,
            )
            .distinct()
            .order_by(BillingProductAccessScope.user_id)
            .limit(limit)
        )
    )
