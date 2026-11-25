"""Bounded local evidence reads and review locks for privileged operations."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import Select, Text, and_, cast, or_, select, exists
from sqlalchemy.orm import Session

from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    BillingWorkItem,
    BillingWorkScope,
    BillingWorkState,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
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


def has_newer_live_financial_point(
    db: Session,
    subscriptions: UUID | Select[tuple[UUID]],
    kind: Kind,
    external_id: str,
    confirmed_at: datetime,
    *,
    schemas: tuple[str, ...],
    preparation_schema: str,
    matched_identity: str,
) -> bool:
    observation = BillingStateObservation
    subscription_scope = (
        observation.subscription_id == subscriptions
        if isinstance(subscriptions, UUID)
        else observation.subscription_id.in_(subscriptions)
    )
    evidence = observation.evidence_document
    sources = (
        (observation.evidence_schema_version.in_(schemas), evidence),
        (observation.evidence_schema_version == preparation_schema, evidence["original_proof"]["subscription"]),
    )
    # New point times are UTC ISO strings at fixed precision. Use the enclosing
    # observation time for legacy evidence without an object-specific clock.
    confirmed_iso = confirmed_at.astimezone(UTC).isoformat(timespec="microseconds")
    agreement = kind == Kind.AGREEMENT
    link = ExternalSubscription.external_agreement_id if agreement else ExternalSubscription.external_subscription_id
    clauses = []
    for schema, document in sources:
        if agreement:
            point_time = document["agreement_read_finished_at"].as_string()
            live = document["agreement_open"].as_boolean().is_(True)
        else:
            point_time = document["subscription_read_finished_at"].as_string()
            live = and_(
                document["identity"].as_string() == matched_identity,
                document["lifecycle"].as_string().in_((Lifecycle.ACTIVE.value, Lifecycle.INACTIVE.value)),
            )
        clauses.append(
            and_(
                schema,
                live,
                or_(point_time > confirmed_iso, and_(point_time.is_(None), observation.observed_at > confirmed_at)),
            )
        )
    return bool(
        db.scalar(
            select(
                exists().where(
                    subscription_scope,
                    ExternalSubscription.subscription_id == observation.subscription_id,
                    link == external_id,
                    observation.observation_kind == BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ,
                    or_(*clauses),
                )
            )
        )
    )


def customer_subscription_ids(customer_id: UUID, account: str) -> Select[tuple[UUID]]:
    return select(ExternalSubscription.subscription_id).where(
        ExternalSubscription.customer_id == customer_id,
        ExternalSubscription.external_billing_account_id == account,
    )


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


def customer_work_active(db: Session, customer_id: UUID, account: str, now: datetime) -> bool:
    """Find same-customer work with a live lease or an unaccounted running claim."""
    item = BillingWorkItem
    sub = ExternalSubscription
    customer_ops = select(cast(ExternalCreateOperation.create_operation_id, Text)).where(
        ExternalCreateOperation.customer_id == customer_id,
        or_(
            ExternalCreateOperation.operation_kind == Kind.CUSTOMER,
            ExternalCreateOperation.external_billing_account_id == account,
        ),
    )
    customer_subs = select(cast(sub.subscription_id, Text)).where(
        sub.customer_id == customer_id, sub.external_billing_account_id == account
    )
    customer_purchases = select(cast(PurchaseIntent.purchase_intent_id, Text)).where(
        PurchaseIntent.customer_id == customer_id, PurchaseIntent.external_billing_account_id == account
    )
    active_work = exists().where(
        or_(
            and_(item.scope_kind == BillingWorkScope.CUSTOMER, item.scope_reference == str(customer_id)),
            and_(item.scope_kind == BillingWorkScope.CREATE_OPERATION, item.scope_reference.in_(customer_ops)),
            and_(item.scope_kind == BillingWorkScope.SUBSCRIPTION, item.scope_reference.in_(customer_subs)),
            and_(item.scope_kind == "purchase_intent", item.scope_reference.in_(customer_purchases)),
        ),
        or_(
            item.lease_expires_at > now,
            and_(item.work_state == BillingWorkState.RUNNING, item.lease_expires_at.is_(None)),
        ),
    )
    active_reconciliation = exists().where(
        sub.customer_id == customer_id,
        sub.external_billing_account_id == account,
        sub.reconciliation_lease_expires_at > now,
    )
    return bool(db.scalar(select(or_(active_work, active_reconciliation))))


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
        query = query.with_for_update().execution_options(populate_existing=True)
    return list(db.scalars(query))
