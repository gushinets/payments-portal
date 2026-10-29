"""Bounded local evidence reads and review locks for privileged operations."""

from uuid import UUID

from sqlalchemy import Text, and_, cast, or_, select
from sqlalchemy.orm import Session

from app.models import (
    BillingStateObservation,
    BillingWorkItem,
    ExternalCreateOperation,
    ExternalSubscription,
    ManualReviewCase,
)


def review(db: Session, case_id: UUID, *, lock: bool = False) -> ManualReviewCase | None:
    query = select(ManualReviewCase).where(ManualReviewCase.review_case_id == case_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def reviews(
    db: Session, purchase_id: UUID, customer_id: UUID, subscription_id: UUID | None, *, open_only: bool = False
) -> list[ManualReviewCase]:
    operations = select(ExternalCreateOperation.create_operation_id).where(
        (ExternalCreateOperation.purchase_intent_id == purchase_id)
        | (
            (ExternalCreateOperation.customer_id == customer_id)
            & (ExternalCreateOperation.purchase_intent_id.is_(None))
        )
    )
    query = select(ManualReviewCase).where(
        or_(
            and_(
                ManualReviewCase.scope_kind == "create_operation",
                ManualReviewCase.scope_reference.in_(select(cast(operations.subquery().c.create_operation_id, Text))),
            ),
            and_(
                ManualReviewCase.scope_kind == "subscription", ManualReviewCase.scope_reference == str(subscription_id)
            ),
            and_(
                ManualReviewCase.scope_kind == "purchase_intent", ManualReviewCase.scope_reference == str(purchase_id)
            ),
        )
    )
    if open_only:
        query = query.where(ManualReviewCase.case_state == "open")
    return list(
        db.scalars(query.order_by(ManualReviewCase.created_at.desc(), ManualReviewCase.review_case_id).limit(101))
    )


def subscription(db: Session, purchase_id: UUID) -> ExternalSubscription | None:
    return db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchase_id))


def observations(db: Session, subscription_id: UUID) -> list[BillingStateObservation]:
    return list(
        db.scalars(
            select(BillingStateObservation)
            .where(BillingStateObservation.subscription_id == subscription_id)
            .order_by(BillingStateObservation.created_at.desc(), BillingStateObservation.observation_id)
            .limit(20)
        )
    )


def work(db: Session, references: tuple[str, ...]) -> list[BillingWorkItem]:
    return list(
        db.scalars(
            select(BillingWorkItem)
            .where(BillingWorkItem.scope_reference.in_(references))
            .order_by(BillingWorkItem.work_item_id)
            .limit(101)
        )
    )
