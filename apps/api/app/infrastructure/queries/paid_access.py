"""Paid projection reads and locks; caller owns the user lock and transaction."""

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalSubscription,
    ManualReviewCase,
    PaidAccessState,
    PurchasedAllowance,
    PurchaseIntent,
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


def state(db: Session, user_id: UUID) -> PaidAccessState | None:
    return db.scalar(select(PaidAccessState).where(PaidAccessState.user_id == user_id).with_for_update())


def outbox(db: Session, user_id: UUID) -> AccessInvalidationOutbox | None:
    return db.scalar(
        select(AccessInvalidationOutbox).where(AccessInvalidationOutbox.user_id == user_id).with_for_update()
    )


def observation(db: Session, identity: UUID) -> BillingStateObservation | None:
    return db.get(BillingStateObservation, identity)


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
