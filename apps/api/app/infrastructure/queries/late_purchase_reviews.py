"""Point lookups for late purchase cases and retained original identities."""

from uuid import UUID

from sqlalchemy import Text, and_, cast, exists, or_, select
from sqlalchemy.orm import Session, aliased
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Exists

from app.models import (
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


def object_cases(db: Session, account: str, kind: Kind, external_id: str, *, reason: str, schema: str) -> list[Case]:
    document = Case.evidence_document
    query = (
        select(Case)
        .join(Purchase, Case.scope_reference == cast(Purchase.purchase_intent_id, Text))
        .where(
            *_purchase_cases(reason, schema),
            Purchase.external_billing_account_id == account,
            document["kind"].as_string() == kind.value,
            document["external_object_id"].as_string() == external_id,
            Case.case_state == "open",
        )
    )
    return list(db.scalars(query))


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

    return list(
        db.scalars(
            select(Purchase)
            .where(
                Purchase.customer_id == customer_id,
                Purchase.state.in_((State.RESOLVED_EXTERNAL_TERMINAL, State.RESOLVED_NO_EXTERNAL_EFFECT)),
                exists().where(
                    Operation.purchase_intent_id == Purchase.purchase_intent_id,
                    or_(matches(Kind.AGREEMENT, agreement_ids), matches(Kind.SUBSCRIPTION, subscription_ids)),
                ),
            )
            .order_by(Purchase.purchase_intent_id)
            .limit(101)
        )
    )
