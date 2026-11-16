"""Bounded local evidence reads and review locks for privileged operations."""

from uuid import UUID

from sqlalchemy import Text, and_, cast, exists, or_, select
from sqlalchemy.orm import Session

from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingWorkItem,
    ExternalCreateOperation,
    ExternalSubscription,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState,
    ExternalCreateOperationKind,
)


def review(db: Session, case_id: UUID, *, lock: bool = False) -> ManualReviewCase | None:
    query = select(ManualReviewCase).where(ManualReviewCase.review_case_id == case_id)
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return db.scalar(query)


def reviews(
    db: Session,
    purchase_id: UUID,
    customer_id: UUID,
    subscription_id: UUID | None,
    *,
    open_only: bool = False,
    lock: bool = False,
    include_paid_diagnostics: bool = False,
) -> list[ManualReviewCase]:
    operations = select(ExternalCreateOperation.create_operation_id).where(
        (ExternalCreateOperation.purchase_intent_id == purchase_id)
        | (
            (ExternalCreateOperation.customer_id == customer_id)
            & (ExternalCreateOperation.purchase_intent_id.is_(None))
        )
    )
    scopes = [
        and_(
            ManualReviewCase.scope_kind == "create_operation",
            ManualReviewCase.scope_reference.in_(select(cast(operations.subquery().c.create_operation_id, Text))),
        ),
        and_(ManualReviewCase.scope_kind == "subscription", ManualReviewCase.scope_reference == str(subscription_id)),
        and_(ManualReviewCase.scope_kind == "purchase_intent", ManualReviewCase.scope_reference == str(purchase_id)),
    ]
    if include_paid_diagnostics:
        access_scopes = (
            select(cast(BillingProductAccessScope.access_scope_id, Text))
            .join(
                PurchaseIntent,
                (PurchaseIntent.user_id == BillingProductAccessScope.user_id)
                & (PurchaseIntent.product_id == BillingProductAccessScope.product_id),
            )
            .where(PurchaseIntent.purchase_intent_id == purchase_id)
        )
        scopes.append(
            and_(
                ManualReviewCase.scope_kind == "product_competitor",
                ManualReviewCase.scope_reference.in_(access_scopes),
            )
        )
        if subscription_id is not None:
            scopes.append(
                and_(
                    ManualReviewCase.scope_kind == "subscription_metric",
                    ManualReviewCase.scope_reference.startswith(f"{subscription_id}:", autoescape=True),
                )
            )
    # Diagnostic visibility does not authorize either scope for resolution.
    # validate_case keeps the original exact purchase/operation/subscription set.
    query = select(ManualReviewCase).where(or_(*scopes))
    if open_only:
        query = query.where(ManualReviewCase.case_state == "open")
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(
        db.scalars(query.order_by(ManualReviewCase.created_at.desc(), ManualReviewCase.review_case_id).limit(101))
    )


def subscription(db: Session, purchase_id: UUID) -> ExternalSubscription | None:
    return db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchase_id))


def released_object_owners(
    db: Session, customer_id: UUID, agreement_ids: tuple[str, ...], subscription_ids: tuple[str, ...]
) -> list[PurchaseIntent]:
    return list(
        db.scalars(
            select(PurchaseIntent)
            .where(
                PurchaseIntent.customer_id == customer_id,
                PurchaseIntent.state.in_(tuple(state for state in PurchaseIntentState if state.resolved)),
                exists().where(
                    ExternalCreateOperation.purchase_intent_id == PurchaseIntent.purchase_intent_id,
                    or_(
                        and_(
                            ExternalCreateOperation.operation_kind == ExternalCreateOperationKind.AGREEMENT,
                            ExternalCreateOperation.bound_external_object_id.in_(agreement_ids),
                        ),
                        and_(
                            ExternalCreateOperation.operation_kind == ExternalCreateOperationKind.SUBSCRIPTION,
                            ExternalCreateOperation.bound_external_object_id.in_(subscription_ids),
                        ),
                    ),
                ),
            )
            .order_by(PurchaseIntent.purchase_intent_id)
            .limit(101)
        )
    )


def observations(db: Session, subscription_id: UUID) -> list[BillingStateObservation]:
    return list(
        db.scalars(
            select(BillingStateObservation)
            .where(BillingStateObservation.subscription_id == subscription_id)
            .order_by(BillingStateObservation.created_at.desc(), BillingStateObservation.observation_id)
            .limit(20)
        )
    )


def work(db: Session, references: tuple[str, ...]) -> list[BillingWorkItem]:
    return list(
        db.scalars(
            select(BillingWorkItem)
            .where(BillingWorkItem.scope_reference.in_(references))
            .order_by(BillingWorkItem.work_item_id)
            .limit(101)
        )
    )


def has_open_purchase_review(db: Session, customer_id: UUID, *, reason: str) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    PurchaseIntent.customer_id == customer_id,
                    ManualReviewCase.scope_kind == "purchase_intent",
                    ManualReviewCase.scope_reference == cast(PurchaseIntent.purchase_intent_id, Text),
                    ManualReviewCase.reason_code == reason,
                    ManualReviewCase.case_state == "open",
                )
            )
        )
    )
