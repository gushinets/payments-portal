"""Bounded local evidence reads and review locks for privileged operations."""

from uuid import UUID

from sqlalchemy import Text, and_, cast, exists, or_, select
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased
from sqlalchemy.sql import ColumnElement
from sqlalchemy.sql.selectable import Exists

from app.infrastructure.persistence.billing_connections import billing_scope_key, lock_billing_key
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
    open_first: bool = False,
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
    if open_first:
        query = query.order_by((ManualReviewCase.case_state == "open").desc())
    return list(
        db.scalars(query.order_by(ManualReviewCase.created_at.desc(), ManualReviewCase.review_case_id).limit(limit))
    )


def purchase_cases(
    db: Session,
    purchase_id: UUID,
    *,
    reason: str,
    schema: str,
    object_identity: tuple[UUID, str] | None = None,
    resolved_only: bool = False,
) -> list[ManualReviewCase]:
    query = select(ManualReviewCase).where(
        ManualReviewCase.scope_kind == "purchase_intent",
        ManualReviewCase.scope_reference == str(purchase_id),
        ManualReviewCase.reason_code == reason,
        ManualReviewCase.evidence_schema_version == schema,
    )
    if object_identity is not None:
        operation_id, external_id = object_identity
        query = query.where(
            ManualReviewCase.evidence_document["operation_id"].as_string() == str(operation_id),
            ManualReviewCase.evidence_document["external_object_id"].as_string() == external_id,
        )
    if resolved_only:
        query = query.where(ManualReviewCase.case_state == "resolved")
    return list(db.scalars(query))


def subscription(db: Session, purchase_id: UUID) -> ExternalSubscription | None:
    return db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchase_id))


def financial_binding(
    db: Session, account_id: str, kind: ExternalCreateOperationKind, external_id: str
) -> ExternalCreateOperation | None:
    return db.scalar(
        select(ExternalCreateOperation).where(
            ExternalCreateOperation.external_billing_account_id == account_id,
            ExternalCreateOperation.operation_kind == kind,
            ExternalCreateOperation.bound_external_object_id == external_id,
        )
    )


def _attests_original_object(
    purchase_id: InstrumentedAttribute[UUID],
    object_ids: tuple[str, ...] | ColumnElement[str],
    *,
    audit_schema: str,
    audit_reasons: tuple[str, ...],
) -> Exists:
    audit = aliased(ManualReviewCase)
    proofs = audit.resolution_document["request"]["evidence"]["operations"]

    def matches_proof(index: int) -> ColumnElement[bool]:
        object_id = proofs[index]["external_object_id"].as_string()
        return and_(
            proofs[index]["operation_id"].as_string() == cast(ExternalCreateOperation.create_operation_id, Text),
            object_id.in_(object_ids) if isinstance(object_ids, tuple) else object_id == object_ids,
        )

    return (
        exists()
        .where(
            audit.scope_kind == "purchase_intent",
            audit.scope_reference == cast(purchase_id, Text),
            audit.case_state == "resolved",
            audit.reason_code.in_(audit_reasons),
            audit.resolution_schema_version == audit_schema,
            or_(matches_proof(0), matches_proof(1)),
        )
        .correlate_except(audit)
    )


def lock_and_check_other_financial_owner(
    db: Session,
    operation: ExternalCreateOperation,
    external_id: str,
    *,
    audit_schema: str,
    audit_reasons: tuple[str, ...],
) -> bool:
    # A new binding and a terminal attestation can be the first record of an ID
    # on different users. Serialize both writers even when no binding exists yet.
    account = operation.external_billing_account_id
    kind = operation.operation_kind
    lock_billing_key(db, billing_scope_key("payments-portal/financial-object/v1", account, kind.value, external_id))
    other = exists().where(
        ExternalCreateOperation.external_billing_account_id == account,
        ExternalCreateOperation.operation_kind == kind,
        ExternalCreateOperation.create_operation_id != operation.create_operation_id,
    )
    bound = other.where(ExternalCreateOperation.bound_external_object_id == external_id)
    attested = other.where(
        _attests_original_object(
            ExternalCreateOperation.purchase_intent_id,
            (external_id,),
            audit_schema=audit_schema,
            audit_reasons=audit_reasons,
        )
    )
    return bool(db.scalar(select(or_(bound, attested))))


