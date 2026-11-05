"""Local witnesses for proof-based inventory review; caller owns apply locks."""

from uuid import UUID
from datetime import timedelta

from sqlalchemy.orm import Session

from app.domains.billing.operator_contracts import InventoryPurchase, ReviewResolution
from app.domains.billing.inventory_readback import apply_findings
from app.domains.billing.operator_case_groups import INVENTORY_CONFLICT, inventory_group, original_possible_send
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseRefused
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from app.infrastructure.queries import billing_background, billing_operator, billing_reconciliation, purchases


def lock_inventory(db: Session, resolution: ReviewResolution) -> None:
    if resolution.inventory is None:
        return
    for item in sorted(
        resolution.inventory.purchases,
        key=lambda item: (item.purchase.accepted.selection.product_id, str(item.purchase.id)),
    ):
        purchase = item.purchase
        service._locked(db, purchase)
        purchases.operations(db, purchase.id, lock=True)
        billing_reconciliation.scope(db, purchase.user_id, purchase.accepted.selection.product_id)
        purchases.linked_subscription(db, purchase.id)


def snapshot(db: Session, customer_id: UUID) -> tuple[InventoryPurchase, ...]:
    from app.domains.billing.operator_review import case_digest

    rows = billing_background.customer_purchases(db, customer_id)
    if len(rows) >= 100:
        raise PurchaseRefused("purchase_inventory_incomplete", 409)
    result = []
    for row in rows:
        purchase = service._snapshot(db, row)
        service._verify_original_consent(db, row, purchase.accepted)
        sub = purchases.linked_subscription(db, purchase.id)
        cases = billing_operator.reviews(
            db, purchase.id, customer_id, sub.subscription_id if sub else None, open_only=True
        )
        if len(cases) > 100:
            raise PurchaseRefused("billing_review_unrelated_cases", 409)
        supported = inventory_group(cases, purchase, sub.subscription_id if sub else None)
        request = None
        for op in purchases.operations(db, purchase.id):
            case = next(
                (
                    c
                    for c in cases
                    if c.reason_code == INVENTORY_CONFLICT
                    and c.scope_kind == "create_operation"
                    and c.scope_reference == str(op.create_operation_id)
                ),
                None,
            )
            hint = op.recovery_hint_document
            if (
                op.operation_kind == Kind.SUBSCRIPTION
                and op.operation_state == State.MANUAL_REVIEW
                and op.bound_external_object_id is None
                and op.unknown_since is not None
                and op.recovery_hint_schema_version == "financial-create:v1"
                and case is not None
                and supported
                and original_possible_send(case, [c for c in cases if c is not case], purchase)
                and isinstance(hint, dict)
                and hint.get("purchase_intent_id") == str(purchase.id)
                and hint.get("accepted_fingerprint") == purchase.accepted.offer.fingerprint
                and isinstance(hint.get("request"), dict)
            ):
                request = hint["request"]
        result.append(
            InventoryPurchase(
                purchase, tuple((c.review_case_id, c.reason_code, case_digest(c)) for c in cases), request, supported
            )
        )
    return tuple(result)


def verify(db: Session, resolution: ReviewResolution) -> None:
    """No source I/O. The shared writer already holds this customer's user lock."""
    proof = resolution.inventory
    now = as_utc(billing_reconciliation.database_now(db))
    if (
        proof is None
        or proof.read_started_at < resolution.started_at
        or proof.read_started_at > proof.read_finished_at
        or proof.read_finished_at > now
        or proof.read_finished_at >= resolution.expires_at - timedelta(seconds=30)
    ):
        raise PurchaseRefused("billing_review_proof_incomplete", 409)
    if snapshot(db, resolution.purchase.customer_id) != proof.purchases:
        raise PurchaseRefused("billing_review_stale", 409)


def apply(db: Session, resolution: ReviewResolution) -> list[dict[str, str]]:
    proof = resolution.inventory
    if proof is None:
        return []
    if any(item.subject.purchase.id == resolution.purchase.id for item in proof.findings):
        raise PurchaseRefused("billing_review_stale", 409)
    return apply_findings(db, resolution.configuration, proof.findings)


def audit(resolution: ReviewResolution, outcomes: list[dict[str, str]]) -> dict:
    proof = resolution.inventory
    if proof is None:
        return {}
    return {
        "inventory_proof": {
            "schema": "review-inventory:v1",
            "read_started_at": proof.read_started_at.isoformat(),
            "read_finished_at": proof.read_finished_at.isoformat(),
            "membership_digest": proof.membership_digest,
            "candidate_count": proof.candidate_count,
            "scoped_outcomes": outcomes,
            "purchases": [
                {"purchase_intent_id": str(item.purchase.id), "review_digests": [d for _, _, d in item.reviews]}
                for item in proof.purchases
            ],
        }
    }
