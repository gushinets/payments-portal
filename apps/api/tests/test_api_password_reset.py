from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock

from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import app.domains.identity.services.password_reset as password_reset_service
from app.core.database import SessionLocal
from app.infrastructure.persistence.password_reset import (
    prune_expired_password_reset_rate_limits,
    prune_expired_password_reset_tokens,
)
from app.models import (
    AuthSession,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordResetRateLimit,
    User,
    UserStatus,
)
from apps.api.tests.support.api import app, client, reset_api_database


def setup_function() -> None:
    reset_api_database()


def test_password_reset_email_token_and_session_revocation(monkeypatch) -> None:
    sent_messages: list[tuple[str, str]] = []
    reset_token = "known-reset-token-value-with-enough-entropy"

    def fake_make_password_reset_token():
        token_hash = hashlib.sha256(reset_token.encode("utf-8")).hexdigest()
        return (
            reset_token,
            token_hash,
            datetime.now(UTC) + timedelta(minutes=30),
        )

    monkeypatch.setattr(
        password_reset_service,
        "make_password_reset_token",
        fake_make_password_reset_token,
    )
    monkeypatch.setattr(
        password_reset_service,
        "send_password_reset_email",
        lambda email, url: sent_messages.append((email, url)) or True,
    )

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "reset-user@example.com",
            "password": "old-password-123",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert register_response.status_code == 200
    old_session_token = register_response.json()["token"]

    request_response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "reset-user@example.com"},
    )
    assert request_response.status_code == 200
    assert request_response.json() == {"status": "accepted"}
    assert sent_messages == [
        (
            "reset-user@example.com",
            password_reset_service.build_password_reset_url(reset_token),
        )
    ]

    with SessionLocal() as db:
        stored_token = db.query(MagicLinkToken).one()
        stored_user = db.query(User).filter(User.email_normalized == "reset-user@example.com").one()
        assert stored_token.purpose == MagicLinkPurpose.PASSWORD_RESET
        assert stored_token.user_id == stored_user.id
        assert stored_token.token_hash
        assert stored_token.token_hash != reset_token
        assert len(stored_token.token_hash) == 64

    confirm_response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "password": "new-password-123"},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json() == {"status": "password_reset"}

    with SessionLocal() as db:
        revoked_session = (
            db.query(AuthSession)
            .filter(AuthSession.token_hash == hashlib.sha256(old_session_token.encode("utf-8")).hexdigest())
            .one()
        )
        assert revoked_session.revoked_at is not None
        assert db.query(MagicLinkToken).one().used_at is not None

    old_session_response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {old_session_token}"},
    )
    assert old_session_response.status_code == 401

    old_login_response = client.post(
        "/api/auth/login",
        json={"email": "reset-user@example.com", "password": "old-password-123"},
    )
    assert old_login_response.status_code == 401

    new_login_response = client.post(
        "/api/auth/login",
        json={"email": "reset-user@example.com", "password": "new-password-123"},
    )
    assert new_login_response.status_code == 200

    reuse_response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "password": "another-password-123"},
    )
    assert reuse_response.status_code == 400
    assert reuse_response.json() == {"detail": {"code": "invalid_or_expired_reset_token"}}


