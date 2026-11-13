"""Focused reconciliation row locks and database time; no business decisions."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, ScalarResult, Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalSubscription,
    ManualReviewCase,
)

POINT_HISTORY_BATCH_SIZE = 64


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


def subscription_point_history(
    db: Session,
    sub: ExternalSubscription,
    *,
    schemas: tuple[str, ...],
    inventory_schema: str,
    legacy_inventory_schema: str,
    provider_origin: str,
    accepted_fingerprint: str,
) -> ScalarResult[BillingStateObservation]:
    """Stream permanent-source facts by their read-finish upper bound."""
    return db.scalars(
        _point_history_statement(
            sub,
            schemas=schemas,
            inventory_schema=inventory_schema,
            legacy_inventory_schema=legacy_inventory_schema,
            provider_origin=provider_origin,
            accepted_fingerprint=accepted_fingerprint,
        ).execution_options(yield_per=POINT_HISTORY_BATCH_SIZE)
    )


def _point_history_statement(
    sub: ExternalSubscription,
    *,
    schemas: tuple[str, ...],
    inventory_schema: str,
    legacy_inventory_schema: str,
    provider_origin: str,
    accepted_fingerprint: str,
) -> Select[tuple[BillingStateObservation]]:
    provenance = BillingStateObservation.evidence_document["provenance"]
    return (
        select(BillingStateObservation)
        .where(
            or_(
                and_(
                    BillingStateObservation.observation_kind
                    == BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ,
                    BillingStateObservation.evidence_schema_version.in_(schemas),
                ),
                and_(
                    BillingStateObservation.observation_kind == BillingStateObservationKind.TARGET_PRODUCT_DISCOVERY,
                    BillingStateObservation.evidence_schema_version.in_((inventory_schema, legacy_inventory_schema)),
                ),
            ),
            BillingStateObservation.subscription_id == sub.subscription_id,
            BillingStateObservation.external_billing_account_id == sub.external_billing_account_id,
            BillingStateObservation.user_id == sub.user_id,
            BillingStateObservation.product_id == sub.product_id,
            BillingStateObservation.evidence_document["point_relationship"] != JSON.NULL,
            provenance["purchase_intent_id"].as_string() == str(sub.purchase_intent_id),
            provenance["mapping_revision_id"].as_string() == str(sub.mapping_revision_id),
            provenance["provider_subscription_id"].as_string() == sub.external_subscription_id,
            provenance["agreement_id"].as_string() == sub.external_agreement_id,
            provenance["provider_origin"].as_string() == provider_origin,
            provenance["accepted_fingerprint"].as_string() == accepted_fingerprint,
        )
        .order_by(BillingStateObservation.observed_at.desc(), BillingStateObservation.observation_id.desc())
    )
