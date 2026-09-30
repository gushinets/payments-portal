from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

import app.core.password_reset_email as password_reset_email
import app.domains.identity.password_reset as password_reset_presentation
import app.domains.identity.services.password_reset as password_reset_service
from app.core.database import SessionLocal
from app.generated.locales import (
    LANGUAGE_TAG_BY_ROUTE_LOCALE,
    RouteLocale,
)
from app.infrastructure.persistence.password_reset import (
    prune_expired_password_reset_rate_limits,
    prune_expired_password_reset_tokens,
)
from app.models import (
    AuthenticationRateLimit,
    AuthSession,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordResetRateLimit,
    User,
    UserStatus,
)
from apps.api.tests.support.api import app, client, register_test_user, reset_api_database


def setup_function() -> None:
    reset_api_database()


def test_password_reset_email_token_and_session_revocation(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_messages: list[tuple[str, str, RouteLocale, int]] = []
    reset_token = "known-reset-token-value-with-enough-entropy"

    def fake_make_password_reset_token() -> tuple[str, str, datetime]:
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
        lambda email, url, route_locale, ttl_minutes: (
            sent_messages.append((email, url, route_locale, ttl_minutes)) or True
        ),
    )

    old_session_token = register_test_user(email="reset-user@example.com")
    with SessionLocal() as db:
        user = db.query(User).filter(User.email_normalized == "reset-user@example.com").one()
        user.password_hash = password_reset_service.hash_password("old-password-123")
        db.commit()

    request_response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "reset-user@example.com"},
        headers={"accept-language": "de"},
    )
    assert request_response.status_code == 200
    assert request_response.json() == {"status": "accepted"}
    assert sent_messages == [
        (
            "reset-user@example.com",
            password_reset_service.build_password_reset_url(reset_token, "de"),
            "de",
            password_reset_service.PASSWORD_RESET_TTL_MINUTES,
        )
    ]

    with SessionLocal() as db:
        stored_token = db.query(MagicLinkToken).filter_by(purpose=MagicLinkPurpose.PASSWORD_RESET).one()
        stored_user = db.query(User).filter(User.email_normalized == "reset-user@example.com").one()
        assert stored_token.purpose == MagicLinkPurpose.PASSWORD_RESET
        assert stored_token.user_id == stored_user.id
        assert stored_token.token_hash
        assert stored_token.token_hash != reset_token
        assert len(stored_token.token_hash) == 64
        assert (stored_token.tenant_id, stored_token.region) == ("anytoolai", "ru")

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
        assert db.query(MagicLinkToken).filter_by(purpose=MagicLinkPurpose.PASSWORD_RESET).one().used_at is not None

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


def test_password_reset_request_does_not_reveal_unknown_email(monkeypatch: pytest.MonkeyPatch) -> None:
    sent_messages: list[tuple[str, str, RouteLocale, int]] = []
    monkeypatch.setattr(
        password_reset_service,
        "send_password_reset_email",
        lambda email, url, route_locale, ttl_minutes: (
            sent_messages.append((email, url, route_locale, ttl_minutes)) or True
        ),
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


@pytest.mark.parametrize(
    ("accept_language", "expected_route_locale"),
    tuple((language_tag, route_locale) for route_locale, language_tag in LANGUAGE_TAG_BY_ROUTE_LOCALE.items()),
)
def test_password_reset_request_normalizes_every_canonical_language_tag(
    monkeypatch: pytest.MonkeyPatch,
    accept_language: str,
    expected_route_locale: RouteLocale,
) -> None:
    prepare_password_reset = Mock(
        return_value=password_reset_service.PasswordResetDeliveryResult(
            recipient_email="reset-user@example.com",
            reset_url="https://payments.example.com/reset#token=secret",
            send_email=False,
            route_locale=expected_route_locale,
        )
    )
    monkeypatch.setattr(
        password_reset_presentation,
        "prepare_password_reset",
        prepare_password_reset,
    )

    response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "reset-user@example.com"},
        headers={"accept-language": accept_language},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert prepare_password_reset.call_args.kwargs["route_locale"] == expected_route_locale


