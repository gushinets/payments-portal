"""Delegation cleanup and storage failures; Application owns the transaction."""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from uuid import UUID

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.exc import OperationalError, TimeoutError
from sqlalchemy.orm import Session

from app.models import AuthSession, BackendSessionDelegation


def prune_expired_delegations(
    db: Session,
    *,
    user_id: UUID,
    tenant_id: str,
    region: str,
    consumer_id: str,
    now: datetime,
) -> None:
    """Caller holds User and parent locks; keep token-expiry evidence for valid parents."""
    parents = select(AuthSession.id).where(
        AuthSession.user_id == user_id,
        AuthSession.tenant_id == tenant_id,
        AuthSession.region == region,
    )
    invalid_parents = parents.where(or_(AuthSession.revoked_at.is_not(None), AuthSession.expires_at <= now))
    db.execute(
        delete(BackendSessionDelegation)
        .where(
            BackendSessionDelegation.consumer_id == consumer_id,
            BackendSessionDelegation.auth_session_id.in_(parents),
            or_(
                and_(
                    BackendSessionDelegation.exchanged_at.is_(None),
                    BackendSessionDelegation.code_expires_at <= now,
                ),
                BackendSessionDelegation.auth_session_id.in_(invalid_parents),
            ),
        )
        .execution_options(synchronize_session=False)
    )


class DelegationUnavailableError(Exception):
    pass


@contextmanager
def delegation_storage_errors() -> Iterator[None]:
    try:
        yield
    except (OperationalError, TimeoutError):
        raise DelegationUnavailableError() from None
