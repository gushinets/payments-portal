"""Supported conflicts covered by one original-subscription inventory proof."""

from uuid import UUID

from app.domains.billing.reconciliation_contracts import RECONCILIATION_SCHEMA
from app.domains.purchases.contracts import Purchase
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State, ManualReviewCase

INVENTORY_CONFLICT = "customer_inventory_conflict"
FINANCIAL_CONFLICTS = {INVENTORY_CONFLICT, "financial_binding_conflict", "accepted_terms_changed_after_preparation"}
SUBSCRIPTION_CONFLICTS = {"subscription_identity_conflict", "subscription_commercial_mismatch"}


def financial_case(case: ManualReviewCase, purchase_id: UUID, operation_id: UUID) -> bool:
    evidence = case.evidence_document
    return (
        case.scope_kind == "create_operation"
        and case.scope_reference == str(operation_id)
        and case.evidence_schema_version == "financial-review:v1"
        and isinstance(evidence, dict)
        and evidence.get("purchase_intent_id") == str(purchase_id)
        and evidence.get("create_operation_id") == str(operation_id)
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
    operation = next((op for op in purchase.operations if str(op.id) == case.scope_reference), None)
    if operation is None or not financial_case(case, purchase.id, operation.id):
        return False
    if possible_send_case(case):
        return True
    # An earlier case on the SAME operation may retain the possible-send before
    # review rotated its fence. Transaction timestamps do not establish causality.
    return case.evidence_document.get("operation_state_at_conflict") == State.MANUAL_REVIEW.value and any(
        financial_case(previous, purchase.id, operation.id) and possible_send_case(previous) for previous in related
    )


def inventory_group(
    cases: list[ManualReviewCase], purchase: Purchase, subscription_id: UUID | None, *, operation_id: UUID | None = None
) -> bool:
    """Never group customer, other-operation, terminal-revival or unknown reasons.

    Bound restoration proves the canonical subscription. Unbound binding proves
    only its original possible-send operation. Both additionally require complete
    fresh inventory; this predicate supplies no source proof or write permission.
    """
    if not any(case.reason_code == INVENTORY_CONFLICT for case in cases):
        return False
    operation = next((op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION), None)
    if operation is None or (operation_id is not None and operation.id != operation_id):
        return False
    for case in cases:
        if financial_case(case, purchase.id, operation.id):
            if case.reason_code in FINANCIAL_CONFLICTS:
                continue
            if (
                subscription_id is None
                and case.reason_code == "external_create_outcome_unknown:subscription"
                and possible_send_case(case)
            ):
                continue
        elif (
            subscription_id is not None
            and case.scope_kind == "subscription"
            and case.scope_reference == str(subscription_id)
            and case.reason_code in SUBSCRIPTION_CONFLICTS
            and case.evidence_schema_version == RECONCILIATION_SCHEMA
            and isinstance(case.evidence_document, dict)
        ):
            continue
        return False
    return True
