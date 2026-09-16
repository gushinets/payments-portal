from __future__ import annotations

import uuid
from collections.abc import Collection

from sqlalchemy.orm import Session

from app.models import Payment, PaymentProviderAccount, PaymentStatus, Refund


def get_payment_by_id(db: Session, payment_id: uuid.UUID, *, for_update: bool = False) -> Payment | None:
    query = db.query(Payment).filter(Payment.id == payment_id)
    return (query.with_for_update() if for_update else query).first()


def get_payment_for_refund(db: Session, payment_id: uuid.UUID) -> Payment | None:
    return get_payment_by_id(db, payment_id, for_update=True)


def get_latest_payment_for_order(db: Session, order_id: uuid.UUID) -> Payment | None:
    return db.query(Payment).filter(Payment.order_id == order_id).order_by(Payment.created_at.desc()).first()


def get_payment_by_provider_identity(
    db: Session,
    *,
    provider_account_id: uuid.UUID,
    provider_payment_id: str,
    for_update: bool = False,
) -> Payment | None:
    query = db.query(Payment).filter(
        Payment.provider_account_id == provider_account_id,
        Payment.provider_payment_id == provider_payment_id,
    )
    return (query.with_for_update() if for_update else query).first()


def get_latest_payment_for_order_with_statuses(
    db: Session,
    *,
    order_id: uuid.UUID,
    statuses: Collection[PaymentStatus],
) -> Payment | None:
    return (
        db.query(Payment)
        .filter(
            Payment.order_id == order_id,
            Payment.status.in_(statuses),
        )
        .order_by(Payment.captured_at.desc(), Payment.created_at.desc())
        .first()
    )


def list_payments_for_order_with_statuses(
    db: Session,
    *,
    order_id: uuid.UUID,
    statuses: Collection[PaymentStatus],
) -> list[Payment]:
    return (
        db.query(Payment)
        .filter(
            Payment.order_id == order_id,
            Payment.status.in_(statuses),
        )
        .all()
    )


def get_refund_by_id(db: Session, refund_id: uuid.UUID, *, for_update: bool = False) -> Refund | None:
    query = db.query(Refund).filter(Refund.id == refund_id)
    return (query.with_for_update() if for_update else query).first()


def get_refund_by_provider_identity(
    db: Session,
    *,
    provider_account_id: uuid.UUID,
    provider_refund_id: str,
    for_update: bool = False,
) -> Refund | None:
    query = db.query(Refund).filter(
        Refund.provider_account_id == provider_account_id,
        Refund.provider_refund_id == provider_refund_id,
    )
    return (query.with_for_update() if for_update else query).first()


def get_provider_account_by_id(
    db: Session, provider_account_id: uuid.UUID, *, for_update: bool = False
) -> PaymentProviderAccount | None:
    query = db.query(PaymentProviderAccount).filter(PaymentProviderAccount.id == provider_account_id)
    return (query.with_for_update() if for_update else query).first()
