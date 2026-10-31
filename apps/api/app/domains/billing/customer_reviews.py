"""Locked customer admission and narrowly evidenced original-key recovery."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.domains.billing.contracts import BillingRefused
from app.infrastructure.queries.billing_customers import open_customer_reviews
from app.models import (
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperation,
    ExternalCreateOperationState as State,
    ManualReviewCase,
)

CUSTOMER_UNKNOWN_REVIEW = "external_create_outcome_unknown:customer"
CUSTOMER_KEY_REVIEW = "customer_original_key_mismatch"
CUSTOMER_KEY_EVIDENCE = "customer-original-key-mismatch:v1"


def customer_admission_reviews(
    db: Session, customer: ExternalBillingCustomer, operation: ExternalCreateOperation
) -> list[ManualReviewCase]:
    """Caller holds the customer lock; unresolved conflicts never authorize sends."""
    reviews = open_customer_reviews(db, operation.create_operation_id)
    _check_reviews(customer, reviews, allow_key_recovery=False)
    return reviews


def customer_recovery_reviews(
    db: Session, customer: ExternalBillingCustomer, operation: ExternalCreateOperation
) -> list[ManualReviewCase]:
    """Allow only read-only recovery of the recorded, previously proven ID."""
    reviews = open_customer_reviews(db, operation.create_operation_id)
    key_reviews = [review for review in reviews if review.reason_code == CUSTOMER_KEY_REVIEW]
    allow_key_recovery = bool(key_reviews) and (
        customer.provider_customer_id is not None
        and operation.bound_external_object_id == customer.provider_customer_id
        and operation.request_correlation_key == customer.billing_customer_key
        and operation.operation_state == State.MANUAL_REVIEW
        and all(
            review.evidence_schema_version == CUSTOMER_KEY_EVIDENCE
            and review.evidence_document
            == {
                "create_operation_id": str(operation.create_operation_id),
                "provider_customer_id": customer.provider_customer_id,
            }
            for review in key_reviews
        )
    )
    _check_reviews(customer, reviews, allow_key_recovery=allow_key_recovery)
    return reviews


def _check_reviews(
    customer: ExternalBillingCustomer, reviews: list[ManualReviewCase], *, allow_key_recovery: bool
) -> None:
    allowed = {CUSTOMER_UNKNOWN_REVIEW}
    if allow_key_recovery:
        allowed.add(CUSTOMER_KEY_REVIEW)
    blocked = any(review.reason_code not in allowed for review in reviews)
    if customer.binding_state == Binding.IDENTITY_CONFLICT and (not allow_key_recovery or blocked):
        raise BillingRefused("billing_identity_conflict", 409)
    if blocked:
        raise BillingRefused("billing_customer_review", 409)


def record_customer_review(db: Session, operation: ExternalCreateOperation, reason: str) -> None:
    if not any(review.reason_code == reason for review in open_customer_reviews(db, operation.create_operation_id)):
        key_mismatch = reason == CUSTOMER_KEY_REVIEW
        evidence = {"create_operation_id": str(operation.create_operation_id)}
        if key_mismatch:
            evidence["provider_customer_id"] = operation.bound_external_object_id
        db.add(
            ManualReviewCase(
                reason_code=reason,
                scope_kind="create_operation",
                scope_reference=str(operation.create_operation_id),
                evidence_schema_version=CUSTOMER_KEY_EVIDENCE if key_mismatch else "v1",
                evidence_document=evidence,
                case_state="open",
            )
        )
    operation.operation_state = State.MANUAL_REVIEW


def record_customer_conflict(
    db: Session,
    customer: ExternalBillingCustomer,
    operation: ExternalCreateOperation,
    *,
    provider_id: str | None,
    ambiguous: bool,
) -> None:
    # Only a point read of the already proven ID can establish this narrow
    # cause. First discovery, another ID and Client-scope ambiguity stay blocked.
    original_id = (
        not ambiguous
        and provider_id is not None
        and customer.binding_state in {Binding.BOUND, Binding.IDENTITY_CONFLICT}
        and customer.provider_customer_id == operation.bound_external_object_id == provider_id
    )
    customer.binding_state = Binding.IDENTITY_CONFLICT
    operation.send_fence = uuid4()  # Invalidate all earlier in-flight proof.
    record_customer_review(db, operation, CUSTOMER_KEY_REVIEW if original_id else "customer_identity_conflict")
