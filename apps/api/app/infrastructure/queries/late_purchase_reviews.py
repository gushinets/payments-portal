"""Point lookups for late purchase cases and retained original identities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Select, Text, and_, cast, exists, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Exists

from app.models import (
    ExternalBillingCustomer as Customer,
    ExternalCreateOperation as Operation,
    ExternalCreateOperationKind as Kind,
    ManualReviewCase as Case,
    PurchaseIntent as Purchase,
    PurchaseIntentState as State,
)


def _purchase_cases(reason: str, schema: str) -> tuple[ColumnElement[bool], ...]:
    return (
        Case.scope_kind == "purchase_intent",
        Case.scope_reference == cast(Purchase.purchase_intent_id, Text),
        Case.reason_code == reason,
        Case.evidence_schema_version == schema,
    )


def _object_cases(account: str, kind: Kind, external_id: str, *, reason: str, schema: str) -> Select[tuple[Case]]:
    document = Case.evidence_document
    return (
        select(Case)
        .join(Purchase, Case.scope_reference == cast(Purchase.purchase_intent_id, Text))
        .where(
            *_purchase_cases(reason, schema),
            Purchase.external_billing_account_id == account,
            document["kind"].as_string() == kind.value,
            document["external_object_id"].as_string() == external_id,
        )
    )


def object_cases(db: Session, account: str, kind: Kind, external_id: str, *, reason: str, schema: str) -> list[Case]:
    return list(
        db.scalars(
            _object_cases(account, kind, external_id, reason=reason, schema=schema).where(Case.case_state == "open")
        )
    )


def other_late_object_owner(
    db: Session, purchase: Purchase, kind: Kind, external_id: str, *, reason: str, schema: str
) -> bool:
    """Match retained ownership even after the late case has been closed."""
    query = _object_cases(purchase.external_billing_account_id, kind, external_id, reason=reason, schema=schema).where(
        Purchase.purchase_intent_id != purchase.purchase_intent_id
    )
    return bool(db.scalar(select(query.exists())))


def latest_closed_subscription_scope(
    db: Session,
    account: str,
    purchase_id: UUID,
    external_id: str,
    read_finished_at: datetime,
    *,
    reason: str,
    schema: str,
    closure_schema: str,
) -> Case | None:
    return db.scalar(
        _object_cases(account, Kind.SUBSCRIPTION, external_id, reason=reason, schema=schema)
        .where(
            Case.scope_reference == str(purchase_id),
            Case.case_state == "resolved",
            Case.resolution_schema_version == closure_schema,
            Case.resolved_at < read_finished_at,
            Case.evidence_document["agreement_id"].as_string().is_not(None),
        )
        .order_by(Case.resolved_at.desc(), Case.review_case_id.desc())
        .limit(1)
    )


def has_terminal_closure(
    db: Session,
    account: str,
    kind: Kind,
    external_id: str,
    *,
    reason: str,
    schema: str,
    closure_schema: str,
    closure_outcome: str,
) -> bool:
    evidence = Case.resolution_document["request"]["evidence"]
    query = _object_cases(account, kind, external_id, reason=reason, schema=schema).where(
        Case.case_state == "resolved",
        Case.resolution_schema_version == closure_schema,
        evidence["outcome"].as_string() == closure_outcome,
        evidence["external_object_id"].as_string() == external_id,
    )
    return bool(db.scalar(select(query.exists())))


def _subscription_case_ids(identities: set[str]) -> ColumnElement[bool]:
    evidence = Case.evidence_document
    return and_(
        evidence["kind"].as_string() == Kind.SUBSCRIPTION.value,
        evidence["external_object_id"].as_string().in_(identities),
    )


def purchase_object_ids(
    db: Session, purchase_id: UUID, *, reason: str, schema: str, subscription_ids: set[str] | None = None
) -> list[tuple[str, str]]:
    evidence = Case.evidence_document
    query = select(evidence["kind"].as_string(), evidence["external_object_id"].as_string()).where(
        Case.scope_kind == "purchase_intent",
        Case.scope_reference == str(purchase_id),
        Case.reason_code == reason,
        Case.evidence_schema_version == schema,
    )
    if subscription_ids is not None:
        query = query.where(_subscription_case_ids(subscription_ids))
    return [tuple(row) for row in db.execute(query.distinct().limit(101))]


def product_cases(
    db: Session,
    customer_id: UUID,
    product_id: str,
    tariff_id: int,
    *,
    reason: str,
    schema: str,
) -> list[Case]:
    return list(
        db.scalars(
            select(Case)
            .join(Purchase, Case.scope_reference == cast(Purchase.purchase_intent_id, Text))
            .where(
                *_purchase_cases(reason, schema),
                Purchase.customer_id == customer_id,
                or_(
                    Purchase.product_id == product_id,
                    Case.evidence_document["competing_tariff_id"].as_integer() == tariff_id,
                ),
                Case.case_state == "open",
            )
            .order_by(Case.created_at, Case.review_case_id)
        )
    )


def _attests_original(identities: set[str], *, reason: str, schema: str) -> Exists:
    audit = aliased(Case)
    proofs = audit.resolution_document["request"]["evidence"]["operations"]
    return (
        exists()
        .where(
            audit.scope_kind == "purchase_intent",
            audit.scope_reference == cast(Operation.purchase_intent_id, Text),
            audit.case_state == "resolved",
            audit.reason_code == reason,
            audit.evidence_schema_version == schema,
            audit.resolution_schema_version == schema,
            or_(
                *(
                    and_(
                        proofs[index]["operation_id"].as_string() == cast(Operation.create_operation_id, Text),
                        proofs[index]["external_object_id"].as_string().in_(identities),
                    )
                    for index in (0, 1)
                ),
            ),
        )
        .correlate_except(audit)
    )


def other_audited_owner(db: Session, operation: Operation, external_id: str, *, reason: str, schema: str) -> bool:
    return bool(
        db.scalar(
            select(
                exists().where(
                    Operation.external_billing_account_id == operation.external_billing_account_id,
                    Operation.operation_kind == operation.operation_kind,
                    Operation.create_operation_id != operation.create_operation_id,
                    _attests_original({external_id}, reason=reason, schema=schema),
                )
            )
        )
    )


def released_owners(
    db: Session,
    customer_id: UUID,
    agreement_ids: set[str],
    subscription_ids: set[str],
    agreement_number: str | None = None,
    *,
    audit_reason: str,
    audit_schema: str,
    case_reason: str,
    case_schema: str,
) -> list[Purchase]:
    def matches(kind: Kind, identities: set[str]) -> ColumnElement[bool]:
        by_number = kind == Kind.AGREEMENT and agreement_number is not None
        return and_(
            Operation.operation_kind == kind,
            or_(
                Operation.bound_external_object_id.in_(identities),
                _attests_original(identities, reason=audit_reason, schema=audit_schema),
                Operation.request_correlation_key == agreement_number if by_number else False,
            ),
        )

    operation_matches = exists().where(
        Operation.purchase_intent_id == Purchase.purchase_intent_id,
        or_(matches(Kind.AGREEMENT, agreement_ids), matches(Kind.SUBSCRIPTION, subscription_ids)),
    )
    case_matches = exists().where(
        *_purchase_cases(case_reason, case_schema),
        _subscription_case_ids(subscription_ids),
    )
    return list(
        db.scalars(
            select(Purchase)
            .join(Customer, Customer.customer_id == Purchase.customer_id)
            .where(
                Purchase.customer_id == customer_id,
                Purchase.external_billing_account_id == Customer.external_billing_account_id,
                Purchase.state.in_((State.RESOLVED_EXTERNAL_TERMINAL, State.RESOLVED_NO_EXTERNAL_EFFECT)),
                or_(operation_matches, case_matches),
            )
            .order_by(Purchase.purchase_intent_id)
            .limit(101)
        )
    )
