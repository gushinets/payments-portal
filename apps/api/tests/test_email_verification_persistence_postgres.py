from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy.orm import Session, sessionmaker

import app.domains.identity.services.email_verification as email_verification_service
from app.domains.identity.errors import InvalidOrExpiredVerificationTokenError
from app.domains.identity.services.auth import register_user
from app.infrastructure.persistence.email_verification import (
    claim_valid_email_verification_token,
    get_email_verification_token,
)
from app.models import MagicLinkPurpose, MagicLinkToken, User


def test_verification_persistence_reads_and_claims_only_exact_scoped_valid_token(db_session: Session) -> None:
    raw_token = "postgres-verification-token-with-enough-entropy"
    registration = register_user(
        db_session,
        tenant_id="anytoolai",
        region="ru",
        email="verification-persistence@example.com",
        password="Persistence-pass1!",
        personal_consent=True,
        offer_consent=True,
        client_ip="192.0.2.20",
        user_agent="verification-persistence-test",
        route_locale="ru",
    )
    user_id = registration.authentication.user_id
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    now = datetime.now(UTC)
    db_session.add(
        MagicLinkToken(
            tenant_id="anytoolai",
            region="ru",
            user_id=user_id,
            email_normalized="verification-persistence@example.com",
            token_hash=token_hash,
            purpose=MagicLinkPurpose.EMAIL_VERIFICATION,
            expires_at=now + timedelta(hours=24),
        )
    )
    db_session.commit()

    assert (
        get_email_verification_token(
            db_session,
            token_hash=token_hash,
            tenant_id="anytoolai",
            region="ru",
        )
        is not None
    )
    assert (
        get_email_verification_token(
            db_session,
            token_hash=token_hash,
            tenant_id="other",
            region="ru",
        )
        is None
    )
    assert (
        claim_valid_email_verification_token(
            db_session,
            token_hash=token_hash,
            tenant_id="anytoolai",
            region="ru",
            user_id=user_id,
            now=now,
        )
        == 1
    )
    assert (
        claim_valid_email_verification_token(
            db_session,
            token_hash=token_hash,
            tenant_id="anytoolai",
            region="ru",
            user_id=user_id,
            now=now,
        )
        == 0
    )
    db_session.rollback()


def test_confirm_and_resend_race_serializes_on_user_lock(
    db_session: Session,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_token = "race-original-verification-token-with-enough-entropy"
    rotated_token = "race-rotated-verification-token-with-enough-entropy"
    monkeypatch.setattr(
        email_verification_service,
        "make_email_verification_token",
        lambda: (
            original_token,
            hashlib.sha256(original_token.encode("utf-8")).hexdigest(),
            datetime.now(UTC) + timedelta(hours=24),
        ),
    )
    registration = register_user(
        db_session,
        tenant_id="anytoolai",
        region="ru",
        email="verification-race@example.com",
        password="Concurrency-pass1!",
        personal_consent=True,
        offer_consent=True,
        client_ip="192.0.2.21",
        user_agent="verification-race-test",
        route_locale="ru",
    )
    user_id = registration.authentication.user_id
    stored = (
        db_session.query(MagicLinkToken).filter_by(token_hash=hashlib.sha256(original_token.encode()).hexdigest()).one()
    )
    stored.created_at = datetime.now(UTC) - timedelta(seconds=61)
    db_session.commit()
    monkeypatch.setattr(
        email_verification_service,
        "make_email_verification_token",
        lambda: (
            rotated_token,
            hashlib.sha256(rotated_token.encode("utf-8")).hexdigest(),
            datetime.now(UTC) + timedelta(hours=24),
        ),
    )
    start = Barrier(2)

    def confirm() -> str:
        with postgres_session_factory() as session:
            start.wait(timeout=10)
            authenticated_user = session.get(User, user_id)
            assert authenticated_user is not None
            try:
                email_verification_service.confirm_email_verification(
                    session,
                    token=original_token,
                    authenticated_user=authenticated_user,
                )
            except InvalidOrExpiredVerificationTokenError:
                return "invalidated"
            return "verified"

    def resend() -> str:
        with postgres_session_factory() as session:
            start.wait(timeout=10)
            delivery = email_verification_service.prepare_email_verification_resend(
                session,
                user_id=user_id,
                tenant_id="anytoolai",
                region="ru",
                route_locale="ru",
                client_ip="192.0.2.22",
                user_agent="verification-race-test",
            )
            return "rotated" if delivery is not None else "noop"

    with ThreadPoolExecutor(max_workers=2) as executor:
        confirm_future = executor.submit(confirm)
        resend_future = executor.submit(resend)
        outcomes = {confirm_future.result(timeout=20), resend_future.result(timeout=20)}

    db_session.expire_all()
    user = db_session.get(User, user_id)
    tokens = db_session.query(MagicLinkToken).filter_by(user_id=user_id).all()
    assert user is not None
    if user.email_verified_at is not None:
        assert outcomes == {"verified", "noop"}
        assert all(token.used_at is not None for token in tokens)
    else:
        assert outcomes == {"invalidated", "rotated"}
        outstanding = [token for token in tokens if token.used_at is None]
        assert len(outstanding) == 1
        assert outstanding[0].token_hash == hashlib.sha256(rotated_token.encode("utf-8")).hexdigest()
