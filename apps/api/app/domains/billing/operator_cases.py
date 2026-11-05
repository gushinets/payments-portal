"""Exact review relationships accepted by the existing audited operator actions."""

from uuid import UUID
from sqlalchemy.orm import Session

from app.domains.billing.operator_contracts import ResolutionRequest
from app.domains.catalog.commercial_offer import canonical_document, commercial_digest
from app.domains.purchases.contracts import Purchase, PurchaseRefused
from app.infrastructure.queries import billing_operator as queries
from app.models import (
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ManualReviewCase,
    BillingStateObservation,
)

RESTORABLE = {
    "subscription_identity_conflict",
    "subscription_commercial_mismatch",
    "financial_binding_conflict",
    "accepted_terms_changed_after_preparation",
    "customer_inventory_conflict",
}
BINDABLE = {"financial_binding_conflict", "accepted_terms_changed_after_preparation", "customer_inventory_conflict"}


def digest(value: object) -> str:
    return commercial_digest(canonical_document(value))


def case_digest(case: ManualReviewCase) -> str:
    return digest(
        {
            "id": str(case.review_case_id),
            "reason": case.reason_code,
            "scope": [case.scope_kind, case.scope_reference],
            "schema": case.evidence_schema_version,
            "evidence": case.evidence_document,
        }
    )


def possible_send_case(case: ManualReviewCase) -> bool:
    evidence = case.evidence_document
    if not isinstance(evidence, dict) or evidence.get("operation_state_at_conflict") not in {
        State.POSSIBLE_SEND.value,
        State.UNKNOWN.value,
    }:
        return False
    try:
        return str(UUID(evidence["send_fence_at_conflict"])) == evidence["send_fence_at_conflict"]
    except (KeyError, TypeError, ValueError, AttributeError):
        return False


def original_possible_send(case: ManualReviewCase, related: list[ManualReviewCase], purchase: Purchase) -> bool:
    evidence = case.evidence_document
    if (
        case.evidence_schema_version != "financial-review:v1"
        or not isinstance(evidence, dict)
        or evidence.get("purchase_intent_id") != str(purchase.id)
        or evidence.get("create_operation_id") != case.scope_reference
    ):
        return False
    if possible_send_case(case):
        return True
    # Deadline escalation rotates the send fence and moves the operation to
    # MANUAL_REVIEW. Its preserved earlier evidence still proves possible-send;
    # no new send can be authorized while this review is open. Database-created
    # timestamps reflect transaction starts, not the causal order of these
    # locked transitions; the saved prior states establish that order.
    return evidence.get("operation_state_at_conflict") == State.MANUAL_REVIEW.value and any(
        possible_send_case(previous) for previous in related
    )


def inventory_case(case: ManualReviewCase, purchase: Purchase, operations: list[ExternalCreateOperation]) -> bool:
    evidence = case.evidence_document
    target = next((op for op in operations if op.operation_kind == Kind.SUBSCRIPTION), None)
    return bool(
        target is not None
        and case.reason_code == "customer_inventory_conflict"
        and (case.scope_kind, case.scope_reference) == ("create_operation", str(target.create_operation_id))
        and case.evidence_schema_version == "financial-review:v1"
        and isinstance(evidence, dict)
        and evidence.get("purchase_intent_id") == str(purchase.id)
        and evidence.get("create_operation_id") == str(target.create_operation_id)
        and evidence.get("operation_state_at_conflict")
        in {State.BOUND.value, State.POSSIBLE_SEND.value, State.UNKNOWN.value, State.MANUAL_REVIEW.value}
    )


def canonical_case(
    db: Session, case: ManualReviewCase, purchase: Purchase, subscription: ExternalSubscription | None
) -> bool:
    if (
        subscription is None
        or case.reason_code not in {"subscription_identity_conflict", "subscription_commercial_mismatch"}
        or (case.scope_kind, case.scope_reference) != ("subscription", str(subscription.subscription_id))
        or case.evidence_schema_version != "subscription-reconciliation:v1"
        or not isinstance(case.evidence_document, dict)
    ):
        return False
    try:
        identity = UUID(case.evidence_document["observation_id"])
    except (KeyError, ValueError, TypeError):
        return False
    observation = db.get(BillingStateObservation, identity)
    return bool(
        observation is not None
        and observation.subscription_id == subscription.subscription_id
        and observation.evidence_document.get("provenance", {}).get("purchase_intent_id") == str(purchase.id)
    )


def validate_case(
    db: Session,
    request: ResolutionRequest,
    purchase: Purchase,
    subscription: ExternalSubscription | None,
    operations: list[ExternalCreateOperation],
) -> tuple[ManualReviewCase, list[ManualReviewCase]]:
    case = queries.review(db, request.case_id, lock=True)
    cases = queries.reviews(
        db,
        purchase.id,
        purchase.customer_id,
        subscription.subscription_id if subscription else None,
        open_only=True,
        lock=True,
    )
    if case is None or len(cases) > 100 or not any(item.review_case_id == request.case_id for item in cases):
        raise PurchaseRefused("billing_review_unrelated_cases", 409)
    if case.case_state != "open" or case_digest(case) != request.expected_case_digest:
        raise PurchaseRefused("billing_review_stale", 409)
    if case.reason_code not in (RESTORABLE if request.resolution == "restore-original" else BINDABLE):
        raise PurchaseRefused("billing_review_resolution_unsupported", 409)
    if request.resolution == "bind-original" and (case.scope_kind, case.scope_reference) != (
        "create_operation",
        str(request.operation_id),
    ):
        raise PurchaseRefused("billing_review_stale", 409)
    if case.reason_code == "customer_inventory_conflict" and not inventory_case(case, purchase, operations):
        raise PurchaseRefused("billing_review_resolution_unsupported", 409)
    related = [item for item in cases if item.review_case_id != case.review_case_id]
    target = next((op for op in operations if op.create_operation_id == request.operation_id), None)
    for previous in related:
        if inventory_case(previous, purchase, operations) or (
            request.resolution == "restore-original" and canonical_case(db, previous, purchase, subscription)
        ):
            continue
        evidence = previous.evidence_document
        if (
            request.resolution != "bind-original"
            or target is None
            or (previous.scope_kind, previous.scope_reference) != (case.scope_kind, case.scope_reference)
            or previous.reason_code != "external_create_outcome_unknown:" + target.operation_kind.value
            or previous.evidence_schema_version != "financial-review:v1"
            or not isinstance(evidence, dict)
            or evidence.get("purchase_intent_id") != str(purchase.id)
            or evidence.get("create_operation_id") != str(target.create_operation_id)
            or not possible_send_case(previous)
        ):
            raise PurchaseRefused("billing_review_unrelated_cases", 409)
    return case, related
