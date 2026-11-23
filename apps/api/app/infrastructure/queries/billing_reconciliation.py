"""Focused reconciliation row locks and database time; no business decisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, and_, func, or_, select
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


def _primary_selections() -> Select[tuple[UUID | None]]:
    observation = BillingStateObservation
    # Operator selection is recorded inside the authoritative read it applied.
    return select(observation.subscription_id).where(
        or_(
            observation.observation_kind == BillingStateObservationKind.PRIMARY_SELECTION,
            and_(
                observation.observation_kind == BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ,
                observation.evidence_document["primary_selection"]["review_case_id"].as_string().is_not(None),
            ),
        ),
    )


def has_primary_selection(db: Session, subscription_id: UUID) -> bool:
    selected = _primary_selections().where(BillingStateObservation.subscription_id == subscription_id)
    return bool(db.scalar(select(selected.exists())))


def primary_selections(db: Session, subscriptions: set[UUID]) -> set[UUID]:
    selected = _primary_selections().where(BillingStateObservation.subscription_id.in_(subscriptions)).distinct()
    return {subscription_id for subscription_id in db.scalars(selected) if subscription_id is not None}


def _open_subscription_reviews() -> Select[tuple[ManualReviewCase]]:
    return select(ManualReviewCase).where(
        ManualReviewCase.scope_kind == "subscription",
        ManualReviewCase.case_state == "open",
    )


def open_reviews(db: Session, subscription_id: UUID) -> list[ManualReviewCase]:
    return list(
        db.scalars(_open_subscription_reviews().where(ManualReviewCase.scope_reference == str(subscription_id)))
    )


def open_review_references(db: Session, subscriptions: set[UUID]) -> set[str]:
    statement = (
        _open_subscription_reviews()
        .with_only_columns(ManualReviewCase.scope_reference)
        .where(ManualReviewCase.scope_reference.in_(map(str, subscriptions)))
        .distinct()
    )
    return set(db.scalars(statement))


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
