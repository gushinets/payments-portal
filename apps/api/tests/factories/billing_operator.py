"""Typed operator expectations built from the public local diagnostic shape."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from app.core.settings import Settings
from app.domains.billing.operator_contracts import ResolutionRequest
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.terminal_resolution import (
    OperationEvidence,
    TerminalEvidence,
    TerminalEvidenceKind,
    TerminalRequest,
)
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


def terminal_request(
    factory: sessionmaker[Session],
    config: Settings,
    purchase: Purchase,
    *operations: OperationEvidence,
    confirmed: bool = False,
) -> TerminalRequest:
    now = datetime.now(UTC) if confirmed else None
    inspected = inspect_evidence(factory, config, purchase.user_id, purchase.id)
    return TerminalRequest(
        user_id=purchase.user_id,
        purchase_id=purchase.id,
        expected_digest=inspected["expected_resolution_digest"],
        reason="Customer requests a new attempt",
        reference="Synthetic provider confirmation for ANY-821",
        evidence=TerminalEvidence(
            senders_stopped_at=now,
            confirmed_at=now,
            operations=operations
            or tuple(
                OperationEvidence(operation_id=op.id, outcome=TerminalEvidenceKind.NOT_SENT)
                for op in purchase.operations
            ),
        ),
    )


def terminal_object_request(
    factory: sessionmaker[Session], config: Settings, purchase: Purchase, *, subscription_id: str
) -> TerminalRequest:
    return terminal_request(
        factory,
        config,
        purchase,
        *(
            OperationEvidence(
                operation_id=op.id,
                outcome=TerminalEvidenceKind.EXTERNAL_TERMINAL,
                external_object_id=op.bound_id or subscription_id,
            )
            for op in purchase.operations
        ),
        confirmed=True,
    )
