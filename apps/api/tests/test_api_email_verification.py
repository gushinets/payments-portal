from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

import app.domains.identity.services.auth as auth_service
import app.domains.identity.services.email_verification as verification_service
from app.core.database import SessionLocal
from app.domains.identity.passwords import PBKDF2_ITERATIONS, password_hash_needs_rehash, verify_password
from app.models import (
    AuthenticationRateLimit,
    AuthSession,
    DocumentAcceptance,
    LegalAcceptanceEvent,
    MagicLinkPurpose,
    MagicLinkToken,
    User,
)
from apps.api.tests.support.api import client, reset_api_database


def setup_function() -> None:
    reset_api_database()


def _token_tuple(raw_token: str) -> tuple[str, str, datetime]:
    return (
        raw_token,
        hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        datetime.now(UTC) + timedelta(hours=24),
    )


def _legacy_password_hash(password: str) -> str:
    salt = "0123456789abcdef0123456789abcdef"
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def test_registration_requires_email_verification_before_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_token = "registration-verification-token-with-enough-entropy"
    delivered: list[tuple[str, str, str, int]] = []
    monkeypatch.setattr(auth_service, "make_email_verification_token", lambda: _token_tuple(raw_token))
    monkeypatch.setattr(
        verification_service,
        "send_email_verification_email",
        lambda email, url, route_locale, ttl_hours: delivered.append((email, url, route_locale, ttl_hours)) or True,
    )

    response = client.post(
        "/api/auth/register",
        json={
            "email": "new-user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
        headers={"accept-language": "pt-BR"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "verification_required"}
    assert len(delivered) == 1
    assert delivered[0][0] == "new-user@example.com"
    assert delivered[0][2:] == ("pt", verification_service.EMAIL_VERIFICATION_TTL_HOURS)
    assert "/pt/verify-email#token=" in delivered[0][1]

    with SessionLocal() as db:
        user = db.query(User).filter_by(email_normalized="new-user@example.com").one()
        verification_token = db.query(MagicLinkToken).one()
        assert user.email_verified_at is None
        assert user.last_login_at is None
        assert db.query(AuthSession).count() == 0
        assert db.query(LegalAcceptanceEvent).filter_by(user_id=user.id).count() == 1
        assert db.query(DocumentAcceptance).filter_by(user_id=user.id).count() == 3
        assert verification_token.purpose == MagicLinkPurpose.EMAIL_VERIFICATION
        assert verification_token.token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        assert verification_token.token_hash != raw_token

    login_response = client.post(
        "/api/auth/login",
        json={"email": "new-user@example.com", "password": "very-secret-password"},
    )
    assert login_response.status_code == 403
    assert login_response.json() == {"detail": {"code": "email_verification_required"}}
    with SessionLocal() as db:
        assert db.query(AuthSession).count() == 0

    wrong_password_response = client.post(
        "/api/auth/email-verification/confirm",
        json={"token": raw_token, "password": "wrong-password"},
    )
    assert wrong_password_response.status_code == 401
    with SessionLocal() as db:
        assert db.query(MagicLinkToken).one().used_at is None
        assert db.query(User).one().email_verified_at is None

    confirm_response = client.post(
        "/api/auth/email-verification/confirm",
        json={"token": raw_token, "password": "very-secret-password"},
    )
    assert confirm_response.status_code == 200
    payload = confirm_response.json()
    assert payload == {
        "status": "verified",
        "token": payload["token"],
        "user": {
            "tenant_id": "anytoolai",
            "region": "ru",
            "user_id": payload["user"]["user_id"],
            "email": "new-user@example.com",
        },
    }
    with SessionLocal() as db:
        user = db.query(User).one()
        assert user.email_verified_at is not None
        assert user.last_login_at is not None
        assert db.query(AuthSession).filter_by(user_id=user.id).count() == 1
        assert db.query(MagicLinkToken).one().used_at is not None


def test_duplicate_registration_is_generic_and_does_not_resend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivered: list[str] = []
    monkeypatch.setattr(
        verification_service,
        "send_email_verification_email",
        lambda email, url, route_locale, ttl_hours: delivered.append(email) or True,
    )
    payload = {
        "email": "duplicate@example.com",
        "password": "very-secret-password",
        "personal_consent": True,
        "offer_consent": True,
    }

    first = client.post("/api/auth/register", json=payload)
    second = client.post("/api/auth/register", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json() == second.json() == {"status": "verification_required"}
    assert delivered == ["duplicate@example.com"]
    with SessionLocal() as db:
        assert db.query(User).count() == 1
        assert db.query(MagicLinkToken).count() == 1


def test_resend_replaces_outstanding_token_and_remains_generic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_tokens = iter(
        (
            "first-verification-token-with-enough-entropy",
            "second-verification-token-with-enough-entropy",
        )
    )
    delivered: list[tuple[str, str]] = []
    monkeypatch.setattr(auth_service, "make_email_verification_token", lambda: _token_tuple(next(raw_tokens)))
    monkeypatch.setattr(
        verification_service,
        "send_email_verification_email",
        lambda email, url, route_locale, ttl_hours: delivered.append((email, route_locale)) or True,
    )

    registration = client.post(
        "/api/auth/register",
        json={
            "email": "resend@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    resend = client.post(
        "/api/auth/email-verification/request",
        json={"email": "resend@example.com"},
        headers={"accept-language": "de"},
    )
    unknown = client.post(
        "/api/auth/email-verification/request",
        json={"email": "missing@example.com"},
    )

    assert registration.json() == {"status": "verification_required"}
    assert resend.status_code == 200
    assert resend.json() == {"status": "accepted"}
    assert unknown.status_code == 200
    assert unknown.json() == {"status": "accepted"}
    assert delivered == [("resend@example.com", "ru"), ("resend@example.com", "de")]
    with SessionLocal() as db:
        first_token = (
            db.query(MagicLinkToken)
            .filter_by(token_hash=hashlib.sha256(b"first-verification-token-with-enough-entropy").hexdigest())
            .one()
        )
        second_token = (
            db.query(MagicLinkToken)
            .filter_by(token_hash=hashlib.sha256(b"second-verification-token-with-enough-entropy").hexdigest())
            .one()
        )
        assert db.query(MagicLinkToken).count() == 2
        assert first_token.used_at is not None
        assert second_token.used_at is None


def test_confirmation_rehashes_legacy_password_and_rejects_reuse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "very-secret-password"
    raw_token = "legacy-verification-token-with-enough-entropy"
    monkeypatch.setattr(auth_service, "make_email_verification_token", lambda: _token_tuple(raw_token))
    client.post(
        "/api/auth/register",
        json={
            "email": "legacy-verification@example.com",
            "password": password,
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    legacy_hash = _legacy_password_hash(password)
    with SessionLocal() as db:
        user = db.query(User).one()
        user.password_hash = legacy_hash
        db.commit()

    verified = client.post(
        "/api/auth/email-verification/confirm",
        json={"token": raw_token, "password": password},
    )
    reused = client.post(
        "/api/auth/email-verification/confirm",
        json={"token": raw_token, "password": password},
    )

    assert verified.status_code == 200
    assert reused.status_code == 400
    assert reused.json() == {"detail": {"code": "invalid_or_expired_verification_token"}}
    with SessionLocal() as db:
        password_hash = db.query(User).one().password_hash
        assert password_hash is not None
        assert password_hash != legacy_hash
        assert not password_hash_needs_rehash(password_hash)
        assert verify_password(password, password_hash)


def test_correct_unverified_login_rehashes_legacy_password_without_creating_session() -> None:
    password = "very-secret-password"
    legacy_hash = _legacy_password_hash(password)
    client.post(
        "/api/auth/register",
        json={
            "email": "legacy-unverified-login@example.com",
            "password": password,
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    with SessionLocal() as db:
        user = db.query(User).filter_by(email_normalized="legacy-unverified-login@example.com").one()
        user.password_hash = legacy_hash
        assert user.email_verified_at is None
        assert user.last_login_at is None
        db.commit()

    response = client.post(
        "/api/auth/login",
        json={"email": "legacy-unverified-login@example.com", "password": password},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": {"code": "email_verification_required"}}
    with SessionLocal() as db:
        user = db.query(User).filter_by(email_normalized="legacy-unverified-login@example.com").one()
        assert user.email_verified_at is None
        assert user.last_login_at is None
        assert db.query(AuthSession).filter_by(user_id=user.id).count() == 0
        assert user.password_hash is not None
        assert user.password_hash != legacy_hash
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(password, user.password_hash)
        assert not password_hash_needs_rehash(user.password_hash)


def test_registration_rate_limit_accounting_survives_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    delivered: list[str] = []
    monkeypatch.setattr(
        verification_service,
        "send_email_verification_email",
        lambda email, url, route_locale, ttl_hours: delivered.append(email) or True,
    )
    payload = {
        "email": "limited-registration@example.com",
        "password": "very-secret-password",
        "personal_consent": True,
        "offer_consent": True,
    }

    for _ in range(auth_service.REGISTRATION_ACCOUNT_RATE_LIMIT_MAX):
        assert client.post("/api/auth/register", json=payload).status_code == 200
    limited = client.post("/api/auth/register", json=payload)

    assert limited.status_code == 429
    assert limited.json() == {"detail": {"code": "authentication_rate_limited"}}
    assert delivered == ["limited-registration@example.com"]
    with SessionLocal() as db:
        stored = db.get(
            AuthenticationRateLimit,
            "registration:account:anytoolai:ru:limited-registration@example.com",
        )
        assert stored is not None
        assert stored.count == auth_service.REGISTRATION_ACCOUNT_RATE_LIMIT_MAX + 1


def test_correct_unverified_login_clears_failure_state_without_session() -> None:
    client.post(
        "/api/auth/register",
        json={
            "email": "unverified-login@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    invalid = client.post(
        "/api/auth/login",
        json={"email": "unverified-login@example.com", "password": "wrong-password-123"},
    )
    unverified = client.post(
        "/api/auth/login",
        json={"email": "unverified-login@example.com", "password": "very-secret-password"},
    )

    assert invalid.status_code == 401
    assert unverified.status_code == 403
    assert unverified.json() == {"detail": {"code": "email_verification_required"}}
    with SessionLocal() as db:
        assert db.query(AuthSession).count() == 0
        assert (
            db.get(
                AuthenticationRateLimit,
                "login:account:anytoolai:ru:unverified-login@example.com",
            )
            is None
        )


def test_login_cooldown_rejection_does_not_extend_failure_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client.post(
        "/api/auth/register",
        json={
            "email": "cooldown@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    current_time = datetime(2026, 9, 30, 16, 0, tzinfo=UTC)
    monkeypatch.setattr(auth_service, "utc_now", lambda: current_time)
    payload = {"email": "cooldown@example.com", "password": "wrong-password-123"}

    for _ in range(auth_service.LOGIN_ACCOUNT_COOLDOWN_START):
        response = client.post("/api/auth/login", json=payload)
        assert response.status_code == 401
        current_time += timedelta(milliseconds=100)

    limited = client.post("/api/auth/login", json=payload)
    assert limited.status_code == 429
    with SessionLocal() as db:
        state = db.get(
            AuthenticationRateLimit,
            "login:account:anytoolai:ru:cooldown@example.com",
        )
        assert state is not None
        assert state.count == auth_service.LOGIN_ACCOUNT_COOLDOWN_START
        updated_at = state.updated_at

    current_time += timedelta(seconds=1)
    accepted_failure = client.post("/api/auth/login", json=payload)
    assert accepted_failure.status_code == 401
    with SessionLocal() as db:
        state = db.get(
            AuthenticationRateLimit,
            "login:account:anytoolai:ru:cooldown@example.com",
        )
        assert state is not None
        assert state.count == auth_service.LOGIN_ACCOUNT_COOLDOWN_START + 1
        assert state.updated_at > updated_at


def test_unknown_login_runs_one_dummy_argon2_verification(monkeypatch: pytest.MonkeyPatch) -> None:
    verified_hashes: list[str] = []

    def capture_verify(_password: str, encoded: str) -> bool:
        verified_hashes.append(encoded)
        return False

    monkeypatch.setattr(auth_service, "verify_password", capture_verify)

    response = client.post(
        "/api/auth/login",
        json={"email": "unknown@example.com", "password": "wrong-password-123"},
    )

    assert response.status_code == 401
    assert verified_hashes == [auth_service.DUMMY_ARGON2_PASSWORD_HASH]


def test_wrong_legacy_password_also_runs_dummy_argon2_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    password = "very-secret-password"
    client.post(
        "/api/auth/register",
        json={
            "email": "legacy-wrong@example.com",
            "password": password,
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    legacy_hash = _legacy_password_hash(password)
    with SessionLocal() as db:
        user = db.query(User).filter_by(email_normalized="legacy-wrong@example.com").one()
        user.password_hash = legacy_hash
        db.commit()
    verified_hashes: list[str] = []

    def capture_verify(_password: str, encoded: str) -> bool:
        verified_hashes.append(encoded)
        return False

    monkeypatch.setattr(auth_service, "verify_password", capture_verify)

    response = client.post(
        "/api/auth/login",
        json={"email": "legacy-wrong@example.com", "password": "wrong-password-123"},
    )

    assert response.status_code == 401
    assert verified_hashes == [legacy_hash, auth_service.DUMMY_ARGON2_PASSWORD_HASH]
