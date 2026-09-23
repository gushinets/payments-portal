from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import AuthSession, MagicLinkPurpose, MagicLinkToken, User, UserStatus


def get_auth_session_by_token_hash(db: Session, token_hash: str) -> AuthSession | None:
    return db.query(AuthSession).filter(AuthSession.token_hash == token_hash).first()


def get_active_user_for_auth_session(db: Session, auth_session: AuthSession) -> User | None:
    return (
        db.query(User)
        .filter(
            User.id == auth_session.user_id,
            User.tenant_id == auth_session.tenant_id,
            User.region == auth_session.region,
            User.status == UserStatus.ACTIVE,
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


def get_active_user_by_normalized_email(
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
            User.status == UserStatus.ACTIVE,
        )
        .first()
    )


def get_active_user_by_id_and_scope(
    db: Session,
    *,
    user_id: uuid.UUID,
    tenant_id: str,
    region: str,
) -> User | None:
    return (
        db.query(User)
        .filter(
            User.id == user_id,
            User.tenant_id == tenant_id,
            User.region == region,
            User.status == UserStatus.ACTIVE,
        )
        .first()
    )


def get_magic_link_token_by_hash_and_purpose(
    db: Session,
    *,
    token_hash: str,
    purpose: MagicLinkPurpose,
) -> MagicLinkToken | None:
    return (
        db.query(MagicLinkToken)
        .filter(
            MagicLinkToken.token_hash == token_hash,
            MagicLinkToken.purpose == purpose,
        )
        .first()
    )


def lock_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.query(User).filter(User.id == user_id).with_for_update().first()
