"""Short purchase reads and the shared scope -> customer -> operation lock order."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.infrastructure.persistence.purchase_scopes import lock_purchase_scope
from app.models import (
    BillingPurchaseScopeHold,
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationKind,
    ExternalCreateOperationState,
    ExternalSubscription,
    ExternalSubscriptionLifecycleStatus,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState,
    PurchaseScopeHoldState,
    User,
)


def owned_intent(
    db: Session, user_id: UUID, intent_id: UUID, *, tenant_id: str, region: str, account_id: str
) -> PurchaseIntent | None:
    return db.scalar(
        select(PurchaseIntent)
        .join(User, User.id == PurchaseIntent.user_id)
        .where(
            PurchaseIntent.purchase_intent_id == intent_id,
            PurchaseIntent.user_id == user_id,
            PurchaseIntent.external_billing_account_id == account_id,
            User.tenant_id == tenant_id,
            User.region == region,
        )
    )


def locked_owner(db: Session, intent: PurchaseIntent) -> tuple[BillingPurchaseScopeHold, ExternalBillingCustomer]:
    hold = lock_purchase_scope(db, intent.user_id, intent.product_id)
    if (
        hold is None
        or hold.hold_state != PurchaseScopeHoldState.HELD
        or hold.purchase_intent_id != intent.purchase_intent_id
        or hold.external_billing_account_id != intent.external_billing_account_id
    ):
        raise ValueError("purchase no longer owns scope")
    customer = db.scalars(
        select(ExternalBillingCustomer)
        .where(ExternalBillingCustomer.customer_id == intent.customer_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    db.refresh(intent)
    return hold, customer


def operation_for(
    db: Session, intent: PurchaseIntent, kind: ExternalCreateOperationKind
) -> ExternalCreateOperation | None:
    return db.scalar(
        select(ExternalCreateOperation)
        .where(
            ExternalCreateOperation.customer_id == intent.customer_id,
            ExternalCreateOperation.operation_kind == kind,
            ExternalCreateOperation.purchase_intent_id.is_(None)
            if kind == ExternalCreateOperationKind.CUSTOMER
            else ExternalCreateOperation.purchase_intent_id == intent.purchase_intent_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def local_subscription_conflict(db: Session, intent: PurchaseIntent) -> bool:
    linked = db.scalar(
        select(ExternalSubscription.subscription_id)
        .where(
            ExternalSubscription.user_id == intent.user_id,
            ExternalSubscription.product_id == intent.product_id,
            ExternalSubscription.lifecycle_status != ExternalSubscriptionLifecycleStatus.ENDED,
        )
        .limit(1)
    )
    unresolved = db.scalar(
        select(ExternalCreateOperation.create_operation_id)
        .join(PurchaseIntent, PurchaseIntent.purchase_intent_id == ExternalCreateOperation.purchase_intent_id)
        .where(
            PurchaseIntent.user_id == intent.user_id,
            PurchaseIntent.product_id == intent.product_id,
            PurchaseIntent.purchase_intent_id != intent.purchase_intent_id,
            ExternalCreateOperation.resolved_at.is_(None),
        )
        .limit(1)
    )
    return linked is not None or unresolved is not None


def agreement_already_linked(db: Session, account_id: str, agreement_id: str) -> bool:
    return (
        db.scalar(
            select(ExternalSubscription.subscription_id)
            .where(
                ExternalSubscription.external_billing_account_id == account_id,
                ExternalSubscription.external_agreement_id == agreement_id,
            )
            .limit(1)
        )
        is not None
    )


def open_review(db: Session, operation_id: UUID) -> ManualReviewCase | None:
    return db.scalar(
        select(ManualReviewCase).where(
            ManualReviewCase.scope_kind == "external_create_operation",
            ManualReviewCase.scope_reference == str(operation_id),
            ManualReviewCase.case_state == "open",
        )
    )


def product_owner(
    db: Session, user_id: UUID, product_id: str, *, tenant_id: str, region: str, account_id: str
) -> tuple[PurchaseIntent | None, bool]:
    hold = db.scalar(
        select(BillingPurchaseScopeHold).where(
            BillingPurchaseScopeHold.user_id == user_id,
            BillingPurchaseScopeHold.product_id == product_id,
            BillingPurchaseScopeHold.tenant_id == tenant_id,
            BillingPurchaseScopeHold.region == region,
            BillingPurchaseScopeHold.external_billing_account_id == account_id,
            BillingPurchaseScopeHold.hold_state == PurchaseScopeHoldState.HELD,
        )
    )
    if hold is not None:
        intent = (
            owned_intent(
                db, user_id, hold.purchase_intent_id, tenant_id=tenant_id, region=region, account_id=account_id
            )
            if hold.purchase_intent_id
            else None
        )
        return intent, hold.subscription_id is not None
    # Imported/historical links may predate a purchase hold. They still occupy it.
    subscription = db.scalar(
        select(ExternalSubscription.subscription_id)
        .where(
            ExternalSubscription.user_id == user_id,
            ExternalSubscription.product_id == product_id,
            ExternalSubscription.external_billing_account_id == account_id,
            ExternalSubscription.lifecycle_status != ExternalSubscriptionLifecycleStatus.ENDED,
        )
        .limit(1)
    )
    return None, subscription is not None


def other_customer_operations(db: Session, intent: PurchaseIntent) -> bool:
    return (
        db.scalar(
            select(ExternalCreateOperation.create_operation_id)
            .where(
                ExternalCreateOperation.customer_id == intent.customer_id,
                ExternalCreateOperation.purchase_intent_id != intent.purchase_intent_id,
            )
            .limit(1)
        )
        is not None
    )


def lock_original_scope(db: Session, intent: PurchaseIntent) -> None:
    """Keep the common lock order even when an audited release changed owner."""
    lock_purchase_scope(db, intent.user_id, intent.product_id)
    db.execute(
        select(ExternalBillingCustomer)
        .where(ExternalBillingCustomer.customer_id == intent.customer_id)
        .with_for_update()
    )


def lock_operation(db: Session, operation_id: UUID) -> ExternalCreateOperation:
    return db.scalars(
        select(ExternalCreateOperation)
        .where(ExternalCreateOperation.create_operation_id == operation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()


def complete_recovery_item(db: Session, operation_id: UUID) -> None:
    item = db.scalar(
        select(BillingWorkItem)
        .where(
            BillingWorkItem.work_kind == "external_create_recovery",
            BillingWorkItem.coalescing_key == f"external-create:{operation_id}",
        )
        .with_for_update()
    )
    if item is not None:
        item.work_state = "completed"
        item.lease_owner = None
        item.lease_expires_at = None


def local_state(db: Session, intent: PurchaseIntent) -> PurchaseIntentState:
    """Include shared customer ambiguity without depending on source readiness."""
    states = set(
        db.scalars(
            select(ExternalCreateOperation.operation_state).where(
                ExternalCreateOperation.customer_id == intent.customer_id,
                or_(
                    ExternalCreateOperation.purchase_intent_id == intent.purchase_intent_id,
                    ExternalCreateOperation.operation_kind == ExternalCreateOperationKind.CUSTOMER,
                ),
            )
        )
    )
    if intent.state == PurchaseIntentState.MANUAL_REVIEW or ExternalCreateOperationState.MANUAL_REVIEW in states:
        return PurchaseIntentState.MANUAL_REVIEW
    if states & {ExternalCreateOperationState.UNKNOWN, ExternalCreateOperationState.POSSIBLE_SEND}:
        return PurchaseIntentState.AWAITING_EXTERNAL_RESULT
    return intent.state
