"""Purchase manual-review writes and explicit overdue escalation; no worker."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.domains.purchases.contracts import AcceptedPurchase
from app.domains.purchases.preparation_contracts import PreparationEvidence
from app.infrastructure.queries import purchase_preparation as queries
from app.models import (
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState,
    ExternalCreateOperation,
    ExternalCreateOperationKind,
    ExternalCreateOperationState,
    ManualReviewCase,
    PurchaseIntent,
    PurchaseIntentState,
)


def review_operation(
    db: Session,
    operation: ExternalCreateOperation,
    intent: PurchaseIntent,
    *,
    reason: str,
    principal: str,
    identity_conflict: bool,
    clock: Callable[[], datetime],
    decode_record: Callable[[str], PreparationEvidence],
) -> None:
    if queries.open_review(db, operation.create_operation_id) is None:
        db.add(
            ManualReviewCase(
                reason_code=reason,
                scope_kind="external_create_operation",
                scope_reference=str(operation.create_operation_id),
                evidence_schema_version="v1",
                evidence_document={
                    "evidence_mode": AcceptedPurchase.model_validate_json(
                        json.dumps(intent.accepted_snapshot)
                    ).review.mapping.evidence_mode,
                    "billing_evidence_mode": decode_record(
                        json.dumps(operation.recovery_hint_document)
                    ).billing_evidence_mode,
                    "principal": principal,
                    "send_fencing_token": operation.send_fencing_token,
                    "scope_ownership_epoch": operation.scope_ownership_epoch,
                },
                case_state="open",
            )
        )
    operation.operation_state = ExternalCreateOperationState.MANUAL_REVIEW
    operation.updated_at = clock()
    queries.complete_recovery_item(db, operation.create_operation_id)
    if identity_conflict and operation.operation_kind == ExternalCreateOperationKind.CUSTOMER:
        customer = db.get(ExternalBillingCustomer, operation.customer_id)
        customer.binding_state = ExternalBillingCustomerBindingState.IDENTITY_CONFLICT
        customer.binding_updated_at = clock()
    intent.state = PurchaseIntentState.MANUAL_REVIEW
    intent.state_updated_at = clock()


def escalate_overdue(
    factory: sessionmaker[Session],
    user_id: UUID,
    intent_id: UUID,
    *,
    principal: str,
    owned: Callable[[Session, UUID, UUID], PurchaseIntent],
    clock: Callable[[], datetime],
    review: Callable[[Session, ExternalCreateOperation, PurchaseIntent], None],
) -> int:
    """Explicit operator invocation; retain the caller's transaction and lock order."""
    if not principal.strip():
        raise ValueError("audited operator principal required")
    changed = 0
    with factory.begin() as db:
        intent = owned(db, user_id, intent_id)
        queries.lock_original_scope(db, intent)
        for kind in ExternalCreateOperationKind:
            operation = queries.operation_for(db, intent, kind)
            if (
                operation is not None
                and operation.operation_state
                in (ExternalCreateOperationState.POSSIBLE_SEND, ExternalCreateOperationState.UNKNOWN)
                and operation.unknown_recovery_deadline_at is not None
                and operation.unknown_recovery_deadline_at <= clock()
            ):
                review(db, operation, intent)
                queries.complete_recovery_item(db, operation.create_operation_id)
                changed += 1
    return changed
