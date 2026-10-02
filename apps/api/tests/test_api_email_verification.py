from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit
from uuid import UUID

import pytest
from httpx import Response
from sqlalchemy.orm import Session

import app.domains.identity.services.email_verification as email_verification_service
from app.core.database import SessionLocal
from app.models import AuthSession, MagicLinkPurpose, MagicLinkToken, User
from apps.api.tests.support.api import client, reset_api_database


PASSWORD = "Original-pass1!"


def setup_function() -> None:
    reset_api_database()


def _install_token(monkeypatch: pytest.MonkeyPatch, raw_token: str) -> None:
    monkeypatch.setattr(
        email_verification_service,
        "make_email_verification_token",
        lambda: (
            raw_token,
            hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            datetime.now(UTC) + timedelta(hours=24),
        ),
    )


def _register(email: str, *, accept_language: str = "ru") -> Response:
    return client.post(
        "/api/auth/register",
        headers={"accept-language": accept_language},
        json={
            "email": email,
            "password": PASSWORD,
            "personal_consent": True,
            "offer_consent": True,
        },
    )


def test_registration_creates_hash_only_localized_verification_and_keeps_session_authenticated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_token = "registration-verification-token-with-enough-entropy"
    _install_token(monkeypatch, raw_token)
    deliveries: list[tuple[str, str, str, int]] = []
    monkeypatch.setattr(
        email_verification_service,
        "send_email_verification_email",
        lambda email, url, route_locale, ttl_hours: deliveries.append((email, url, route_locale, ttl_hours)) or True,
    )

    registration = _register("verification-registration@example.com", accept_language="pt-BR")

    assert registration.status_code == 200
    payload = registration.json()
    assert payload["user"]["email_verified"] is False
    assert len(deliveries) == 1
    recipient, verification_url, route_locale, ttl_hours = deliveries[0]
    assert recipient == "verification-registration@example.com"
    assert route_locale == "pt"
    assert ttl_hours == email_verification_service.EMAIL_VERIFICATION_TTL_HOURS
    assert urlsplit(verification_url).path == "/pt/verify-email"
    assert parse_qs(urlsplit(verification_url).fragment) == {"token": [raw_token]}

    with SessionLocal() as db:
        user = db.query(User).filter_by(email_normalized="verification-registration@example.com").one()
        stored_token = db.query(MagicLinkToken).one()
        assert user.email_verified_at is None
        assert stored_token.purpose == MagicLinkPurpose.EMAIL_VERIFICATION
        assert stored_token.user_id == user.id
        assert stored_token.token_hash == hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        assert raw_token not in stored_token.token_hash
        assert db.query(AuthSession).filter_by(user_id=user.id).count() == 1

    login = client.post(
        "/api/auth/login",
        json={"email": "verification-registration@example.com", "password": PASSWORD},
    )
    session = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {payload['token']}"},
    )
    assert login.status_code == 200
    assert login.json()["user"]["email_verified"] is False
    assert session.status_code == 200
    assert session.json()["user"]["email_verified"] is False


def test_duplicate_registration_schedules_no_second_verification_email(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_token(monkeypatch, "duplicate-registration-verification-token")
    deliveries: list[str] = []
    monkeypatch.setattr(
        email_verification_service,
        "send_email_verification_email",
        lambda email, url, route_locale, ttl_hours: deliveries.append(url) or True,
    )

    assert _register("duplicate-verification@example.com").status_code == 200
    duplicate = _register("duplicate-verification@example.com")

    assert duplicate.status_code == 409
    assert len(deliveries) == 1


def test_authenticated_confirmation_preserves_session_and_last_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_token = "confirm-verification-token-with-enough-entropy"
    _install_token(monkeypatch, raw_token)
    monkeypatch.setattr(email_verification_service, "send_email_verification_email", lambda *args: True)
    registration = _register("confirm-verification@example.com")
    auth_token = registration.json()["token"]
    with SessionLocal() as db:
        user = db.query(User).filter_by(email_normalized="confirm-verification@example.com").one()
        original_last_login_at = user.last_login_at
        original_sessions = {
            session.id: (session.token_hash, session.expires_at, session.revoked_at)
            for session in db.query(AuthSession).filter_by(user_id=user.id).all()
        }

    confirmed = client.post(
        "/api/auth/email-verification/confirm",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"token": raw_token},
    )

    assert confirmed.status_code == 200
    assert confirmed.json() == {"status": "verified"}
    with SessionLocal() as db:
        user = db.query(User).filter_by(email_normalized="confirm-verification@example.com").one()
        assert user.email_verified_at is not None
        assert user.last_login_at == original_last_login_at
        assert {
            session.id: (session.token_hash, session.expires_at, session.revoked_at)
            for session in db.query(AuthSession).filter_by(user_id=user.id).all()
        } == original_sessions
        assert db.query(MagicLinkToken).one().used_at is not None

    session = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {auth_token}"},
    )
    replay = client.post(
        "/api/auth/email-verification/confirm",
        headers={"Authorization": f"Bearer {auth_token}"},
        json={"token": raw_token},
    )
    assert session.status_code == 200
    assert session.json()["user"]["email_verified"] is True
    assert replay.status_code == 200
    assert replay.json() == {"status": "verified"}


