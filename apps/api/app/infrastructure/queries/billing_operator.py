"""Bounded local evidence reads and review locks for privileged operations."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Text, and_, cast, or_, select, exists
from sqlalchemy.orm import Session

from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    BillingWorkItem,
    ExternalCreateOperation,
    ExternalSubscription,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    ManualReviewCase,
    PurchaseIntent,
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
    limit: int | None = 101,
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
        db.scalars(query.order_by(ManualReviewCase.created_at.desc(), ManualReviewCase.review_case_id).limit(limit))
    )


def purchase_resolution_audit(db: Session, purchase_id: UUID, *, reason: str, schema: str) -> ManualReviewCase | None:
    return db.scalar(
        select(ManualReviewCase).where(
            ManualReviewCase.scope_kind == "purchase_intent",
            ManualReviewCase.scope_reference == str(purchase_id),
            ManualReviewCase.reason_code == reason,
            ManualReviewCase.evidence_schema_version == schema,
            ManualReviewCase.resolution_schema_version == schema,
            ManualReviewCase.case_state == "resolved",
        )
    )


def other_financial_binding(db: Session, operation: ExternalCreateOperation, external_id: str) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    ExternalCreateOperation.external_billing_account_id == operation.external_billing_account_id,
                    ExternalCreateOperation.operation_kind == operation.operation_kind,
                    ExternalCreateOperation.bound_external_object_id == external_id,
                    ExternalCreateOperation.create_operation_id != operation.create_operation_id,
                )
            )
        )
    )


def has_newer_live_subscription_read(
    db: Session,
    subscription_id: UUID,
    confirmed_at: datetime,
    *,
    schemas: tuple[str, ...],
    preparation_schema: str,
    matched_identity: str,
) -> bool:
    observation = BillingStateObservation
    evidence = observation.evidence_document
    first_binding = evidence["original_proof"]["subscription"]
    live = (Lifecycle.ACTIVE.value, Lifecycle.INACTIVE.value)
    live_read = exists().where(
        observation.subscription_id == subscription_id,
        observation.observation_kind == BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ,
        observation.observed_at > confirmed_at,
        or_(
            and_(
                observation.evidence_schema_version.in_(schemas),
                evidence["identity"].as_string() == matched_identity,
                evidence["lifecycle"].as_string().in_(live),
            ),
            and_(
                observation.evidence_schema_version == preparation_schema,
                first_binding["identity"].as_string() == matched_identity,
                first_binding["lifecycle"].as_string().in_(live),
            ),
        ),
    )
    return bool(db.scalar(select(live_read)))


def subscription(db: Session, purchase_id: UUID) -> ExternalSubscription | None:
    return db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchase_id))


def observations(db: Session, subscription_id: UUID) -> list[BillingStateObservation]:
    return list(
        db.scalars(
            select(BillingStateObservation)
            .where(BillingStateObservation.subscription_id == subscription_id)
            .order_by(BillingStateObservation.created_at.desc(), BillingStateObservation.observation_id)
            .limit(20)
        )
    )


def work(
    db: Session, references: tuple[str, ...], *, limit: int | None = 101, lock: bool = False
) -> list[BillingWorkItem]:
    query = (
        select(BillingWorkItem)
        .where(BillingWorkItem.scope_reference.in_(references))
        .order_by(BillingWorkItem.work_item_id)
        .limit(limit)
    )
    if lock:
        query = query.with_for_update()
    return list(db.scalars(query))