@pytest.mark.parametrize(
    ("accept_language", "expected_route_locale"),
    [
        ("PT-br", "pt"),
        ("DE", "de"),
        ("de ; q=0.8", "de"),
        ("de; q=0.8", "de"),
        ("en;q=0.4,de;q=0.9", "de"),
        ("de;q=0.8,en;q=0.8", "de"),
        ("de;q=0,en;q=0.5", "en"),
        ("de;q=0", "ru"),
        ("ja-JP,de;q=0.7", "de"),
        ("de;foo=bar,en;q=0.6", "en"),
        (None, "ru"),
        ("", "ru"),
        ("ja-JP", "ru"),
        ("*", "ru"),
        ("de;q=.5", "ru"),
        ("de;q=1.1", "ru"),
        ("de;q=0.0000", "ru"),
        ("de;q=0.5;path=/reset-password", "ru"),
        ("../../de/reset-password", "ru"),
    ],
)
def test_password_reset_request_strictly_normalizes_accept_language(
    monkeypatch: pytest.MonkeyPatch,
    accept_language: str | None,
    expected_route_locale: RouteLocale,
) -> None:
    prepare_password_reset = Mock(
        return_value=password_reset_service.PasswordResetDeliveryResult(
            recipient_email="reset-user@example.com",
            reset_url="https://payments.example.com/reset#token=secret",
            send_email=False,
            route_locale=expected_route_locale,
        )
    )
    monkeypatch.setattr(
        password_reset_presentation,
        "prepare_password_reset",
        prepare_password_reset,
    )
    headers = {} if accept_language is None else {"accept-language": accept_language}

    response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "reset-user@example.com"},
        headers=headers,
    )

    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert prepare_password_reset.call_args.kwargs["route_locale"] == expected_route_locale
    assert "accept_language" not in prepare_password_reset.call_args.kwargs


@pytest.mark.parametrize("accept_language", [None, "ja-JP"])
def test_password_reset_request_uses_ru_email_template_for_fallback_language(
    monkeypatch: pytest.MonkeyPatch,
    accept_language: str | None,
) -> None:
    delivered_messages: list[dict[str, str]] = []

    def capture_text_email(*, to_email: str, subject: str, body: str) -> bool:
        delivered_messages.append(
            {
                "to_email": to_email,
                "subject": subject,
                "body": body,
            }
        )
        return True

    monkeypatch.setattr(password_reset_email, "send_text_email", capture_text_email)
    register_test_user(email="fallback-reset@example.com")
    headers = {} if accept_language is None else {"accept-language": accept_language}

    response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "fallback-reset@example.com"},
        headers=headers,
    )

    assert response.status_code == 200
    assert len(delivered_messages) == 1
    delivered = delivered_messages[0]
    reset_url = delivered["body"].splitlines()[3]
    assert "/ru/reset-password#" in reset_url
    expected_content = password_reset_email.render_password_reset_email(
        route_locale="ru",
        reset_url=reset_url,
        ttl_minutes=password_reset_service.PASSWORD_RESET_TTL_MINUTES,
    )
    assert delivered == {
        "to_email": "fallback-reset@example.com",
        "subject": expected_content.subject,
        "body": expected_content.body,
    }


