"""Delegation cleanup and storage failures; Application owns the transaction."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import and_, delete, or_, select, tuple_
from sqlalchemy.exc import OperationalError, TimeoutError
from sqlalchemy.orm import Session

from app.models import AuthSession, BackendSessionDelegation, BackendCodeIssuanceBudget, User


def prune_delegation_batch(db: Session, *, tenant_id: str, region: str, now: datetime, limit: int) -> bool:
    """Bound candidate rows, lock User → parent → credential, then recheck eligibility."""
    expired = or_(
        and_(BackendSessionDelegation.exchanged_at.is_(None), BackendSessionDelegation.code_expires_at <= now),
        AuthSession.revoked_at.is_not(None),
        AuthSession.expires_at <= now,
    )
    candidates = list(
        db.execute(
            select(BackendSessionDelegation.id, AuthSession.id, AuthSession.user_id)
            .join(AuthSession, AuthSession.id == BackendSessionDelegation.auth_session_id)
            .where(AuthSession.tenant_id == tenant_id, AuthSession.region == region, expired)
            .order_by(BackendSessionDelegation.id)
            .limit(limit)
        )
    )
    budgets = list(
        db.execute(
            select(BackendCodeIssuanceBudget.user_id, BackendCodeIssuanceBudget.consumer_id)
            .where(
                BackendCodeIssuanceBudget.tenant_id == tenant_id,
                BackendCodeIssuanceBudget.region == region,
                BackendCodeIssuanceBudget.window_expires_at <= now,
            )
            .order_by(BackendCodeIssuanceBudget.user_id, BackendCodeIssuanceBudget.consumer_id)
            .limit(limit)
        )
    )
    user_ids = {row[2] for row in candidates} | {row[0] for row in budgets}
    if user_ids:
        # Include inactive users and removed consumers; cleanup is not authorization.
        db.scalars(
            select(User)
            .where(User.id.in_(user_ids), User.tenant_id == tenant_id, User.region == region)
            .order_by(User.id)
            .with_for_update()
        ).all()
    if candidates:
        parent_ids = {row[1] for row in candidates}
        db.scalars(
            select(AuthSession).where(AuthSession.id.in_(parent_ids)).order_by(AuthSession.id).with_for_update()
        ).all()
        eligible = (
            select(BackendSessionDelegation.id)
            .join(AuthSession, AuthSession.id == BackendSessionDelegation.auth_session_id)
            .where(BackendSessionDelegation.id.in_([row[0] for row in candidates]), expired)
        )
        db.execute(
            delete(BackendSessionDelegation)
            .where(BackendSessionDelegation.id.in_(eligible))
            .execution_options(synchronize_session=False)
        )
    if budgets:
        db.execute(
            delete(BackendCodeIssuanceBudget)
            .where(
                BackendCodeIssuanceBudget.tenant_id == tenant_id,
                BackendCodeIssuanceBudget.region == region,
                tuple_(BackendCodeIssuanceBudget.user_id, BackendCodeIssuanceBudget.consumer_id).in_(budgets),
                BackendCodeIssuanceBudget.window_expires_at <= now,
            )
            .execution_options(synchronize_session=False)
        )
    return max(len(candidates), len(budgets)) == limit


class DelegationUnavailableError(Exception):
    pass


@contextmanager
def delegation_storage_errors() -> Iterator[None]:
    try:
        yield
    except (OperationalError, TimeoutError):
        raise DelegationUnavailableError() from None
