from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    CommercialMappingRevision,
    CommercialProductHead,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalSubscription,
)


def mapping_revision_history(db: Session, *, account_id: str, offer_id: str) -> Iterator[CommercialMappingRevision]:
    """Read retained pins after the publisher has acquired this scope's lock."""
    statement = (
        select(CommercialMappingRevision)
        .where(
            CommercialMappingRevision.external_billing_account_id == account_id,
            CommercialMappingRevision.billing_offer_id == offer_id,
        )
        .order_by(CommercialMappingRevision.revision_number)
        .execution_options(yield_per=100)
    )
    yield from db.scalars(statement)


def find_mapping_revision(
    db: Session, *, account_id: str, offer_id: str, revision: int | None = None
) -> CommercialMappingRevision | None:
    """Select before validating. Never fall back past an invalid latest row."""
    statement = select(CommercialMappingRevision).where(
        CommercialMappingRevision.external_billing_account_id == account_id,
        CommercialMappingRevision.billing_offer_id == offer_id,
    )
    if revision is not None:
        statement = statement.where(CommercialMappingRevision.revision_number == revision)
    return db.scalar(statement.order_by(CommercialMappingRevision.revision_number.desc()).limit(1))


def find_product_head(db: Session, *, account_id: str, product_id: str) -> CommercialProductHead | None:
    return db.get(CommercialProductHead, (account_id, product_id))


def product_head_revision(db: Session, head: CommercialProductHead) -> CommercialMappingRevision | None:
    return db.get(CommercialMappingRevision, head.mapping_revision_id)


def has_foreign_customer_binding(db: Session, *, account_id: str) -> bool:
    customer = (
        db.scalar(
            select(ExternalBillingCustomer.customer_id)
            .where(
                ExternalBillingCustomer.external_billing_account_id != account_id,
                ExternalBillingCustomer.provider_customer_id.is_not(None),
            )
            .limit(1)
        )
        is not None
    )
    subscription = (
        db.scalar(
            select(ExternalSubscription.subscription_id)
            .where(
                ExternalSubscription.external_billing_account_id != account_id,
                ExternalSubscription.external_subscription_id.is_not(None)
                | ExternalSubscription.external_agreement_id.is_not(None),
            )
            .limit(1)
        )
        is not None
    )
    operation = (
        db.scalar(
            select(ExternalCreateOperation.create_operation_id)
            .join(
                ExternalBillingCustomer,
                ExternalCreateOperation.customer_id == ExternalBillingCustomer.customer_id,
            )
            .where(
                ExternalBillingCustomer.external_billing_account_id != account_id,
                ExternalCreateOperation.bound_external_object_id.is_not(None)
                | ExternalCreateOperation.unknown_since.is_not(None),
            )
            .limit(1)
        )
        is not None
    )
    return customer or subscription or operation


def retained_product_mappings(db: Session, *, product_id: str) -> Iterator[CommercialMappingRevision]:
    # Scope is validated by the document reader. JSON expressions work for the
    # existing JSONB column; historical rows are never rewritten or relabelled.
    statement = (
        select(CommercialMappingRevision)
        .where(
            (
                CommercialMappingRevision.mapping_document["material"]["technical"]["product_id"].as_string()
                == product_id
            )
            | (CommercialMappingRevision.mapping_document["selection"]["product_id"].as_string() == product_id)
        )
        .execution_options(yield_per=100)
    )
    yield from db.scalars(statement)


def find_offer_history(db: Session, *, offer_id: str, revision: int | None) -> list[CommercialMappingRevision]:
    statement = select(CommercialMappingRevision).where(CommercialMappingRevision.billing_offer_id == offer_id)
    if revision is not None:
        statement = statement.where(CommercialMappingRevision.revision_number == revision)
    return list(db.scalars(statement.order_by(CommercialMappingRevision.revision_number.desc())))
