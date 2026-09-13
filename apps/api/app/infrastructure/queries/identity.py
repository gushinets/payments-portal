from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import AuthSession, User


def get_auth_session_by_token_hash(db: Session, token_hash: str) -> AuthSession | None:
    return db.query(AuthSession).filter(AuthSession.token_hash == token_hash).first()


def get_user_for_auth_session(db: Session, auth_session: AuthSession) -> User | None:
    return (
        db.query(User)
        .filter(
            User.id == auth_session.user_id,
            User.tenant_id == auth_session.tenant_id,
            User.region == auth_session.region,
        )
        .first()
    )


def get_user_by_normalized_email(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    email_normalized: str,
) -> User | None:
    return (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.region == region,
            User.email_normalized == email_normalized,
        )
        .first()
    )


def lock_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.query(User).filter(User.id == user_id).with_for_update().first()