def test_password_reset_request_rejects_unicode_qvalue_digit() -> None:
    assert password_reset_presentation._normalize_request_language("de;q=0.\u0661") == "ru"


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
            headers={"accept-language": "de"},
        )
        assert response.status_code == 200

    limited_response = client.post(
        "/api/auth/password-reset/request",
        json={
            "tenant_id": "attacker-final",
            "region": "still-not-a-region",
            "email": "scope-probe-final@example.com",
        },
        headers={"accept-language": "de"},
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
    monkeypatch: pytest.MonkeyPatch,
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
    monkeypatch.setattr(
        password_reset_service,
        "send_password_reset_email",
        lambda email, url, route_locale, ttl_minutes: True,
    )

    register_test_user(email="multi-reset@example.com")
    with SessionLocal() as db:
        user = db.query(User).filter(User.email_normalized == "multi-reset@example.com").one()
        user.password_hash = password_reset_service.hash_password("old-password-123")
        db.commit()

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
        stored_tokens = db.query(MagicLinkToken).filter_by(purpose=MagicLinkPurpose.PASSWORD_RESET).all()
        assert len(stored_tokens) == 2
        assert {stored_token.user_id for stored_token in stored_tokens} == {user.id}

    confirm_response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": first_token, "password": "new-password-123"},
    )
    assert confirm_response.status_code == 200

    with SessionLocal() as db:
        stored_tokens = db.query(MagicLinkToken).filter_by(purpose=MagicLinkPurpose.PASSWORD_RESET).all()
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


def test_password_reset_email_delivery_disabled_is_observable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        password_reset_service,
        "send_password_reset_email",
        lambda email, url, route_locale, ttl_minutes: False,
    )

    with caplog.at_level("WARNING", logger="payment_portal.identity.password_reset"):
        password_reset_service.send_password_reset_email_safely(
            "reset-user@example.com",
            "http://localhost/reset?token=reset-token-secret",
            "ru",
        )

    assert "password_reset_email_delivery_disabled" in caplog.text
    for marker in (
        "reset-user@example.com",
        "http://localhost/reset?token=reset-token-secret",
        "reset-token-secret",
    ):
        assert marker not in caplog.text


def test_password_reset_email_delivery_failure_is_observable(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    original_error = TimeoutError("synthetic timeout with reset-token-secret")
    record_password_reset_email = Mock()
    report_exception = Mock()

    def fail_delivery(
        email: str,
        url: str,
        route_locale: RouteLocale,
        ttl_minutes: int,
    ) -> bool:
        raise original_error

    monkeypatch.setattr(password_reset_service, "send_password_reset_email", fail_delivery)
    monkeypatch.setattr(password_reset_service, "record_password_reset_email", record_password_reset_email)
    monkeypatch.setattr(password_reset_service, "report_exception", report_exception)

    with caplog.at_level("WARNING", logger="payment_portal.identity.password_reset"):
        result = password_reset_service.send_password_reset_email_safely(
            "reset-user@example.com",
            "http://localhost/reset?token=reset-token-secret",
            "ru",
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


def test_unverified_password_reset_preserves_unverified_state_and_invalidates_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_token = "unverified-reset-token-with-enough-entropy"
    monkeypatch.setattr(
        password_reset_service,
        "make_password_reset_token",
        lambda: (
            reset_token,
            hashlib.sha256(reset_token.encode("utf-8")).hexdigest(),
            datetime.now(UTC) + timedelta(minutes=30),
        ),
    )
    registration = client.post(
        "/api/auth/register",
        json={
            "email": "unverified-reset@example.com",
            "password": "old-password-123",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert registration.status_code == 200
    failed_login = client.post(
        "/api/auth/login",
        json={"email": "unverified-reset@example.com", "password": "wrong-password-123"},
    )
    assert failed_login.status_code == 401

    requested = client.post(
        "/api/auth/password-reset/request",
        json={"email": "unverified-reset@example.com"},
    )
    confirmed = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "password": "new-password-123"},
    )

    assert requested.status_code == 200
    assert confirmed.status_code == 200
    with SessionLocal() as db:
        user = db.query(User).filter_by(email_normalized="unverified-reset@example.com").one()
        verification_tokens = db.query(MagicLinkToken).filter_by(purpose=MagicLinkPurpose.EMAIL_VERIFICATION).all()
        assert user.email_verified_at is None
        assert db.query(AuthSession).filter_by(user_id=user.id).count() == 0
        assert verification_tokens
        assert all(token.used_at is not None for token in verification_tokens)
        assert (
            db.query(AuthenticationRateLimit)
            .filter_by(rate_limit_key="login:account:anytoolai:ru:unverified-reset@example.com")
            .count()
            == 0
        )
