"""Focused reconciliation row locks and database time; no business decisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalSubscription,
    ManualReviewCase,
)


def database_now(db: Session) -> datetime:
    clock = func.clock_timestamp() if db.get_bind().dialect.name == "postgresql" else func.current_timestamp()
    return db.scalar(select(clock))


def subscription(db: Session, subscription_id: UUID, *, lock: bool = False) -> ExternalSubscription | None:
    statement = select(ExternalSubscription).where(ExternalSubscription.subscription_id == subscription_id)
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    return db.scalar(statement)


def scope(db: Session, user_id: UUID, product_id: str) -> BillingProductAccessScope | None:
    return db.scalar(
        select(BillingProductAccessScope)
        .where(BillingProductAccessScope.user_id == user_id, BillingProductAccessScope.product_id == product_id)
        .with_for_update()
    )


def has_primary_selection(db: Session, subscription_id: UUID) -> bool:
    observation = BillingStateObservation
    # Operator selection is recorded inside the authoritative read it applied.
    selected = select(observation.observation_id).where(
        observation.subscription_id == subscription_id,
        or_(
            observation.observation_kind == BillingStateObservationKind.PRIMARY_SELECTION,
            and_(
                observation.observation_kind == BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ,
                observation.evidence_document["primary_selection"]["review_case_id"].as_string().is_not(None),
            ),
        ),
    )
    return bool(db.scalar(select(selected.exists())))


def open_reviews(db: Session, subscription_id: UUID) -> list[ManualReviewCase]:
    return list(
        db.scalars(
            select(ManualReviewCase).where(
                ManualReviewCase.scope_kind == "subscription",
                ManualReviewCase.scope_reference == str(subscription_id),
                ManualReviewCase.case_state == "open",
            )
        )
    )


def customer_subscriptions(db: Session, customer_id: UUID) -> list[ExternalSubscription]:
    return list(
        db.scalars(
            select(ExternalSubscription)
            .where(ExternalSubscription.customer_id == customer_id)
            .order_by(ExternalSubscription.subscription_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )
