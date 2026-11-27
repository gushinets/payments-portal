"""Local cabinet reads. The shared user lock stabilizes all projection tuples."""

from uuid import UUID

from sqlalchemy import or_, select, union
from sqlalchemy.orm import Session

from app.models import (
    BillingProductAccessScope,
    BillingPurchaseScopeHold,
    BillingStateObservation,
    BillingWorkItem,
    BillingWorkKind,
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState,
    ExternalSubscription,
    PaidAccessState,
    PurchaseIntent,
    PurchasedAllowance,
    User,
)

MAX_EVIDENCE_PRODUCTS = 100


def lock_reader(db: Session, user_id: UUID, tenant: str, region: str) -> bool:
    # Writers acquire this row FOR UPDATE before business/state/queue locks.
    # Multiple readers can coexist; none can mix pre/post-commit metadata.
    return (
        db.scalar(
            select(User.id)
            .where(User.id == user_id, User.tenant_id == tenant, User.region == region)
            .with_for_update(read=True)
        )
        is not None
    )


def state(db: Session, user_id: UUID, tenant: str, region: str) -> PaidAccessState | None:
    return db.scalar(
        select(PaidAccessState).where(
            PaidAccessState.user_id == user_id, PaidAccessState.tenant_id == tenant, PaidAccessState.region == region
        )
    )


def scopes(db: Session, user_id: UUID) -> list[BillingProductAccessScope]:
    return list(db.scalars(select(BillingProductAccessScope).where(BillingProductAccessScope.user_id == user_id)))


def product_ids(db: Session, user_id: UUID) -> list[str]:
    products = union(
        select(BillingProductAccessScope.product_id).where(BillingProductAccessScope.user_id == user_id),
        select(BillingPurchaseScopeHold.product_id).where(BillingPurchaseScopeHold.user_id == user_id),
    ).subquery()
    return list(
        db.scalars(select(products.c.product_id).order_by(products.c.product_id).limit(MAX_EVIDENCE_PRODUCTS + 1))
    )


def sources(
    db: Session, user_id: UUID, products: list[str]
) -> list[
    tuple[
        PurchaseIntent, ExternalSubscription | None, BillingStateObservation | None, ExternalBillingCustomerBindingState
    ]
]:
    return list(
        db.execute(
            select(PurchaseIntent, ExternalSubscription, BillingStateObservation, ExternalBillingCustomer.binding_state)
            .join(
                BillingPurchaseScopeHold,
                BillingPurchaseScopeHold.purchase_intent_id == PurchaseIntent.purchase_intent_id,
            )
            .join(ExternalBillingCustomer, ExternalBillingCustomer.customer_id == PurchaseIntent.customer_id)
            .outerjoin(
                ExternalSubscription, ExternalSubscription.purchase_intent_id == PurchaseIntent.purchase_intent_id
            )
            .outerjoin(
                BillingStateObservation,
                BillingStateObservation.observation_id == ExternalSubscription.latest_observation_id,
            )
            .where(PurchaseIntent.user_id == user_id, PurchaseIntent.product_id.in_(products))
        ).tuples()
    )


def activation_jobs(
    db: Session, subscription_keys: set[str], customer_keys: set[str]
) -> dict[tuple[str, str], BillingWorkItem]:
    return {
        (row.work_kind, row.coalescing_key): row
        for row in db.scalars(
            select(BillingWorkItem).where(
                or_(
                    BillingWorkItem.work_kind.in_(
                        (BillingWorkKind.WIDGET_ACTIVATION_CHECK, BillingWorkKind.SUBSCRIPTION_RECONCILIATION)
                    )
                    & BillingWorkItem.coalescing_key.in_(subscription_keys),
                    (BillingWorkItem.work_kind == BillingWorkKind.CUSTOMER_INVENTORY)
                    & BillingWorkItem.coalescing_key.in_(customer_keys),
                )
            )
        )
        if row.coalescing_key is not None
    }


def allowances(db: Session, identities: list[UUID]) -> list[PurchasedAllowance]:
    return list(db.scalars(select(PurchasedAllowance).where(PurchasedAllowance.allowance_id.in_(identities))))


def grant_purchases(db: Session, user_id: UUID, products: list[str]) -> dict[str, PurchaseIntent]:
    """Resolve committed grant provenance under the caller's shared user lock."""
    return dict(
        db.execute(
            select(BillingProductAccessScope.product_id, PurchaseIntent)
            .join(
                ExternalSubscription,
                ExternalSubscription.subscription_id == BillingProductAccessScope.primary_subscription_id,
            )
            .join(PurchaseIntent, PurchaseIntent.purchase_intent_id == ExternalSubscription.purchase_intent_id)
            .where(BillingProductAccessScope.user_id == user_id, BillingProductAccessScope.product_id.in_(products))
        )
        .tuples()
        .all()
    )