def test_invalid_and_expired_verification_tokens_are_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_token = "expired-verification-token-with-enough-entropy"
    _install_token(monkeypatch, raw_token)
    monkeypatch.setattr(email_verification_service, "send_email_verification_email", lambda *args: True)
    registration = _register("expired-verification@example.com")
    assert registration.status_code == 200
    auth_header = {"Authorization": f"Bearer {registration.json()['token']}"}
    with SessionLocal() as db:
        stored_token = db.query(MagicLinkToken).one()
        stored_token.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    invalid = client.post(
        "/api/auth/email-verification/confirm",
        headers=auth_header,
        json={"token": "unknown-verification-token-with-enough-length"},
    )
    expired = client.post(
        "/api/auth/email-verification/confirm",
        headers=auth_header,
        json={"token": raw_token},
    )

    assert invalid.status_code == 400
    assert expired.status_code == 400
    assert invalid.json() == expired.json() == {"detail": {"code": "invalid_or_expired_verification_token"}}


def test_confirmation_requires_authenticated_bearer_session(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_token = "authenticated-confirmation-token-with-enough-entropy"
    _install_token(monkeypatch, raw_token)
    monkeypatch.setattr(email_verification_service, "send_email_verification_email", lambda *args: True)
    assert _register("authentication-required@example.com").status_code == 200

    response = client.post(
        "/api/auth/email-verification/confirm",
        json={"token": raw_token},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "missing_session"}
    with SessionLocal() as db:
        assert db.query(MagicLinkToken).one().used_at is None


def test_confirmation_rejects_token_owned_by_another_authenticated_user(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_token = "first-user-confirmation-token-with-enough-entropy"
    second_token = "second-user-confirmation-token-with-enough-entropy"
    monkeypatch.setattr(email_verification_service, "send_email_verification_email", lambda *args: True)
    _install_token(monkeypatch, first_token)
    first_registration = _register("first-confirmation-user@example.com")
    _install_token(monkeypatch, second_token)
    second_registration = _register("second-confirmation-user@example.com")

    response = client.post(
        "/api/auth/email-verification/confirm",
        headers={"Authorization": f"Bearer {second_registration.json()['token']}"},
        json={"token": first_token},
    )

    assert first_registration.status_code == 200
    assert second_registration.status_code == 200
    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "invalid_or_expired_verification_token"}}
    with SessionLocal() as db:
        users = db.query(User).order_by(User.email_normalized).all()
        assert all(user.email_verified_at is None for user in users)
        first_stored_token = (
            db.query(MagicLinkToken).filter_by(token_hash=hashlib.sha256(first_token.encode("utf-8")).hexdigest()).one()
        )
        assert first_stored_token.used_at is None


def test_confirmation_rejects_token_with_stale_email_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_token = "stale-email-confirmation-token-with-enough-entropy"
    _install_token(monkeypatch, raw_token)
    monkeypatch.setattr(email_verification_service, "send_email_verification_email", lambda *args: True)
    registration = _register("current-email@example.com")
    with SessionLocal() as db:
        stored_token = db.query(MagicLinkToken).one()
        stored_token.email_normalized = "old-email@example.com"
        db.commit()

    response = client.post(
        "/api/auth/email-verification/confirm",
        headers={"Authorization": f"Bearer {registration.json()['token']}"},
        json={"token": raw_token},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "invalid_or_expired_verification_token"}}
    with SessionLocal() as db:
        user = db.query(User).filter_by(email_normalized="current-email@example.com").one()
        assert user.email_verified_at is None
        assert db.query(MagicLinkToken).one().used_at is None


def test_confirmation_uses_expiry_time_obtained_after_user_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    raw_token = "post-lock-expiry-confirmation-token-with-enough-entropy"
    _install_token(monkeypatch, raw_token)
    monkeypatch.setattr(email_verification_service, "send_email_verification_email", lambda *args: True)
    registration = _register("post-lock-expiry@example.com")
    expires_at = datetime.now(UTC) + timedelta(minutes=1)
    with SessionLocal() as db:
        stored_token = db.query(MagicLinkToken).one()
        stored_token.expires_at = expires_at
        db.commit()

    original_lock = email_verification_service.lock_active_user_by_id_and_scope
    lock_acquired = False

    def lock_user(
        db: Session,
        *,
        user_id: UUID,
        tenant_id: str,
        region: str,
    ) -> User | None:
        nonlocal lock_acquired
        user = original_lock(
            db,
            user_id=user_id,
            tenant_id=tenant_id,
            region=region,
        )
        lock_acquired = True
        return user

    def post_lock_now() -> datetime:
        assert lock_acquired
        return expires_at + timedelta(seconds=1)

    monkeypatch.setattr(email_verification_service, "lock_active_user_by_id_and_scope", lock_user)
    monkeypatch.setattr(email_verification_service, "utc_now", post_lock_now)

    response = client.post(
        "/api/auth/email-verification/confirm",
        headers={"Authorization": f"Bearer {registration.json()['token']}"},
        json={"token": raw_token},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "invalid_or_expired_verification_token"}}


