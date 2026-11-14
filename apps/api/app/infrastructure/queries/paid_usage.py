"""Owned history and retained activation proof. Reads never create usage state."""

from uuid import UUID

from sqlalchemy import Row, String, and_, cast, or_, select
from sqlalchemy.orm import Session, aliased

from app.models import (
    BillingStateObservation,
    BillingStateObservationKind,
    BillingProductAccessScope,
    ExternalSubscription,
    PurchasedAllowance,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)


def allowances(db: Session, user_id: UUID) -> list[PurchasedAllowance]:
    return list(
        db.scalars(
            select(PurchasedAllowance)
            .join(ExternalSubscription, ExternalSubscription.subscription_id == PurchasedAllowance.subscription_id)
            .where(ExternalSubscription.user_id == user_id)
            .order_by(PurchasedAllowance.created_at.desc(), PurchasedAllowance.allowance_id.desc())
        )
    )


def legacy_activation_candidates(
    db: Session,
    row: PurchasedAllowance,
    *,
    schema: str,
    selection_schema: str,
    identity: str,
    commercial: str,
) -> list[BillingStateObservation]:
    # Issuance before a timestamp start does not activate a bucket, even after
    # that start passes. A material authoritative apply for this exact cycle
    # at/after its conservative start supplies the retained reconciliation proof.
    selection = aliased(BillingStateObservation)
    selected = (
        select(selection.observation_id)
        .where(
            selection.subscription_id == row.subscription_id,
            selection.evidence_schema_version == selection_schema,
            selection.resulting_access_revision.is_not(None),
            selection.observed_at >= row.period_start,
            selection.evidence_document["source_observation_id"].as_string()
            == cast(BillingStateObservation.observation_id, String),
        )
        .exists()
    )
    return list(
        db.scalars(
            select(BillingStateObservation).where(
                BillingStateObservation.subscription_id == row.subscription_id,
                BillingStateObservation.evidence_schema_version == schema,
                or_(
                    and_(
                        BillingStateObservation.resulting_access_revision.is_not(None),
                        BillingStateObservation.created_at >= row.period_start,
                    ),
                    selected,
                ),
                BillingStateObservation.result_classification == commercial,
                BillingStateObservation.evidence_document["identity"].as_string() == identity,
                BillingStateObservation.evidence_document["commercial"].as_string() == commercial,
                BillingStateObservation.evidence_document["financial"].as_string() == Financial.ALLOWED,
                BillingStateObservation.evidence_document["lifecycle"].as_string() == Lifecycle.ACTIVE,
                BillingStateObservation.evidence_document["complete"].as_boolean().is_(True),
            )
        )
    )


def activation(db: Session, allowance_id: UUID) -> BillingStateObservation | None:
    return db.scalar(
        select(BillingStateObservation).where(
            BillingStateObservation.observation_kind == BillingStateObservationKind.ALLOWANCE_ACTIVATION,
            BillingStateObservation.evidence_document["allowance_id"].as_string() == str(allowance_id),
        )
    )


def activation_subject(
    db: Session, user_id: UUID, allowance_id: UUID
) -> Row[tuple[PurchasedAllowance, ExternalSubscription, BillingProductAccessScope]] | None:

    return db.execute(
        select(PurchasedAllowance, ExternalSubscription, BillingProductAccessScope)
        .join(ExternalSubscription, ExternalSubscription.subscription_id == PurchasedAllowance.subscription_id)
        .join(
            BillingProductAccessScope,
            and_(
                BillingProductAccessScope.user_id == ExternalSubscription.user_id,
                BillingProductAccessScope.product_id == ExternalSubscription.product_id,
            ),
        )
        .where(PurchasedAllowance.allowance_id == allowance_id, ExternalSubscription.user_id == user_id)
    ).one_or_none()
