"""Local versions and admission effects for the shared scoped inventory."""

from uuid import uuid4

from sqlalchemy.orm import Session

from app.domains.billing.customers import lock_customer
from app.domains.billing.customer_reviews import customer_admission_reviews
from app.domains.billing.paid_policy import CandidateConclusion
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase
from app.domains.purchases.inventory_contracts import InventoryResult, InventoryStale
from app.infrastructure.queries import purchases as queries
from app.infrastructure.queries.billing_customers import customer_operation
from app.models import (
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperationState as State,
)


def same_purchase(current: Purchase, expected: Purchase) -> bool:
    return (
        current.id == expected.id
        and current.accepted == expected.accepted
        and current.held == expected.held
        and current.state == expected.state
        and tuple(op.admission_snapshot() for op in current.operations)
        == tuple(op.admission_snapshot() for op in expected.operations)
    )


def validate_inventory_structure(db: Session, result: InventoryResult) -> tuple[Purchase, ...]:
    """Caller holds the existing user lock; never refresh the attempt's subject."""
    customer = lock_customer(db, result.customer.customer_id)
    operation = customer_operation(db, customer.customer_id)
    if operation is not None:
        customer_admission_reviews(db, customer, operation)
    if (
        customer.binding_state != Binding.BOUND
        or customer.provider_customer_id != result.customer.provider_id
        or customer.billing_customer_key != result.customer.outer_key
        or operation is None
        or operation.create_operation_id != result.customer.operation_id
        or operation.send_fence != result.customer.fence
        or operation.operation_state != State.BOUND
        or operation.bound_external_object_id != result.customer.provider_id
    ):
        raise InventoryStale()
    # Also reject new held purchases introduced during the source reads.
    from app.infrastructure.queries.billing_background import customer_purchases

    rows = customer_purchases(db, customer.customer_id)
    if {row.purchase_intent_id for row in rows} != {item.id for item in result.purchases}:
        raise InventoryStale()
    current = []
    for expected in result.purchases:
        row = service._locked(db, expected)
        queries.operations(db, expected.id, lock=True)
        snapshot = service._snapshot(db, row)
        if (
            snapshot.accepted != expected.accepted
            or snapshot.held != expected.held
            or {(op.id, op.kind, op.key, op.bound_id, op.candidate_id, op.deadline) for op in snapshot.operations}
            != {(op.id, op.kind, op.key, op.bound_id, op.candidate_id, op.deadline) for op in expected.operations}
        ):
            raise InventoryStale()
        service._verify_original_consent(db, row, expected.accepted)
        current.append(snapshot)
    return tuple(current)


def validate_inventory(db: Session, result: InventoryResult) -> None:
    """Strict customer-wide admission and restore-original validation."""
    from app.domains.billing.inventory_history import verify_inventory_point_history
    from app.domains.billing.reconciliation_validation import source_receipt_current

    current = validate_inventory_structure(db, result)
    if any(not same_purchase(now, old) for now, old in zip(current, result.purchases, strict=True)):
        raise InventoryStale()
    for source in result.sources:
        sub = queries.linked_subscription(db, source.purchase.id)
        if sub is None or not source_receipt_current(db, source, sub, require_latest=source.proof.complete):
            raise InventoryStale()
    verify_inventory_point_history(db, result)


def validate_inventory_product(
    db: Session, result: InventoryResult, product_id: str, *, current: tuple[Purchase, ...] | None = None
) -> None:
    """Validate only mutable facts supporting this product, with strict own operations."""
    from app.domains.billing.inventory_history import verify_inventory_point_history
    from app.infrastructure.queries import billing_reconciliation

    current = validate_inventory_structure(db, result) if current is None else current
    product = next((item for item in result.products if item.product_id == product_id), None)
    if product is None:
        raise InventoryStale()
    scope = billing_reconciliation.scope(db, result.purchases[0].user_id, product_id)
    if ((scope.primary_subscription_id, scope.primary_retired_at) if scope else (None, None)) != (
        product.primary_subscription_id,
        product.primary_retired_at,
    ):
        raise InventoryStale()
    relevant = {item.id for item in result.purchases if item.accepted.selection.product_id == product_id}
    relevant.update(
        item.purchase_id
        for item in product.candidates
        if item.purchase_id is not None and item.conclusion != CandidateConclusion.INELIGIBLE
    )
    # A conclusive permanent sibling may share a tariff without participating
    # in this decision. Its relationship changes are still checked below;
    # unrelated local review must not become a dependency again.
    if any(
        old.id in relevant and not same_purchase(now, old) for now, old in zip(current, result.purchases, strict=True)
    ):
        raise InventoryStale()
    verify_inventory_point_history(db, result, product_id=product_id)


def invalidate_unsent(db: Session, purchase: Purchase) -> bool:
    """Invalidate admission without changing no-send evidence or creating review."""
    operations = queries.operations(db, purchase.id, lock=True)
    changed = False
    for operation in operations:
        if operation.bound_external_object_id is None and operation.operation_state in {
            State.PENDING,
            State.PROVEN_NOT_SENT,
        }:
            operation.send_fence = uuid4()
            changed = True
    return changed


def block_admission(factory: SessionFactory, result: InventoryResult, purchase: Purchase) -> None:
    with factory() as db:
        service._locked(db, purchase)
        validate_inventory(db, result)
        if invalidate_unsent(db, purchase):
            from app.core.time import utc_now
            from app.models import PurchaseIntentState

            row = service._locked(db, purchase)
            row.state = PurchaseIntentState.AWAITING_EXTERNAL_RESULT
            row.state_updated_at = utc_now()
        db.commit()
