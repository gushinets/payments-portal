"""Committed potential-send claims and fenced bindings; no provider HTTP/worker."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.infrastructure.persistence.purchase_scopes import lock_purchase_scope
from app.models import (
    BillingPurchaseScopeHold,
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationState,
    PurchaseIntent,
    PurchaseScopeHoldState,
)


@dataclass(frozen=True)
class ExternalCreateClaim:
    create_operation_id: UUID
    send_fencing_token: int
    scope_ownership_epoch: int | None


def _lock_operation(db: Session, operation_id: UUID) -> tuple[ExternalCreateOperation, BillingPurchaseScopeHold | None]:
    operation = db.get(ExternalCreateOperation, operation_id)
    if operation is None:
        raise ValueError("external create operation not found")
    hold = None
    if operation.purchase_intent_id is not None:
        purchase = db.get(PurchaseIntent, operation.purchase_intent_id)
        if purchase is None:
            raise ValueError("external create purchase not found")
        hold = lock_purchase_scope(db, purchase.user_id, purchase.product_id)
        if (
            hold is None
            or hold.hold_state != PurchaseScopeHoldState.HELD
            or hold.purchase_intent_id != purchase.purchase_intent_id
            or hold.external_billing_account_id != operation.external_billing_account_id
        ):
            raise ValueError("external create does not own held purchase scope")
    # Scope -> customer -> operation is the common lock order. A customer create
    # is shared across products and serializes on its customer slot alone.
    db.execute(
        select(ExternalBillingCustomer)
        .where(
            ExternalBillingCustomer.customer_id == operation.customer_id,
        )
        .with_for_update()
    )
    operation = db.scalars(
        select(ExternalCreateOperation)
        .where(
            ExternalCreateOperation.create_operation_id == operation_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
    return operation, hold


def claim_external_create(
    db: Session,
    operation_id: UUID,
    *,
    now: datetime,
) -> ExternalCreateClaim | None:
    """Prepare a send claim, clock and due item in the caller-owned transaction.

    Application must commit before using the returned claim for I/O.
    A crash immediately after that commit is UNKNOWN even if no packet left the process.
    No caller may POST if this returns None or commit raised/was uncertain.
    """
    if now.utcoffset() is None:
        raise ValueError("aware send claim timestamp required")
    operation, hold = _lock_operation(db, operation_id)
    if operation.operation_state != ExternalCreateOperationState.UNSENT or operation.resolved_at is not None:
        return None
    operation.operation_state = ExternalCreateOperationState.POSSIBLE_SEND
    operation.send_fencing_token += 1
    operation.scope_ownership_epoch = hold.ownership_epoch if hold else None
    operation.unknown_since = now
    operation.unknown_recovery_deadline_at = now + timedelta(hours=2)
    operation.updated_at = now
    db.add(
        BillingWorkItem(
            work_kind="external_create_recovery",
            scope_kind="external_create_operation",
            scope_reference=str(operation_id),
            coalescing_key=f"external-create:{operation_id}",
            payload_schema_version="v1",
            payload_document={"create_operation_id": str(operation_id)},
            next_attempt_at=operation.unknown_recovery_deadline_at,
            work_state="pending",
        )
    )
    db.flush()
    return ExternalCreateClaim(operation_id, operation.send_fencing_token, operation.scope_ownership_epoch)


def bind_external_create(
    db: Session,
    claim: ExternalCreateClaim,
    *,
    verified_external_object_id: str,
    now: datetime,
) -> bool:
    """Persist an Integration-verified binding, rejecting stale/late responses.

    Ownership/material readback is the caller's responsibility. Unique provider-ID
    constraints apply before subsequent CREATE, including pre-subscription agreements.
    """
    if not verified_external_object_id.strip() or now.utcoffset() is None:
        raise ValueError("verified binding and aware timestamp required")
    try:
        operation, hold = _lock_operation(db, claim.create_operation_id)
    except ValueError:
        return False
    if (
        operation.send_fencing_token != claim.send_fencing_token
        or operation.scope_ownership_epoch != claim.scope_ownership_epoch
        or (hold is not None and hold.ownership_epoch != claim.scope_ownership_epoch)
        or operation.operation_state
        not in (ExternalCreateOperationState.POSSIBLE_SEND, ExternalCreateOperationState.UNKNOWN)
    ):
        return False
    operation.bound_external_object_id = verified_external_object_id
    operation.operation_state = ExternalCreateOperationState.BOUND
    operation.resolved_at = now
    operation.updated_at = now
    item = db.scalar(
        select(BillingWorkItem)
        .where(
            BillingWorkItem.work_kind == "external_create_recovery",
            BillingWorkItem.coalescing_key == f"external-create:{claim.create_operation_id}",
        )
        .with_for_update()
    )
    if item is not None:
        item.work_state = "completed"
        item.lease_owner = None
        item.lease_expires_at = None
    db.flush()
    return True
