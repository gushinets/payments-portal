"""Focused immutable allowance and metric-review reads; caller owns the transaction."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import ManualReviewCase, PurchasedAllowance


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
