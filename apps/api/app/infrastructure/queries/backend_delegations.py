"""Security writes always acquire User → AuthSession → delegation locks."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.models import AuthSession, BackendSessionDelegation, User


def read_delegation(
    db: Session,
    *,
    credential_hash: str,
    by_code: bool,
) -> tuple[BackendSessionDelegation, AuthSession, User] | None:
    field = BackendSessionDelegation.code_hash if by_code else BackendSessionDelegation.token_hash
    row = (
        db.query(BackendSessionDelegation, AuthSession, User)
        .join(AuthSession, AuthSession.id == BackendSessionDelegation.auth_session_id)
        .join(
            User,
            (User.id == AuthSession.user_id)
            & (User.tenant_id == AuthSession.tenant_id)
            & (User.region == AuthSession.region),
        )
        .filter(field == credential_hash)
        .populate_existing()
        .first()
    )
    return None if row is None else (row[0], row[1], row[2])


def lock_parent_session(db: Session, session_id: UUID) -> AuthSession | None:
    return db.query(AuthSession).filter(AuthSession.id == session_id).populate_existing().with_for_update().first()


def lock_delegation(db: Session, delegation_id: UUID) -> BackendSessionDelegation | None:
    return (
        db.query(BackendSessionDelegation)
        .filter(BackendSessionDelegation.id == delegation_id)
        .populate_existing()
        .with_for_update()
        .first()
    )
