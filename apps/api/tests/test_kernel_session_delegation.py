"""Delegation HTTP/security tests with local SQLite; PostgreSQL races are separate."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
import httpx
from collections.abc import Iterator
from typing import Any
from pydantic import SecretStr, ValidationError
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.core.database import SessionLocal
from app.core.settings import Settings, settings
from app.domains.identity.services import kernel_delegation as delegation
from app.domains.identity.services.auth import validate_session
from app.models import AuthSession, KernelSessionDelegation, User, UserStatus
from apps.api.tests.support.api import client, register_test_user, reset_api_database
from apps.api.tests.support.settings import override_settings
from apps.api.tests.support.paid_contracts import validate_contract

VERIFIER = "synthetic-pkce-verifier-" + "v" * 32
SERVICE_TOKEN = "synthetic-kernel-service-" + "s" * 32
PREVIOUS_TOKEN = "synthetic-old-service-" + "p" * 32
INTERNAL = "/internal/v1/kernel-sessions/"


@pytest.fixture(autouse=True)
def isolated_delegation_settings() -> Iterator[None]:
    reset_api_database()
    with override_settings(
        settings,
        kernel_access_service_token=SecretStr(SERVICE_TOKEN),
        kernel_access_service_token_previous=SecretStr(PREVIOUS_TOKEN),
        kernel_access_permissions=("kernel-session:exchange", "kernel-session:introspect"),
        paid_access_clock_skew_seconds=5,
    ):
        yield


def issue() -> tuple[dict[str, Any], str]:
    token = register_test_user(email="delegation@example.com")
    auth = {
        "token": token,
        "user": client.get("/api/auth/session", headers={"Authorization": "Bearer " + token}).json()["user"],
    }
    response = client.post(
        "/api/kernel-session-codes",
        json={
            "code_challenge": delegation.pkce_challenge(VERIFIER),
            "code_challenge_method": "S256",
        },
        headers={"Authorization": "Bearer " + auth["token"]},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    validate_contract("code-response-v1", response.text)
    return auth, response.json()["code"]


def exchange(code: str, verifier: str = VERIFIER) -> httpx.Response:
    return client.post(
        INTERNAL + "exchange",
        json={"code": code, "code_verifier": verifier},
        headers={"Authorization": "Bearer " + SERVICE_TOKEN},
    )


def introspect(token: str) -> httpx.Response:
    return client.post(
        INTERNAL + "introspect", json={"access_token": token}, headers={"Authorization": "Bearer " + SERVICE_TOKEN}
    )


def test_hashes_ttls_pkce_single_use_and_read_only_identity() -> None:
    auth, code = issue()
    assert len(code) == 43
    with SessionLocal() as db:
        row = db.query(KernelSessionDelegation).one()
        assert row.code_hash == delegation.credential_hash(code)
        assert row.code_hash != code
        assert 0 < (delegation.as_utc(row.code_expires_at) - datetime.now(UTC)).total_seconds() <= 60
    assert exchange(code, "w" * 43).status_code == 401
    response = exchange(code)
    assert response.status_code == 200
    validate_contract("exchange-response-v1", response.text)
    payload = response.json()
    assert set(payload) == {
        "schema_version",
        "token_type",
        "access_token",
        "user_id",
        "tenant_id",
        "region",
        "expires_at",
    }
    assert payload["user_id"] == auth["user"]["user_id"]
    assert exchange(code).status_code == 401
    commits = Mock()
    event.listen(SessionLocal, "after_commit", commits)
    try:
        read = introspect(payload["access_token"])
        assert read.status_code == 200
        validate_contract("introspection-response-v1", read.text)
        assert set(read.json()) == {"schema_version", "user_id", "tenant_id", "region", "valid_until"}
        assert datetime.fromisoformat(read.json()["valid_until"]) == datetime.fromisoformat(
            payload["expires_at"]
        ) - timedelta(seconds=5)
        assert 0 < (datetime.fromisoformat(payload["expires_at"]) - datetime.now(UTC)).total_seconds() <= 1800
        with SessionLocal() as db:
            user, parent = validate_session(db, token=auth["token"], tenant_id="anytoolai", region="ru")
            row = db.query(KernelSessionDelegation).one()
            assert row.token_hash == delegation.credential_hash(payload["access_token"])
            assert parent.id == row.auth_session_id
            assert user.id == parent.user_id
        commits.assert_not_called()
    finally:
        event.remove(SessionLocal, "after_commit", commits)


@pytest.mark.parametrize(
    "change", ["logout", "reset", "deactivated", "revoked", "parent_expired", "token_expired", "audience"]
)
def test_parent_authority_and_distinct_expiry(change: str) -> None:
    auth, code = issue()
    token = exchange(code).json()["access_token"]
    if change == "logout":
        assert client.post("/api/auth/logout", headers={"Authorization": "Bearer " + auth["token"]}).status_code == 200
    elif change == "reset":
        # The existing reset writer revokes every parent session.
        from app.domains.identity.services.password_reset import confirm_password_reset
        from app.models import MagicLinkPurpose, MagicLinkToken

        with SessionLocal() as db:
            user = db.query(User).one()
            db.add(
                MagicLinkToken(
                    user_id=user.id,
                    email_normalized=user.email_normalized,
                    tenant_id=user.tenant_id,
                    region=user.region,
                    token_hash=delegation.credential_hash("synthetic-reset-token"),
                    purpose=MagicLinkPurpose.PASSWORD_RESET,
                    expires_at=datetime.now(UTC) + timedelta(minutes=5),
                )
            )
            db.commit()
            confirm_password_reset(
                db,
                token="synthetic-reset-token",
                password="Changed-password-123!",
                tenant_id=user.tenant_id,
                region=user.region,
            )
    else:
        with SessionLocal() as db:
            row = db.query(KernelSessionDelegation).one()
            parent = db.query(AuthSession).one()
            if change == "deactivated":
                db.query(User).one().status = UserStatus.INACTIVE
            elif change == "revoked":
                parent.revoked_at = datetime.now(UTC)
            elif change == "parent_expired":
                parent.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            elif change == "token_expired":
                row.token_expires_at = datetime.now(UTC)
            else:
                row.audience = "foreign-audience"
            db.commit()
    response = introspect(token)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == (
        "kernel_delegation_expired" if change == "token_expired" else "kernel_parent_authority_invalid"
    )


@pytest.mark.parametrize("change", ["expired", "audience", "scope", "parent_revoked"])
def test_exchange_rechecks_code_and_parent(change: str) -> None:
    _, code = issue()
    with SessionLocal() as db:
        row = db.query(KernelSessionDelegation).one()
        if change == "expired":
            row.code_expires_at = datetime.now(UTC)
        elif change == "audience":
            row.audience = "foreign-audience"
        elif change == "scope":
            db.query(User).one().status = UserStatus.INACTIVE
        else:
            db.query(AuthSession).one().revoked_at = datetime.now(UTC)
        db.commit()
    assert exchange(code).status_code == 401


def test_parent_deadline_caps_token_and_expiry_is_checked_after_locks() -> None:
    _, code = issue()
    deadline = datetime.now(UTC) + timedelta(minutes=2)
    with SessionLocal() as db:
        db.query(AuthSession).one().expires_at = deadline
        db.commit()
    assert datetime.fromisoformat(exchange(code).json()["expires_at"]) == deadline


@pytest.mark.parametrize("operation", ["exchange", "introspect"])
def test_service_rotation_scope_permission_and_browser_refusal(operation: str) -> None:
    path = INTERNAL + operation
    payload = {"code": "c" * 43, "code_verifier": VERIFIER} if operation == "exchange" else {"access_token": "t" * 43}
    for token in (SERVICE_TOKEN, PREVIOUS_TOKEN):
        assert client.post(path, json=payload, headers={"Authorization": "Bearer " + token}).status_code == 401
    for headers in (
        {},
        {"Authorization": "Bearer wrong"},
        [("Authorization", "Bearer " + SERVICE_TOKEN), ("Authorization", "Bearer " + SERVICE_TOKEN)],
    ):
        result = client.post(path, json=payload, headers=headers)
        assert result.status_code == 401
        assert result.json()["detail"]["code"] == "service_unauthorized"
    for method in ("POST", "OPTIONS"):
        response = client.request(
            method,
            path,
            json=payload,
            headers={
                "Origin": "http://localhost:3000",
                "Authorization": "Bearer " + SERVICE_TOKEN,
                "Access-Control-Request-Method": "POST",
            },
        )
        assert response.status_code == 403
        assert "access-control-allow-origin" not in response.headers
        assert response.headers["cache-control"] == "no-store"
    for query in ("?region=eu", "?tenant_id=foreign", "?region=ru&region=ru"):
        assert (
            client.post(path + query, json=payload, headers={"Authorization": "Bearer " + SERVICE_TOKEN}).status_code
            == 403
        )
    with override_settings(settings, kernel_access_permissions=()):
        assert client.post(path, json=payload, headers={"Authorization": "Bearer " + SERVICE_TOKEN}).status_code == 403
    with override_settings(settings, kernel_access_service_token_previous=None):
        assert (
            client.post(path, json=payload, headers={"Authorization": "Bearer " + PREVIOUS_TOKEN}).json()["detail"][
                "code"
            ]
            == "service_unauthorized"
        )


def test_dependency_errors_and_secret_canaries(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    auth, code = issue()
    secret = exchange(code).json()["access_token"]
    with override_settings(settings, paid_access_clock_skew_seconds=None):
        assert introspect(secret).status_code == 503
    with override_settings(settings, kernel_access_service_token=None):
        assert introspect(secret).status_code == 503
    monkeypatch.setattr(
        "app.domains.identity.services.kernel_delegation.read_delegation",
        Mock(side_effect=OperationalError("SELECT " + secret, {}, Exception(secret))),
    )
    assert introspect(secret).status_code == 503
    for path, body in (
        (INTERNAL + "exchange", {"code": code, "code_verifier": secret + "!"}),
        (INTERNAL + "introspect", {"access_token": secret, "extra": secret}),
        ("/api/kernel-session-codes", {"code_challenge": secret, "code_challenge_method": "plain"}),
    ):
        response = client.post(path, json=body, headers={"Authorization": "Bearer " + SERVICE_TOKEN})
        assert response.status_code == 422
        assert secret not in response.text and code not in response.text
    assert all(value not in caplog.text for value in (auth["token"], code, secret, SERVICE_TOKEN))


@pytest.mark.parametrize(
    "overrides",
    [
        {"kernel_access_service_token": "short"},
        {"kernel_access_service_token_previous": PREVIOUS_TOKEN, "kernel_access_service_token": None},
        {"kernel_access_service_token_previous": SERVICE_TOKEN, "kernel_access_service_token": SERVICE_TOKEN},
        {"kernel_service_token": SERVICE_TOKEN, "kernel_access_service_token": SERVICE_TOKEN},
        {"kernel_access_permissions": ("unknown:permission",)},
    ],
)
def test_invalid_receiver_configuration(overrides: dict[str, object]) -> None:
    values = settings.model_dump()
    values.update(overrides)
    with pytest.raises(ValidationError):
        Settings.model_validate(values)
