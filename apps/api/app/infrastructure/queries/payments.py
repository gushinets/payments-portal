from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Payment, PaymentProviderAccount, Refund


def get_payment_by_id(db: Session, payment_id: uuid.UUID, *, for_update: bool = False) -> Payment | None:
    query = db.query(Payment).filter(Payment.id == payment_id)
    return (query.with_for_update() if for_update else query).first()


def get_payment_for_refund(db: Session, payment_id: uuid.UUID) -> Payment | None:
    return get_payment_by_id(db, payment_id, for_update=True)


def get_latest_payment_for_order(db: Session, order_id: uuid.UUID) -> Payment | None:
    return (
        db.query(Payment)
        .filter(Payment.order_id == order_id)
        .order_by(Payment.created_at.desc())
        .first()
    )


def get_refund_by_id(db: Session, refund_id: uuid.UUID, *, for_update: bool = False) -> Refund | None:
    query = db.query(Refund).filter(Refund.id == refund_id)
    return (query.with_for_update() if for_update else query).first()


def get_provider_account_by_id(
    db: Session, provider_account_id: uuid.UUID, *, for_update: bool = False
) -> PaymentProviderAccount | None:
    query = db.query(PaymentProviderAccount).filter(PaymentProviderAccount.id == provider_account_id)
    return (query.with_for_update() if for_update else query).first()
