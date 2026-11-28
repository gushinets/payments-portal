"""Durable reviews raised by competing financial evidence."""

from uuid import uuid4
from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domains.billing.customer_reviews import restrict_subscription
from app.domains.purchases.contracts import FINANCIAL_REVIEW_SCHEMA, ORIGINAL_ID_CONFLICT, FinancialReviewEvidence
from app.infrastructure.queries import purchases as queries
from app.infrastructure.queries.billing_customers import open_customer_reviews
from app.models import (
    ExternalCreateOperation,
    ExternalCreateOperationState as State,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState as IntentState,
)


def record_financial_review(db: Session, row: PurchaseIntent, operation: ExternalCreateOperation, reason: str) -> None:
    existing = any(case.reason_code == reason for case in open_customer_reviews(db, operation.create_operation_id))
    if not existing:
        db.add(
            ManualReviewCase(
                reason_code=reason,
                scope_kind="create_operation",
                scope_reference=str(operation.create_operation_id),
                evidence_schema_version=FINANCIAL_REVIEW_SCHEMA,
                evidence_document=FinancialReviewEvidence(
                    purchase_intent_id=row.purchase_intent_id,
                    create_operation_id=operation.create_operation_id,
                    operation_state_at_conflict=operation.operation_state,
                    send_fence_at_conflict=operation.send_fence,
                ).model_dump(mode="json"),
                case_state="open",
            )
        )
    if not existing or operation.operation_state != State.MANUAL_REVIEW:
        operation.send_fence = uuid4()
    operation.operation_state = State.MANUAL_REVIEW
    sub = queries.linked_subscription(db, row.purchase_intent_id)
    if sub is not None:
        restrict_subscription(sub)
    row.state = IntentState.MANUAL_REVIEW
    row.state_updated_at = utc_now()


def review_identity_conflict(db: Session, row: PurchaseIntent, op: ExternalCreateOperation) -> None:
    from app.domains.billing.paid_access import reduce_paid_access

    record_financial_review(db, row, op, ORIGINAL_ID_CONFLICT)
    reduce_paid_access(db, row.user_id)
