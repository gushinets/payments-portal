from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.identity.passwords import hash_password
from app.models import AuthSession, MagicLinkPurpose, MagicLinkToken, User, UserStatus


pytestmark = pytest.mark.postgres


def create_user(db_session: Session, *, email: str) -> User:
    user = User(
        tenant_id="anytoolai",
        region="ru",
        email=email,
        email_normalized=email,
        password_hash=hash_password("very-secret-password"),
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def test_auth_session_scope_must_match_canonical_user(db_session: Session) -> None:
    user = create_user(db_session, email="session-scope@example.com")
    db_session.add(
        AuthSession(
            tenant_id=user.tenant_id,
            region="eu",
            user_id=user.id,
            token_hash=hashlib.sha256(b"mismatched-session-token").hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_known_reset_token_scope_must_match_canonical_user(db_session: Session) -> None:
    user = create_user(db_session, email="reset-scope@example.com")
    db_session.add(
        MagicLinkToken(
            tenant_id=user.tenant_id,
            region="eu",
            user_id=user.id,
            email_normalized=user.email_normalized,
            token_hash=hashlib.sha256(b"mismatched-reset-token").hexdigest(),
            purpose=MagicLinkPurpose.PASSWORD_RESET,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_canonical_user_delete_is_restricted_by_auth_session(db_session: Session) -> None:
    user = create_user(db_session, email="retained-user@example.com")
    db_session.add(
        AuthSession(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            token_hash=hashlib.sha256(b"retained-session-token").hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    )
    db_session.commit()

    db_session.delete(user)
    with pytest.raises(IntegrityError):
        db_session.flush()
