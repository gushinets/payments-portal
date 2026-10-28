"""Focused reconciliation row locks and database time; no business decisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import BillingProductAccessScope, ExternalSubscription, ManualReviewCase


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
