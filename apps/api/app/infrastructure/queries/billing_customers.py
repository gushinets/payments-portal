"""Focused customer-slot locking and permanent create identity queries."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models import (
    BillingWorkItem,
    CommercialProductHead,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationKind,
    ExternalCreateOperationState,
    ManualReviewCase,
    User,
)


CUSTOMER_LOCK_TIMEOUT_MS = 1000
CUSTOMER_STATEMENT_TIMEOUT_MS = 2000


def _bound_transaction(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text(
                "SELECT set_config('lock_timeout', :lock_timeout, true), set_config('statement_timeout', :statement_timeout, true)"
            ),
            {
                "lock_timeout": f"{CUSTOMER_LOCK_TIMEOUT_MS}ms",
                "statement_timeout": f"{CUSTOMER_STATEMENT_TIMEOUT_MS}ms",
            },
        )


def lock_user(db: Session, user_id: UUID) -> User:
    _bound_transaction(db)
    return db.scalars(
        select(User).where(User.id == user_id).with_for_update().execution_options(populate_existing=True)
    ).one()


def connection_accounts(db: Session, origin: str) -> set[str]:
    return set(
        db.scalars(
            select(CommercialProductHead.external_billing_account_id).where(
                CommercialProductHead.provider_origin == origin
            )
        )
    ) | set(
        db.scalars(
            select(ExternalBillingCustomer.external_billing_account_id).where(
                ExternalBillingCustomer.provider_origin == origin
            )
        )
    )


def customer_slot(db: Session, account_id: str, user_id: UUID) -> ExternalBillingCustomer | None:
    return db.scalar(
        select(ExternalBillingCustomer)
        .where(
            ExternalBillingCustomer.external_billing_account_id == account_id,
            ExternalBillingCustomer.user_id == user_id,
        )
        .with_for_update()
    )


def foreign_customer(db: Session, user_id: UUID, account_id: str) -> bool:
    return (
        db.scalar(
            select(ExternalBillingCustomer.customer_id)
            .outerjoin(
                ExternalCreateOperation, ExternalCreateOperation.customer_id == ExternalBillingCustomer.customer_id
            )
            .where(
                ExternalBillingCustomer.user_id == user_id,
                ExternalBillingCustomer.external_billing_account_id != account_id,
                ExternalBillingCustomer.provider_customer_id.is_not(None)
                | ExternalCreateOperation.unknown_since.is_not(None)
                | ExternalCreateOperation.bound_external_object_id.is_not(None),
            )
            .limit(1)
        )
        is not None
    )


def customer_operation(db: Session, customer_id: UUID) -> ExternalCreateOperation | None:
    return db.scalar(
        select(ExternalCreateOperation)
        .where(
            ExternalCreateOperation.customer_id == customer_id,
            ExternalCreateOperation.operation_kind == ExternalCreateOperationKind.CUSTOMER,
        )
        .with_for_update()
    )


def recovery_work(db: Session, operation_id: UUID) -> BillingWorkItem | None:
    return db.scalar(
        select(BillingWorkItem).where(
            BillingWorkItem.work_kind == "external_create_recovery", BillingWorkItem.coalescing_key == str(operation_id)
        )
    )


def overdue_customer_ids(db: Session, now: datetime, limit: int) -> tuple[UUID, ...]:
    return tuple(
        db.scalars(
            select(ExternalCreateOperation.customer_id)
            .where(
                ExternalCreateOperation.operation_kind == ExternalCreateOperationKind.CUSTOMER,
                ExternalCreateOperation.operation_state.in_(
                    [ExternalCreateOperationState.POSSIBLE_SEND, ExternalCreateOperationState.UNKNOWN]
                ),
                ExternalCreateOperation.unknown_recovery_deadline_at <= now,
            )
            .order_by(ExternalCreateOperation.unknown_recovery_deadline_at)
            .limit(limit)
        )
    )


def lock_customer(db: Session, customer_id: UUID) -> ExternalBillingCustomer:
    _bound_transaction(db)
    return db.scalars(
        select(ExternalBillingCustomer).where(ExternalBillingCustomer.customer_id == customer_id).with_for_update()
    ).one()


def open_customer_reviews(db: Session, operation_id: UUID) -> list[ManualReviewCase]:
    return list(
        db.scalars(
            select(ManualReviewCase).where(
                ManualReviewCase.scope_kind == "create_operation",
                ManualReviewCase.scope_reference == str(operation_id),
                ManualReviewCase.case_state == "open",
            )
        )
    )
