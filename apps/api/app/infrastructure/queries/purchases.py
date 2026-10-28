"""Bounded purchase reads and local concurrency boundaries; no transaction owner."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, and_, cast, func, select, text
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.infrastructure.queries.legal import list_active_required_documents
from app.models import (
    BillingPurchaseScopeHold,
    BillingWorkItem,
    CommercialProductHead,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    DocumentVersion,
    DocumentAcceptance,
    PurchaseIntent,
)


MAX_HELD_PURCHASES = 100


def account_purchases(db: Session, user_id: UUID, *, after: UUID | None, limit: int) -> list[PurchaseIntent]:
    query = (
        select(PurchaseIntent)
        .join(
            BillingPurchaseScopeHold, BillingPurchaseScopeHold.purchase_intent_id == PurchaseIntent.purchase_intent_id
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


def subscription_purchase(
    db: Session, *, user_id: UUID, customer_id: UUID, account_id: str, provider_id: str, agreement_id: str
) -> PurchaseIntent | None:
    return db.scalar(
        select(PurchaseIntent)
        .join(ExternalSubscription, ExternalSubscription.purchase_intent_id == PurchaseIntent.purchase_intent_id)
        .where(
            ExternalSubscription.user_id == user_id,
            ExternalSubscription.customer_id == customer_id,
            ExternalSubscription.external_billing_account_id == account_id,
            ExternalSubscription.external_subscription_id == provider_id,
            ExternalSubscription.external_agreement_id == agreement_id,
        )
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


def other_held_purchases(db: Session, user_id: UUID, purchase_id: UUID) -> list[PurchaseIntent]:
    return list(
        db.scalars(
            select(PurchaseIntent)
            .join(
                BillingPurchaseScopeHold,
                BillingPurchaseScopeHold.purchase_intent_id == PurchaseIntent.purchase_intent_id,
            )
            .where(PurchaseIntent.user_id == user_id, PurchaseIntent.purchase_intent_id != purchase_id)
            .limit(MAX_HELD_PURCHASES)
        )
    )


def financial_recovery_deadline(operation: ExternalCreateOperation, work: BillingWorkItem | None) -> datetime | None:
    """Pre-migration work keeps the original window; retry scheduling is unrelated."""
    if work is not None and work.active_recovery_deadline_at is not None:
        return work.active_recovery_deadline_at
    return operation.unknown_recovery_deadline_at


def overdue_financial(db: Session, now: datetime, limit: int) -> tuple[tuple[UUID, UUID], ...]:
    deadline = func.coalesce(
        BillingWorkItem.active_recovery_deadline_at, ExternalCreateOperation.unknown_recovery_deadline_at
    )
    return tuple(
        db.execute(
            select(PurchaseIntent.user_id, PurchaseIntent.purchase_intent_id)
            .join(
                ExternalCreateOperation, ExternalCreateOperation.purchase_intent_id == PurchaseIntent.purchase_intent_id
            )
            .outerjoin(
                BillingWorkItem,
                and_(
                    BillingWorkItem.work_kind == "external_create_recovery",
                    BillingWorkItem.coalescing_key == cast(ExternalCreateOperation.create_operation_id, Text),
                ),
            )
            .where(
                ExternalCreateOperation.operation_kind.in_([Kind.AGREEMENT, Kind.SUBSCRIPTION]),
                ExternalCreateOperation.operation_state.in_([State.UNKNOWN, State.POSSIBLE_SEND]),
                deadline <= now,
            )
            .order_by(deadline)
            .limit(limit)
        ).tuples()
    )
