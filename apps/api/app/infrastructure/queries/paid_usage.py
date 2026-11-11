"""Owned history and retained activation proof. Reads never create usage state."""

from uuid import UUID

from sqlalchemy import String, and_, cast, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    BillingStateObservation, ExternalSubscription, PurchasedAllowance,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)


def allowances(db: Session, user_id: UUID) -> list[PurchasedAllowance]:
    return list(db.scalars(
        select(PurchasedAllowance)
        .join(ExternalSubscription, ExternalSubscription.subscription_id == PurchasedAllowance.subscription_id)
        .where(ExternalSubscription.user_id == user_id)
        .order_by(PurchasedAllowance.created_at.desc(), PurchasedAllowance.allowance_id.desc())
    ))


def activated(
    db: Session, row: PurchasedAllowance, *, schema: str, selection_schema: str, identity: str, commercial: str,
) -> bool:
    # Issuance before a timestamp start does not activate a bucket, even after
    # that start passes. A material authoritative apply for this exact cycle
    # at/after its conservative start supplies the retained reconciliation proof.
    selection = aliased(BillingStateObservation)
    selected = select(selection.observation_id).where(
        selection.subscription_id == row.subscription_id,
        selection.evidence_schema_version == selection_schema,
        selection.resulting_access_revision.is_not(None),
        selection.observed_at >= row.period_start,
        selection.evidence_document["source_observation_id"].as_string() == cast(BillingStateObservation.observation_id, String),
    ).exists()
    return db.scalar(select(BillingStateObservation.observation_id).where(
        BillingStateObservation.subscription_id == row.subscription_id,
        BillingStateObservation.evidence_schema_version == schema,
        or_(and_(
            BillingStateObservation.resulting_access_revision.is_not(None),
            BillingStateObservation.created_at >= row.period_start,
        ), selected),
        BillingStateObservation.result_classification == commercial,
        BillingStateObservation.evidence_document["cycle"] == row.calendar_document,
        BillingStateObservation.evidence_document["identity"].as_string() == identity,
        BillingStateObservation.evidence_document["commercial"].as_string() == commercial,
        BillingStateObservation.evidence_document["financial"].as_string() == Financial.ALLOWED,
        BillingStateObservation.evidence_document["lifecycle"].as_string() == Lifecycle.ACTIVE,
        BillingStateObservation.evidence_document["complete"].as_boolean().is_(True),
    ).limit(1)) is not None
