"""Focused storage mechanics for canonical commercial identity inserts."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.infrastructure.queries.payments import (
    get_payment_by_provider_identity,
    get_refund_by_provider_identity,
)
from app.models import Payment, Refund


_PAYMENT_IDENTITY_INDEX = "uq_payments_provider_account_payment_id"
_REFUND_IDENTITY_INDEX = "uq_refunds_provider_account_refund_id"


def _constraint_name(error: IntegrityError) -> str | None:
    return getattr(getattr(error.orig, "diag", None), "constraint_name", None)


def establish_payment_identity(db: Session, candidate: Payment) -> tuple[Payment, bool]:
    """Insert a Payment identity or return the row that won the expected race."""
    provider_payment_id = candidate.provider_payment_id
    if provider_payment_id is None:
        raise ValueError("payment_identity_required")
    try:
        with db.begin_nested():
            db.add(candidate)
            db.flush()
    except IntegrityError as exc:
        if _constraint_name(exc) != _PAYMENT_IDENTITY_INDEX:
            raise
        winner = get_payment_by_provider_identity(
            db,
            provider_account_id=candidate.provider_account_id,
            provider_payment_id=provider_payment_id,
        )
        if winner is None:
            raise
        return winner, False
    return candidate, True


def establish_refund_identity(db: Session, candidate: Refund) -> tuple[Refund, bool]:
    """Insert a Refund identity or return the row that won the expected race."""
    provider_refund_id = candidate.provider_refund_id
    if provider_refund_id is None:
        raise ValueError("refund_identity_required")
    try:
        with db.begin_nested():
            db.add(candidate)
            db.flush()
    except IntegrityError as exc:
        if _constraint_name(exc) != _REFUND_IDENTITY_INDEX:
            raise
        winner = get_refund_by_provider_identity(
            db,
            provider_account_id=candidate.provider_account_id,
            provider_refund_id=provider_refund_id,
        )
        if winner is None:
            raise
        return winner, False
    return candidate, True