def test_foreign_contour_password_reset_token_is_rejected_without_mutation() -> None:
    from app.domains.identity.passwords import hash_password

    raw_token = "foreign-reset-token-value-with-enough-entropy"
    original_password_hash = hash_password("foreign-old-password")
    with SessionLocal() as db:
        foreign_user = User(
            tenant_id="anytoolai",
            region="eu",
            email="foreign-reset@example.com",
            email_normalized="foreign-reset@example.com",
            password_hash=original_password_hash,
            status=UserStatus.ACTIVE,
        )
        db.add(foreign_user)
        db.flush()
        foreign_session = AuthSession(
            tenant_id=foreign_user.tenant_id,
            region=foreign_user.region,
            user_id=foreign_user.id,
            token_hash=hashlib.sha256(b"foreign-reset-session").hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
        reset_token = MagicLinkToken(
            tenant_id=foreign_user.tenant_id,
            region=foreign_user.region,
            user_id=foreign_user.id,
            email_normalized=foreign_user.email_normalized,
            token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
            purpose=MagicLinkPurpose.PASSWORD_RESET,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        db.add_all([foreign_session, reset_token])
        db.commit()
        foreign_user_id = foreign_user.id
        foreign_session_id = foreign_session.id
        reset_token_id = reset_token.id

    response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": raw_token, "password": "foreign-new-password"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "invalid_or_expired_reset_token"}}
    with SessionLocal() as db:
        retained_user = db.get(User, foreign_user_id)
        retained_session = db.get(AuthSession, foreign_session_id)
        retained_token = db.get(MagicLinkToken, reset_token_id)
        assert retained_user is not None
        assert retained_user.password_hash == original_password_hash
        assert retained_session is not None
        assert retained_session.revoked_at is None
        assert retained_token is not None
        assert retained_token.used_at is None


def test_password_reset_request_does_not_reveal_unknown_email(monkeypatch) -> None:
    sent_messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        password_reset_service,
        "send_password_reset_email",
        lambda email, url: sent_messages.append((email, url)) or True,
    )

    response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "missing@example.com"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert sent_messages == []

    with SessionLocal() as db:
        stored_token = db.query(MagicLinkToken).one()
        assert stored_token.purpose == MagicLinkPurpose.PASSWORD_RESET
        assert stored_token.user_id is None
        assert stored_token.email_normalized.startswith("password-reset-decoy:")


def test_password_reset_request_uses_forwarded_client_ip_from_trusted_proxy() -> None:
    proxy_client = TestClient(
        ProxyHeadersMiddleware(app, trusted_hosts=["testclient"]),
    )

    response = proxy_client.post(
        "/api/auth/password-reset/request",
        json={"email": "forwarded@example.com"},
        headers={"x-forwarded-for": "203.0.113.10"},
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        stored_limit = db.query(PasswordResetRateLimit).filter_by(rate_limit_key="ip:anytoolai:ru:203.0.113.10").one()
        assert stored_limit.count == 1


def test_password_reset_request_derives_scope_server_side_for_rate_limits() -> None:
    for index in range(password_reset_service.PASSWORD_RESET_IP_RATE_LIMIT_MAX):
        response = client.post(
            "/api/auth/password-reset/request",
            json={
                "tenant_id": f"attacker-{index}",
                "region": "not-a-region",
                "email": f"scope-probe-{index}@example.com",
            },
        )
        assert response.status_code == 200

    limited_response = client.post(
        "/api/auth/password-reset/request",
        json={
            "tenant_id": "attacker-final",
            "region": "still-not-a-region",
            "email": "scope-probe-final@example.com",
        },
    )
    assert limited_response.status_code == 429
    assert limited_response.json() == {"detail": {"code": "password_reset_rate_limited"}}

    with SessionLocal() as db:
        assert db.query(MagicLinkToken).count() == password_reset_service.PASSWORD_RESET_IP_RATE_LIMIT_MAX
        stored_token = db.query(MagicLinkToken).first()
        assert stored_token is not None
        assert stored_token.tenant_id == "anytoolai"
        assert stored_token.region == "ru"
        ip_limit = db.query(PasswordResetRateLimit).filter_by(rate_limit_key="ip:anytoolai:ru:testclient").one()
        assert ip_limit.count == password_reset_service.PASSWORD_RESET_IP_RATE_LIMIT_MAX


def test_password_reset_request_is_rate_limited_per_account() -> None:
    for _ in range(password_reset_service.PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX):
        response = client.post(
            "/api/auth/password-reset/request",
            json={"email": "probe@example.com"},
        )
        assert response.status_code == 200

    limited_response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "probe@example.com"},
    )
    assert limited_response.status_code == 429
    assert limited_response.json() == {"detail": {"code": "password_reset_rate_limited"}}


def test_password_reset_account_limit_does_not_rollback_ip_counter() -> None:
    for _ in range(password_reset_service.PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX):
        response = client.post(
            "/api/auth/password-reset/request",
            json={"email": "rollback-probe@example.com"},
        )
        assert response.status_code == 200

    limited_response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "rollback-probe@example.com"},
    )
    assert limited_response.status_code == 429

    with SessionLocal() as db:
        stored_limit = db.query(PasswordResetRateLimit).filter_by(rate_limit_key="ip:anytoolai:ru:testclient").one()
        assert stored_limit.count == password_reset_service.PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX + 1


def test_password_reset_confirm_invalidates_other_outstanding_reset_tokens(
    monkeypatch,
) -> None:
    first_token = "first-reset-token-with-enough-length-123"
    second_token = "second-reset-token-with-enough-length-456"
    tokens = iter([first_token, second_token])

    def make_token() -> tuple[str, str, datetime]:
        token = next(tokens)
        return (
            token,
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
            datetime.now(timezone.utc) + timedelta(minutes=30),
        )

    monkeypatch.setattr(password_reset_service, "make_password_reset_token", make_token)
    monkeypatch.setattr(password_reset_service, "send_password_reset_email", lambda email, url: True)

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "multi-reset@example.com",
            "password": "old-password-123",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert register_response.status_code == 200

    first_request = client.post(
        "/api/auth/password-reset/request",
        json={"email": "multi-reset@example.com"},
    )
    second_request = client.post(
        "/api/auth/password-reset/request",
        json={"email": "multi-reset@example.com"},
    )
    assert first_request.status_code == 200
    assert second_request.status_code == 200

    with SessionLocal() as db:
        user = db.query(User).filter(User.email_normalized == "multi-reset@example.com").one()
        stored_tokens = db.query(MagicLinkToken).all()
        assert len(stored_tokens) == 2
        assert {stored_token.user_id for stored_token in stored_tokens} == {user.id}

    confirm_response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": first_token, "password": "new-password-123"},
    )
    assert confirm_response.status_code == 200

    with SessionLocal() as db:
        stored_tokens = db.query(MagicLinkToken).all()
        assert len(stored_tokens) == 2
        assert all(stored_token.used_at is not None for stored_token in stored_tokens)

    second_confirm_response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": second_token, "password": "another-password-123"},
    )
    assert second_confirm_response.status_code == 400
    assert second_confirm_response.json() == {"detail": {"code": "invalid_or_expired_reset_token"}}