def test_authenticated_resend_obeys_cooldown_then_rotates_and_verified_user_is_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_token = "first-verification-token-with-enough-entropy"
    second_token = "second-verification-token-with-enough-entropy"
    _install_token(monkeypatch, first_token)
    deliveries: list[str] = []
    monkeypatch.setattr(
        email_verification_service,
        "send_email_verification_email",
        lambda email, url, route_locale, ttl_hours: deliveries.append(url) or True,
    )
    registration = _register("resend-verification@example.com", accept_language="de")
    auth_header = {"Authorization": f"Bearer {registration.json()['token']}"}

    cooldown = client.post(
        "/api/auth/email-verification/request",
        headers={**auth_header, "accept-language": "fr"},
        json={},
    )
    assert cooldown.status_code == 200
    assert cooldown.json() == {"status": "accepted"}
    assert len(deliveries) == 1

    with SessionLocal() as db:
        first = db.query(MagicLinkToken).one()
        user_id = first.user_id
        first.created_at = datetime.now(UTC) - timedelta(seconds=61)
        db.commit()
    _install_token(monkeypatch, second_token)

    rotated = client.post(
        "/api/auth/email-verification/request",
        headers={**auth_header, "accept-language": "fr"},
        json={},
    )

    assert rotated.status_code == 200
    assert len(deliveries) == 2
    assert urlsplit(deliveries[-1]).path == "/fr/verify-email"
    with SessionLocal() as db:
        tokens = db.query(MagicLinkToken).order_by(MagicLinkToken.created_at).all()
        assert len(tokens) == 2
        assert tokens[0].used_at is not None
        assert tokens[1].used_at is None
        assert tokens[1].token_hash == hashlib.sha256(second_token.encode("utf-8")).hexdigest()

    old_confirmation = client.post(
        "/api/auth/email-verification/confirm",
        headers=auth_header,
        json={"token": first_token},
    )
    assert old_confirmation.status_code == 400
    assert (
        client.post(
            "/api/auth/email-verification/confirm",
            headers=auth_header,
            json={"token": second_token},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/email-verification/confirm",
            headers=auth_header,
            json={"token": first_token},
        ).status_code
        == 400
    )
    assert (
        client.post(
            "/api/auth/email-verification/confirm",
            headers=auth_header,
            json={"token": second_token},
        ).status_code
        == 200
    )
    with SessionLocal() as db:
        tokens = (
            db.query(MagicLinkToken)
            .filter(
                MagicLinkToken.user_id == user_id,
                MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_VERIFICATION,
            )
            .order_by(MagicLinkToken.created_at)
            .all()
        )
        assert len(tokens) == 2
        assert all(token.used_at is not None for token in tokens)

    verified_resend = client.post(
        "/api/auth/email-verification/request",
        headers=auth_header,
        json={},
    )
    assert verified_resend.status_code == 200
    assert len(deliveries) == 2


def test_authenticated_resend_does_not_accept_an_email_address(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_token(monkeypatch, "no-email-input-verification-token-with-enough-entropy")
    monkeypatch.setattr(email_verification_service, "send_email_verification_email", lambda *args: True)
    registration = _register("canonical-resend@example.com")

    response = client.post(
        "/api/auth/email-verification/request",
        headers={"Authorization": f"Bearer {registration.json()['token']}"},
        json={"email": "attacker-selected@example.com"},
    )

    assert response.status_code == 422


def test_email_delivery_failure_log_excludes_verification_secrets(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fail_delivery(*args: object) -> bool:
        raise TimeoutError("verification-token-secret")

    monkeypatch.setattr(email_verification_service, "send_email_verification_email", fail_delivery)
    with caplog.at_level("WARNING", logger="payment_portal.identity.email_verification"):
        email_verification_service.send_email_verification_email_safely(
            "private@example.com",
            "https://payments.example.com/ru/verify-email#token=verification-token-secret",
            "ru",
        )

    assert "email_verification_delivery_failed" in caplog.text
    diagnostics = [record for record in caplog.records if record.getMessage() == "email_verification_delivery_failed"]
    assert len(diagnostics) == 1
    assert diagnostics[0].structured == {"outcome": "failed", "reason": "TimeoutError"}
    for secret in ("private@example.com", "verification-token-secret", "verify-email"):
        assert secret not in caplog.text
