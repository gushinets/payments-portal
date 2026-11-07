"""Bounded purchase reads and local concurrency boundaries; no transaction owner."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.infrastructure.queries.legal import list_active_required_documents
from app.models import (
    BillingStateObservation,
    BillingPurchaseScopeHold,
    BillingWorkItem,
    CommercialProductHead,
    ExternalCreateOperation,
    ExternalSubscription,
    DocumentVersion,
    DocumentAcceptance,
    PurchaseIntent,
)


def account_purchases(db: Session, user_id: UUID, *, after: UUID | None, limit: int) -> list[PurchaseIntent]:
    query = (
        select(PurchaseIntent)
        .join(
            BillingPurchaseScopeHold,
            BillingPurchaseScopeHold.purchase_intent_id == PurchaseIntent.purchase_intent_id,
        )
        .where(PurchaseIntent.user_id == user_id)
        .order_by(PurchaseIntent.purchase_intent_id)
        .limit(limit)
    )
    if after is not None:
        query = query.where(PurchaseIntent.purchase_intent_id > after)
    return list(db.scalars(query))


def by_key(db: Session, user_id: UUID, key: str) -> list[PurchaseIntent]:
    return list(
        db.scalars(
            select(PurchaseIntent)
            .where(PurchaseIntent.user_id == user_id, PurchaseIntent.client_idempotency_key == key)
            .limit(2)
        )
    )


def hold(db: Session, user_id: UUID, product_id: str) -> BillingPurchaseScopeHold | None:
    return db.get(BillingPurchaseScopeHold, (user_id, product_id))


def owned(db: Session, user_id: UUID, purchase_id: UUID, *, lock: bool = False) -> PurchaseIntent | None:
    query = select(PurchaseIntent).where(
        PurchaseIntent.user_id == user_id, PurchaseIntent.purchase_intent_id == purchase_id
    )
    return db.scalar(query.with_for_update() if lock else query)


def operations(db: Session, purchase_id: UUID, *, lock: bool = False) -> list[ExternalCreateOperation]:
    query = (
        select(ExternalCreateOperation)
        .where(ExternalCreateOperation.purchase_intent_id == purchase_id)
        .order_by(ExternalCreateOperation.operation_kind)
    )
    return list(db.scalars(query.with_for_update() if lock else query))


def current_head(db: Session, account_id: str, product_id: str) -> CommercialProductHead | None:
    return db.scalar(
        select(CommercialProductHead)
        .where(
            CommercialProductHead.external_billing_account_id == account_id,
            CommercialProductHead.product_id == product_id,
        )
        .with_for_update()
    )


def required_documents(
    db: Session, tenant_id: str, region: str, *, pin: bool = False, effective_at: datetime | None = None
) -> list[DocumentVersion]:
    if pin and db.get_bind().dialect.name == "postgresql":
        # Also excludes a new active version phantom until the acceptance commits.
        db.execute(text("LOCK TABLE document_versions IN SHARE MODE"))
    return list_active_required_documents(
        db, tenant_id=tenant_id, region=region, effective_at=effective_at or utc_now()
    )


def linked_subscription(db: Session, purchase_id: UUID) -> ExternalSubscription | None:
    return db.scalar(
        select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchase_id).with_for_update()
    )


def original_consent(
    db: Session, row: PurchaseIntent, *, limit: int
) -> list[tuple[DocumentAcceptance, DocumentVersion]]:
    return list(
        db.execute(
            select(DocumentAcceptance, DocumentVersion)
            .join(DocumentVersion, DocumentVersion.id == DocumentAcceptance.document_version_id)
            .where(
                DocumentAcceptance.legal_acceptance_event_id == row.legal_acceptance_event_id,
                DocumentAcceptance.user_id == row.user_id,
            )
            .limit(limit)
        ).tuples()
    )


def financial_recovery_deadline(operation: ExternalCreateOperation, work: BillingWorkItem | None) -> datetime | None:
    """Pre-migration work keeps the original window; retry scheduling is unrelated."""
    if work is not None and work.active_recovery_deadline_at is not None:
        return work.active_recovery_deadline_at
    return operation.unknown_recovery_deadline_at


def closed_original_agreement(db: Session, purchase_id: UUID, agreement_id: str) -> bool:
    return (
        db.scalar(
            select(BillingStateObservation.observation_id)
            .where(
                BillingStateObservation.purchase_intent_id == purchase_id,
                BillingStateObservation.evidence_schema_version == "prepared-agreement:v1",
                BillingStateObservation.result_classification == "source_negative",
                BillingStateObservation.evidence_document["agreement_id"].as_string() == agreement_id,
            )
            .limit(1)
        )
        is not None
    )