def test_password_reset_request_is_rate_limited_per_ip_across_emails() -> None:
    for index in range(password_reset_service.PASSWORD_RESET_IP_RATE_LIMIT_MAX):
        response = client.post(
            "/api/auth/password-reset/request",
            json={"email": f"probe-{index}@example.com"},
        )
        assert response.status_code == 200

    limited_response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "another-probe@example.com"},
    )
    assert limited_response.status_code == 429
    assert limited_response.json() == {"detail": {"code": "password_reset_rate_limited"}}


def test_password_reset_rate_limit_window_resets_after_expiry() -> None:
    key = "account:anytoolai:ru:window-reset@example.com"
    first_attempt_at = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)
    next_window_at = first_attempt_at + timedelta(
        minutes=password_reset_service.PASSWORD_RESET_RATE_LIMIT_WINDOW_MINUTES + 1
    )

    with SessionLocal() as db:
        password_reset_service.enforce_password_reset_rate_limit(
            db=db,
            key=key,
            limit=1,
            now=first_attempt_at,
        )
        db.commit()

        password_reset_service.enforce_password_reset_rate_limit(
            db=db,
            key=key,
            limit=1,
            now=next_window_at,
        )
        db.commit()

        stored_limit = db.query(PasswordResetRateLimit).filter_by(rate_limit_key=key).one()
        assert stored_limit.count == 1
        assert stored_limit.window_start == next_window_at


def test_password_reset_rate_limit_prunes_expired_keys() -> None:
    now = datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)
    expired_at = now - timedelta(minutes=1)

    with SessionLocal() as db:
        db.add(
            PasswordResetRateLimit(
                rate_limit_key="account:anytoolai:ru:expired@example.com",
                count=1,
                window_start=expired_at - timedelta(minutes=15),
                expires_at=expired_at,
            )
        )
        db.commit()

        prune_expired_password_reset_rate_limits(db, now=now)
        db.commit()

        assert db.query(PasswordResetRateLimit).count() == 0


def test_password_reset_request_prunes_expired_reset_tokens() -> None:
    now = datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)

    with SessionLocal() as db:
        db.add(
            MagicLinkToken(
                tenant_id="anytoolai",
                region="ru",
                email_normalized="password-reset-decoy:expired",
                token_hash=hashlib.sha256(b"expired-reset-token").hexdigest(),
                purpose=MagicLinkPurpose.PASSWORD_RESET,
                expires_at=now - timedelta(minutes=1),
            )
        )
        db.commit()

        prune_expired_password_reset_tokens(db, now=now)
        db.commit()

        assert db.query(MagicLinkToken).count() == 0


def test_password_reset_email_delivery_disabled_is_observable(monkeypatch, caplog) -> None:
    monkeypatch.setattr(password_reset_service, "send_password_reset_email", lambda email, url: False)

    with caplog.at_level("WARNING", logger="payment_portal.identity.password_reset"):
        password_reset_service.send_password_reset_email_safely(
            "reset-user@example.com",
            "http://localhost/reset",
        )

    assert "password_reset_email_delivery_disabled" in caplog.text


def test_password_reset_email_delivery_failure_is_observable(monkeypatch, caplog) -> None:
    original_error = TimeoutError("synthetic timeout with reset-token-secret")
    record_password_reset_email = Mock()
    report_exception = Mock()

    def fail_delivery(email: str, url: str) -> bool:
        raise original_error

    monkeypatch.setattr(password_reset_service, "send_password_reset_email", fail_delivery)
    monkeypatch.setattr(password_reset_service, "record_password_reset_email", record_password_reset_email)
    monkeypatch.setattr(password_reset_service, "report_exception", report_exception)

    with caplog.at_level("WARNING", logger="payment_portal.identity.password_reset"):
        result = password_reset_service.send_password_reset_email_safely(
            "reset-user@example.com",
            "http://localhost/reset?token=reset-token-secret",
        )

    assert result is None
    assert password_reset_service.Operation.PASSWORD_RESET_EMAIL.value == "password_reset_email"
    record_password_reset_email.assert_called_once_with("failed")
    report_exception.assert_called_once_with(
        original_error,
        operation=password_reset_service.Operation.PASSWORD_RESET_EMAIL,
        failure_category=password_reset_service.FailureCategory.INTEGRATION_FAILURE,
    )
    diagnostics = [record for record in caplog.records if record.getMessage() == "password_reset_email_delivery_failed"]
    assert len(diagnostics) == 1
    assert diagnostics[0].structured == {"outcome": "failed", "reason": "TimeoutError"}
    for marker in (
        "reset-user@example.com",
        "http://localhost/reset?token=reset-token-secret",
        "reset-token-secret",
        str(original_error),
    ):
        assert marker not in caplog.text


