"""Bounded enrollment and subject reads for recovery and customer inventory."""

from uuid import UUID

from sqlalchemy import Text, exists, func, or_, select
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.models import (
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationState as State,
    PurchaseIntent,
    User,
)


def operation_subject(db: Session, identity: UUID) -> tuple[ExternalCreateOperation, ExternalBillingCustomer] | None:
    return db.execute(
        select(ExternalCreateOperation, ExternalBillingCustomer)
        .join(ExternalBillingCustomer, ExternalBillingCustomer.customer_id == ExternalCreateOperation.customer_id)
        .where(ExternalCreateOperation.create_operation_id == identity)
    ).first()


def missing_operations(db: Session, configuration: Settings) -> list[ExternalCreateOperation]:
    op = ExternalCreateOperation
    customer = ExternalBillingCustomer
    account = configuration.lbx_external_billing_account_id
    recovery = exists().where(
        BillingWorkItem.work_kind == "external_create_recovery",
        BillingWorkItem.coalescing_key == func.cast(op.create_operation_id, Text),
        BillingWorkItem.work_state.in_(("pending", "running", "invalid")),
        # Legacy recovery was due only at escalation. Repair its schedule once.
        BillingWorkItem.priority > 0,
    )
    deadline = exists().where(
        BillingWorkItem.work_kind == "external_create_deadline",
        BillingWorkItem.coalescing_key == account + ":" + func.cast(op.create_operation_id, Text),
    )
    return list(
        db.scalars(
            select(op)
            .join(customer, customer.customer_id == op.customer_id)
            .join(User, User.id == customer.user_id)
            .where(
                customer.external_billing_account_id == account,
                User.tenant_id == configuration.instance_tenant_id,
                User.region == configuration.instance_region,
                op.operation_state.in_((State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW)),
                op.unknown_since.is_not(None),
                op.unknown_recovery_deadline_at.is_not(None),
                or_(~recovery, ~deadline),
            )
            .order_by(op.create_operation_id)
            .limit(configuration.billing_worker_scan_batch_size)
        )
    )


def missing_inventory(db: Session, configuration: Settings) -> list[ExternalBillingCustomer]:
    customer = ExternalBillingCustomer
    enrolled = exists().where(
        BillingWorkItem.work_kind == "customer_inventory",
        BillingWorkItem.coalescing_key
        == configuration.lbx_external_billing_account_id + ":" + func.cast(customer.customer_id, Text),
        BillingWorkItem.work_state.in_(("pending", "running", "invalid")),
    )
    return list(
        db.scalars(
            select(customer)
            .join(User, User.id == customer.user_id)
            .where(
                customer.external_billing_account_id == configuration.lbx_external_billing_account_id,
                customer.provider_customer_id.is_not(None),
                User.tenant_id == configuration.instance_tenant_id,
                User.region == configuration.instance_region,
                ~enrolled,
            )
            .order_by(customer.customer_id)
            .limit(configuration.billing_worker_scan_batch_size)
        )
    )


def customer(db: Session, identity: UUID) -> ExternalBillingCustomer | None:
    return db.get(ExternalBillingCustomer, identity)


def customer_purchases(db: Session, identity: UUID) -> list[PurchaseIntent]:
    from app.models import BillingPurchaseScopeHold

    return list(
        db.scalars(
            select(PurchaseIntent)
            .join(
                BillingPurchaseScopeHold,
                BillingPurchaseScopeHold.purchase_intent_id == PurchaseIntent.purchase_intent_id,
            )
            .where(PurchaseIntent.customer_id == identity)
            .order_by(PurchaseIntent.purchase_intent_id)
            .limit(100)
        )
    )