def released_object_owners(
    db: Session,
    customer_id: UUID,
    agreement_ids: tuple[str, ...],
    subscription_ids: tuple[str, ...],
    *,
    audit_schema: str,
    audit_reasons: tuple[str, ...],
) -> list[PurchaseIntent]:
    def matches(kind: ExternalCreateOperationKind, ids: tuple[str, ...]) -> ColumnElement[bool]:
        return and_(
            ExternalCreateOperation.operation_kind == kind,
            or_(
                ExternalCreateOperation.bound_external_object_id.in_(ids),
                _attests_original_object(
                    PurchaseIntent.purchase_intent_id, ids, audit_schema=audit_schema, audit_reasons=audit_reasons
                ),
            ),
        )

    return list(
        db.scalars(
            select(PurchaseIntent)
            .where(
                PurchaseIntent.customer_id == customer_id,
                PurchaseIntent.state.in_(tuple(state for state in PurchaseIntentState if state.resolved)),
                exists().where(
                    ExternalCreateOperation.purchase_intent_id == PurchaseIntent.purchase_intent_id,
                    or_(
                        matches(ExternalCreateOperationKind.AGREEMENT, agreement_ids),
                        matches(ExternalCreateOperationKind.SUBSCRIPTION, subscription_ids),
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


def _open_purchase_reviews(customer_id: UUID, reason: str) -> Exists:
    return exists().where(
        PurchaseIntent.customer_id == customer_id,
        ManualReviewCase.scope_kind == "purchase_intent",
        ManualReviewCase.scope_reference == cast(PurchaseIntent.purchase_intent_id, Text),
        ManualReviewCase.reason_code == reason,
        ManualReviewCase.case_state == "open",
    )


def has_open_purchase_review(db: Session, customer_id: UUID, *, reason: str) -> bool:
    return bool(db.scalar(select(_open_purchase_reviews(customer_id, reason))))


def has_open_purchase_review_for_product(
    db: Session,
    customer_id: UUID,
    *,
    reason: str,
    product_id: str,
    tariff_id: int | None,
    audit_schema: str,
    audit_reasons: tuple[str, ...],
) -> bool:
    related = aliased(PurchaseIntent)
    evidence = ManualReviewCase.evidence_document
    observed_agreement_id = evidence["observed_agreement_id"].as_string()
    observed_owner = (
        exists()
        .where(
            related.customer_id == customer_id,
            related.product_id == product_id,
            ExternalCreateOperation.purchase_intent_id == related.purchase_intent_id,
            or_(
                and_(
                    ExternalCreateOperation.operation_kind == ExternalCreateOperationKind.AGREEMENT,
                    or_(
                        ExternalCreateOperation.bound_external_object_id == observed_agreement_id,
                        and_(
                            related.state.in_(tuple(state for state in PurchaseIntentState if state.resolved)),
                            _attests_original_object(
                                related.purchase_intent_id,
                                observed_agreement_id,
                                audit_schema=audit_schema,
                                audit_reasons=audit_reasons,
                            ),
                        ),
                    ),
                ),
                and_(
                    evidence["bound_to_another_operation"].as_boolean().is_(True),
                    ExternalCreateOperation.operation_kind == ExternalCreateOperationKind.SUBSCRIPTION,
                    ExternalCreateOperation.bound_external_object_id == evidence["external_object_id"].as_string(),
                ),
            ),
        )
        .correlate(ManualReviewCase)
    )
    affected = [observed_owner]
    if tariff_id is not None:
        affected.append(cast(evidence["observed_tariff_id"].as_string(), Text) == str(tariff_id))
    # Legacy records stored observed relationship fields only for conflicts.
    restriction = _open_purchase_reviews(customer_id, reason).where(
        or_(
            PurchaseIntent.product_id == product_id,
            and_(evidence["relationship_conflict"].as_boolean().is_not(False), or_(*affected)),
        )
    )
    return bool(db.scalar(select(restriction)))
