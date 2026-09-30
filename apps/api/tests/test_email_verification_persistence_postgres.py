from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.infrastructure.persistence.email_verification import (
    claim_valid_email_verification_token,
    invalidate_outstanding_email_verification_tokens,
)
from app.models import MagicLinkPurpose, MagicLinkToken, User, UserStatus


pytestmark = pytest.mark.postgres


def _create_unverified_user(db_session: Session) -> User:
    user = User(
        tenant_id="anytoolai",
        region="ru",
        email="verification@example.com",
        email_normalized="verification@example.com",
        password_hash="password-hash",
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    db_session.flush()
    return user


def test_email_verification_claim_is_conditional_and_single_use(db_session: Session) -> None:
    user = _create_unverified_user(db_session)
    now = datetime(2026, 9, 30, 14, 0, tzinfo=UTC)
    token_hash = hashlib.sha256(b"verification-token").hexdigest()
    db_session.add(
        MagicLinkToken(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            email_normalized=user.email_normalized,
            token_hash=token_hash,
            purpose=MagicLinkPurpose.EMAIL_VERIFICATION,
            expires_at=now + timedelta(hours=24),
        )
    )
    db_session.commit()

    assert (
        claim_valid_email_verification_token(
            db_session,
            token_hash=token_hash,
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            now=now,
        )
        == 1
    )
    assert (
        claim_valid_email_verification_token(
            db_session,
            token_hash=token_hash,
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            now=now,
        )
        == 0
    )


def test_email_verification_invalidation_is_scoped_to_user_and_purpose(db_session: Session) -> None:
    user = _create_unverified_user(db_session)
    now = datetime(2026, 9, 30, 15, 0, tzinfo=UTC)
    verification = MagicLinkToken(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        email_normalized=user.email_normalized,
        token_hash=hashlib.sha256(b"email-verification-token").hexdigest(),
        purpose=MagicLinkPurpose.EMAIL_VERIFICATION,
        expires_at=now + timedelta(hours=24),
    )
    password_reset = MagicLinkToken(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        email_normalized=user.email_normalized,
        token_hash=hashlib.sha256(b"password-reset-token").hexdigest(),
        purpose=MagicLinkPurpose.PASSWORD_RESET,
        expires_at=now + timedelta(minutes=30),
    )
    db_session.add_all([verification, password_reset])
    db_session.commit()

    assert (
        invalidate_outstanding_email_verification_tokens(
            db_session,
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            now=now,
        )
        == 1
    )
    db_session.expire_all()
    assert db_session.get(MagicLinkToken, verification.id).used_at == now
    assert db_session.get(MagicLinkToken, password_reset.id).used_at is None
