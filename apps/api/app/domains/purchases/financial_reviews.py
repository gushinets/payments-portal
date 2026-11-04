"""Financial review transitions inside the caller's locked transaction."""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.infrastructure.queries.billing_customers import open_customer_reviews
from app.models import (
    ExternalCreateOperation,
    ExternalCreateOperationState as State,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState as IntentState,
)


def record_review(db: Session, row: PurchaseIntent, operation: ExternalCreateOperation, reason: str) -> None:
    if not any(case.reason_code == reason for case in open_customer_reviews(db, operation.create_operation_id)):
        db.add(
            ManualReviewCase(
                reason_code=reason,
                scope_kind="create_operation",
                scope_reference=str(operation.create_operation_id),
                evidence_schema_version="financial-review:v1",
                evidence_document={
                    "purchase_intent_id": str(row.purchase_intent_id),
                    "create_operation_id": str(operation.create_operation_id),
                    "operation_state_at_conflict": operation.operation_state.value,
                    "send_fence_at_conflict": str(operation.send_fence) if operation.send_fence else None,
                },
                case_state="open",
            )
        )
    operation.operation_state = State.MANUAL_REVIEW
    operation.send_fence = uuid4()
    row.state = IntentState.MANUAL_REVIEW
    row.state_updated_at = utc_now()
