"""Focused reads for a single owned Widget scope; no external I/O or writes."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models import (
    BillingPurchaseScopeHold,
    DocumentAcceptance,
    ExternalCreateOperation,
    ExternalCreateOperationKind,
    ExternalCreateOperationState,
    ExternalSubscription,
    ExternalSubscriptionLifecycleStatus,
    PurchaseScopeHoldState,
)


def held_subscription(
    db: Session, user_id: UUID, product_id: str, account_id: str, *, tenant_id: str, region: str
) -> ExternalSubscription | None:
    """Select only the current hold's confirmed link, locking the scope first."""
    return db.scalar(
        select(ExternalSubscription)
        .join(
            BillingPurchaseScopeHold, BillingPurchaseScopeHold.subscription_id == ExternalSubscription.subscription_id
        )
        .where(
            BillingPurchaseScopeHold.user_id == user_id,
            BillingPurchaseScopeHold.product_id == product_id,
            BillingPurchaseScopeHold.external_billing_account_id == account_id,
            BillingPurchaseScopeHold.tenant_id == tenant_id,
            BillingPurchaseScopeHold.region == region,
            BillingPurchaseScopeHold.hold_state == PurchaseScopeHoldState.HELD,
            BillingPurchaseScopeHold.purchase_intent_id == ExternalSubscription.purchase_intent_id,
            ExternalSubscription.user_id == user_id,
            ExternalSubscription.product_id == product_id,
            ExternalSubscription.external_billing_account_id == account_id,
        )
        .with_for_update(of=BillingPurchaseScopeHold)
    )


def conflicting_subscription(db: Session, link: ExternalSubscription) -> bool:
    """Ended history is harmless; another nonterminal link is still ambiguous."""
    return (
        db.scalar(
            select(ExternalSubscription.subscription_id)
            .where(
                ExternalSubscription.subscription_id != link.subscription_id,
                ExternalSubscription.user_id == link.user_id,
                ExternalSubscription.product_id == link.product_id,
                ExternalSubscription.lifecycle_status != ExternalSubscriptionLifecycleStatus.ENDED,
            )
            .limit(1)
        )
        is not None
    )


def create_operations(db: Session, customer_id: UUID, intent_id: UUID) -> list[ExternalCreateOperation]:
    return list(
        db.scalars(
            select(ExternalCreateOperation).where(
                ExternalCreateOperation.customer_id == customer_id,
                or_(
                    ExternalCreateOperation.purchase_intent_id == intent_id,
                    ExternalCreateOperation.purchase_intent_id.is_(None),
                ),
            )
        )
    )


def document_acceptances(db: Session, event_id: UUID) -> list[DocumentAcceptance]:
    return list(
        db.scalars(
            select(DocumentAcceptance).where(
                DocumentAcceptance.legal_acceptance_event_id == event_id,
            )
        )
    )


def uncertain_customer_create(db: Session, customer_id: UUID) -> bool:
    return (
        db.scalar(
            select(ExternalCreateOperation.create_operation_id)
            .where(
                ExternalCreateOperation.customer_id == customer_id,
                ExternalCreateOperation.operation_kind == ExternalCreateOperationKind.CUSTOMER,
                ExternalCreateOperation.operation_state != ExternalCreateOperationState.BOUND,
            )
            .limit(1)
        )
        is not None
    )
