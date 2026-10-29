"""Typed operator expectations built from the public local diagnostic shape."""

from uuid import UUID

from app.domains.billing.operator_contracts import ResolutionRequest
from app.domains.purchases.contracts import Purchase


def resolution_request(purchase: Purchase, evidence: dict, *, bind: bool = False) -> ResolutionRequest:
    case = next(case for case in evidence["reviews"] if case["state"] == "open")
    values = {
        "user_id": purchase.user_id,
        "purchase_id": purchase.id,
        "case_id": UUID(case["review_case_id"]),
        "expected_case_digest": case["expected_case_digest"],
        "resolution": "bind-original" if bind else "restore-original",
        "reason": "Original source facts verified",
        "reference": "ANY-715",
    }
    if bind:
        op = next(op for op in evidence["operations"] if op["create_operation_id"] == case["scope_reference"])
        values.update(operation_id=UUID(op["create_operation_id"]), expected_operation_fence=UUID(op["send_fence"]))
    else:
        sub = evidence["subscription"]
        values.update(
            expected_observation_id=UUID(sub["supporting_observation_id"]),
            expected_reconciliation_fence=sub["reconciliation_fence"],
        )
    return ResolutionRequest.model_validate(values)
