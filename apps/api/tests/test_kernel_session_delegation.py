"""Delegation HTTP/security tests with local SQLite; PostgreSQL races are separate."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest
import httpx
from collections.abc import Iterator
from typing import Any
from pydantic import ValidationError
from sqlalchemy import event
from sqlalchemy.exc import OperationalError

from app.core.database import SessionLocal
from app.composition.backend_consumers import initialize_backend_consumers
from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer
from app.core.settings import Settings, settings
from app.domains.identity.services import backend_delegation as delegation
from app.domains.identity.services import delegation_cleanup as cleanup
from app.domains.identity.services.auth import validate_session
from app.http.backend_session_policy import BackendErrorResponse
from app.models import AuthSession, BackendSessionDelegation, User, UserStatus
from apps.api.tests.support.api import client, register_test_user, reset_api_database
from apps.api.tests.support.settings import override_settings
from apps.api.tests.support.paid_contracts import validate_contract

VERIFIER = "synthetic-pkce-verifier-" + "v" * 32
SERVICE_TOKEN = "synthetic-kernel-service-" + "s" * 32
PREVIOUS_TOKEN = "synthetic-old-service-" + "p" * 32
INTERNAL = "/internal/v1/backend-sessions/"


@pytest.fixture(autouse=True)
def isolated_delegation_settings() -> Iterator[None]:
    reset_api_database()
    with override_settings(
        settings,
        backend_consumers=(backend_consumer(), second_consumer()),
        paid_access_clock_skew_seconds=5,
    ):
        initialize_backend_consumers(settings, SessionLocal)
        yield


def issue(consumer_id: str = "platform-kernel") -> tuple[dict[str, Any], str]:
    token = register_test_user(email=consumer_id + "@example.com")
    with SessionLocal() as db:
        db.query(User).filter(
            User.email_normalized == consumer_id + "@example.com"
        ).one().email_verified_at = datetime.now(UTC)
        db.commit()
    auth = {
        "token": token,
        "user": client.get("/api/auth/session", headers={"Authorization": "Bearer " + token}).json()["user"],
    }
    response = client.post(
        "/api/backend-session-codes",
        json={
            "consumer_id": consumer_id,
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


@pytest.mark.parametrize(
    "method,path,headers,status",
    [
        ("POST", "/api/backend-session-codes", {}, 401),
        ("POST", INTERNAL + "exchange", {"Authorization": "Bearer " + SERVICE_TOKEN}, 422),
        ("POST", INTERNAL + "introspect", {"Authorization": "Bearer " + SERVICE_TOKEN}, 422),
        (
            "GET",
            "/internal/v1/access-snapshots/00000000-0000-4000-8000-000000000001",
            {"Origin": "https://browser.example.test"},
            403,
        ),
    ],
)
def test_kernel_refusals_match_their_documented_error_response(
    method: str, path: str, headers: dict[str, str], status: int
) -> None:
    response = client.request(method, path, json={}, headers=headers)
    assert response.status_code == status
    assert BackendErrorResponse.model_validate(response.json()).model_dump() == response.json()
    schema_path = "/internal/v1/access-snapshots/{user_id}" if method == "GET" else path
    operation = client.app.openapi()["paths"][schema_path][method.lower()]
    assert operation["responses"][str(status)]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/BackendErrorResponse"
    }


def test_hashes_ttls_pkce_single_use_and_read_only_identity() -> None:
    auth, code = issue()
    assert len(code) == 43
    with SessionLocal() as db:
        row = db.query(BackendSessionDelegation).one()
        assert row.code_hash == delegation.credential_hash(code)
        assert row.code_hash != code
        assert 0 < (delegation.as_utc(row.code_expires_at) - datetime.now(UTC)).total_seconds() <= 60
    assert exchange(code, "w" * 43).status_code == 401
    response = exchange(code)
    assert response.status_code == 200
    validate_contract("exchange-response-v2", response.text)
    payload = response.json()
    assert set(payload) == {
        "schema_version",
        "consumer_id",
        "consumer_policy_revision",
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
        validate_contract("introspection-response-v2", read.text)
        assert set(read.json()) == {
            "schema_version",
            "consumer_id",
            "consumer_policy_revision",
            "user_id",
            "tenant_id",
            "region",
            "valid_until",
        }
        assert datetime.fromisoformat(read.json()["valid_until"]) == datetime.fromisoformat(
            payload["expires_at"]
        ) - timedelta(seconds=5)
        assert 0 < (datetime.fromisoformat(payload["expires_at"]) - datetime.now(UTC)).total_seconds() <= 1800
        with SessionLocal() as db:
            user, parent = validate_session(db, token=auth["token"], tenant_id="anytoolai", region="ru")
            row = db.query(BackendSessionDelegation).one()
            assert row.token_hash == delegation.credential_hash(payload["access_token"])
            assert parent.id == row.auth_session_id
            assert user.id == parent.user_id
        commits.assert_not_called()
    finally:
        event.remove(SessionLocal, "after_commit", commits)


def test_code_issuance_budget_survives_abandoned_code_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    start = datetime.now(UTC)
    monkeypatch.setattr(delegation, "utc_now", lambda: start)
    auth, _ = issue()
    request = {
        "consumer_id": "platform-kernel",
        "code_challenge": delegation.pkce_challenge(VERIFIER),
        "code_challenge_method": "S256",
    }
    headers = {"Authorization": "Bearer " + auth["token"]}
    # Background cleanup removes abandoned codes without refunding successful issuances.
    monkeypatch.setattr(delegation, "utc_now", lambda: start + timedelta(seconds=61.2))
    monkeypatch.setattr(cleanup, "utc_now", lambda: start + timedelta(seconds=61.2))
    cleanup.cleanup_batch(SessionLocal, tenant_id="anytoolai", region="ru")
    with SessionLocal() as db:
        assert db.query(BackendSessionDelegation).count() == 0
    for _ in range(59):
        response = client.post("/api/backend-session-codes", json=request, headers=headers)
        assert response.status_code == 200
    valid_code = response.json()["code"]
    for _ in range(2):
        refused = client.post("/api/backend-session-codes", json=request, headers=headers)
        assert refused.status_code == 429
        assert refused.json() == {"detail": {"code": "backend_session_rate_limited"}}
        assert refused.headers["Retry-After"] == "3539"
        assert refused.headers["Cache-Control"] == "no-store"
    # Existing credentials and parent session remain usable during the limit.
    assert exchange(valid_code).status_code == 200
    assert client.get("/api/auth/session", headers=headers).json()["authenticated"]
    monkeypatch.setattr(delegation, "utc_now", lambda: start + timedelta(seconds=3600))
    assert client.post("/api/backend-session-codes", json=request, headers=headers).status_code == 200


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
            row = db.query(BackendSessionDelegation).one()
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
                row.consumer_id = "foreign-audience"
            db.commit()
    response = introspect(token)
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == (
        "backend_delegation_expired" if change == "token_expired" else "backend_parent_authority_invalid"
    )


@pytest.mark.parametrize("change", ["expired", "audience", "scope", "parent_revoked"])
def test_exchange_rechecks_code_and_parent(change: str) -> None:
    _, code = issue()
    with SessionLocal() as db:
        row = db.query(BackendSessionDelegation).one()
        if change == "expired":
            row.code_expires_at = datetime.now(UTC)
        elif change == "audience":
            row.consumer_id = "foreign-audience"
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
    with override_settings(settings, backend_consumers=(backend_consumer(permissions=[]),)):
        assert client.post(path, json=payload, headers={"Authorization": "Bearer " + SERVICE_TOKEN}).status_code == 403
    with override_settings(settings, backend_consumers=(backend_consumer(backend_to_portal_previous_secret=None),)):
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
    with override_settings(settings, backend_consumers=()):
        assert introspect(secret).status_code == 503
    monkeypatch.setattr(
        "app.domains.identity.services.backend_delegation.read_delegation",
        Mock(side_effect=OperationalError("SELECT " + secret, {}, Exception(secret))),
    )
    assert introspect(secret).status_code == 503
    for path, body in (
        (INTERNAL + "exchange", {"code": code, "code_verifier": secret + "!"}),
        (INTERNAL + "introspect", {"access_token": secret, "extra": secret}),
        ("/api/backend-session-codes", {"code_challenge": secret, "code_challenge_method": "plain"}),
    ):
        response = client.post(path, json=body, headers={"Authorization": "Bearer " + SERVICE_TOKEN})
        assert response.status_code == 422
        assert secret not in response.text and code not in response.text
    assert all(value not in caplog.text for value in (auth["token"], code, secret, SERVICE_TOKEN))


@pytest.mark.parametrize(
    "overrides",
    [
        {"backend_to_portal_current_secret": "short"},
        {"backend_to_portal_previous_secret": SERVICE_TOKEN},
        {"portal_to_backend_current_secret": SERVICE_TOKEN},
        {"permissions": ["unknown:permission"]},
        {"consumer_policy_revision": True},
        {"consumer_policy_revision": 0},
        {"callback_url": "https://evil.invalid/callback"},
    ],
)
def test_invalid_receiver_configuration(overrides: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        backend_consumer(**overrides)


@pytest.mark.parametrize("consumer_factory", [backend_consumer, second_consumer])
def test_independent_consumer_and_rotation_cannot_redeem_or_introspect_foreign_authority(consumer_factory) -> None:
    consumer = consumer_factory()
    foreign = second_consumer() if consumer.consumer_id == "platform-kernel" else backend_consumer()
    auth, code = issue(consumer.consumer_id)
    body = {"code": code, "code_verifier": VERIFIER}
    for secret in (foreign.backend_to_portal_current_secret, foreign.backend_to_portal_previous_secret):
        response = client.post(
            INTERNAL + "exchange", json=body, headers={"Authorization": "Bearer " + secret.get_secret_value()}
        )
        assert response.status_code == 401
    response = client.post(
        INTERNAL + "exchange",
        json=body,
        headers={
            "Authorization": "Bearer " + consumer.backend_to_portal_previous_secret.get_secret_value(),
        },
    )
    assert response.status_code == 200
    result = response.json()
    assert result["consumer_id"] == consumer.consumer_id
    assert result["consumer_policy_revision"] == 1
    assert result["user_id"] == auth["user"]["user_id"]
    for other in (consumer, foreign):
        for secret in (other.backend_to_portal_current_secret, other.backend_to_portal_previous_secret):
            read = client.post(
                INTERNAL + "introspect",
                json={"access_token": result["access_token"]},
                headers={
                    "Authorization": "Bearer " + secret.get_secret_value(),
                },
            )
            assert read.status_code == (200 if other == consumer else 401)
            assert read.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "policy_change",
    [
        {"allowed_products": ["proposal_ai"]},
        {"permissions": ["backend-session:exchange", "backend-session:introspect"]},
        {"technical_source_id": "replacement-source"},
    ],
)
def test_policy_guard_rejects_reused_digest_and_rollback_and_stale_process(policy_change: dict) -> None:
    from app.infrastructure.queries.backend_policies import BackendPolicyConflict
    from app.models import BackendConsumerPolicy

    _, code = issue()
    token = exchange(code).json()["access_token"]
    original = settings.backend_consumers
    changed = backend_consumer(**policy_change)
    for invalid in (changed, backend_consumer(consumer_policy_revision=1, allowed_products=["brief_decoder"])):
        with override_settings(settings, backend_consumers=(invalid, second_consumer())):
            with pytest.raises(BackendPolicyConflict):
                initialize_backend_consumers(settings, SessionLocal)
            assert introspect(token).status_code == 503
            with SessionLocal() as db:
                rows = db.query(BackendConsumerPolicy).all()
                assert all(row.snapshot_delivery_enabled for row in rows)
    newer = backend_consumer(consumer_policy_revision=2, **policy_change)
    with override_settings(settings, backend_consumers=(newer, second_consumer())):
        initialize_backend_consumers(settings, SessionLocal)
        assert introspect(token).json()["consumer_policy_revision"] == 2
    # The old process still holds P1 settings, but cannot serve authority after P2 committed.
    assert settings.backend_consumers == original
    assert introspect(token).status_code == 503
    with pytest.raises(BackendPolicyConflict):
        initialize_backend_consumers(settings, SessionLocal)
    with SessionLocal() as db:
        row = db.get(BackendConsumerPolicy, ("platform-kernel", "anytoolai", "ru"))
        assert (row.consumer_policy_revision, row.policy_digest) == (2, newer.policy_digest)


def test_rotation_and_callback_changes_preserve_policy_digest_and_paid_revision() -> None:
    original = backend_consumer()
    rotated = backend_consumer(
        backend_to_portal_current_secret="rotated-synthetic-" + "r" * 32,
        callback_url="https://kernel.example.test/new-callback",
    )
    assert original.policy_digest == rotated.policy_digest
    with override_settings(settings, backend_consumers=(rotated, second_consumer())):
        initialize_backend_consumers(settings, SessionLocal)
    from app.models import PaidAccessState

    with SessionLocal() as db:
        assert db.query(PaidAccessState).count() == 0


@pytest.mark.parametrize("change", ["duplicate_id", "duplicate_product", "shared_secret", "foreign_scope"])
def test_consumer_registry_rejects_ambiguous_authority(change: str) -> None:
    first, second = backend_consumer(), second_consumer()
    if change == "duplicate_id":
        second = second.model_copy(update={"consumer_id": first.consumer_id})
    elif change == "duplicate_product":
        second = second.model_copy(update={"allowed_products": first.allowed_products})
    elif change == "shared_secret":
        second = second.model_copy(update={"backend_to_portal_previous_secret": first.backend_to_portal_current_secret})
    else:
        second = second.model_copy(update={"region": "eu"})
    with pytest.raises(ValidationError):
        Settings.model_validate({**settings.model_dump(), "backend_consumers": (first, second)})


def test_callback_body_tampering_and_unknown_consumer_are_refused() -> None:
    auth, _ = issue()
    payload = {
        "consumer_id": "platform-kernel",
        "code_challenge": delegation.pkce_challenge(VERIFIER),
        "code_challenge_method": "S256",
    }
    for extra in ("callback", "callback_url", "redirect_uri"):
        response = client.post(
            "/api/backend-session-codes",
            json={**payload, extra: "https://evil.invalid"},
            headers={"Authorization": "Bearer " + auth["token"]},
        )
        assert response.status_code == 422
    response = client.post(
        "/api/backend-session-codes",
        json={**payload, "consumer_id": "unknown"},
        headers={"Authorization": "Bearer " + auth["token"]},
    )
    assert response.status_code == 403
    assert client.post("/api/kernel-session-codes", json=payload).status_code == 404


def test_openapi_documents_distinct_bearers_secret_body_and_real_identity_routes() -> None:
    schema = client.app.openapi()
    schemes = schema["components"]["securitySchemes"]
    assert {"PortalUserBearer", "BackendServiceBearer"} <= schemes.keys()
    for path, scheme in (
        ("/api/backend-session-codes", "PortalUserBearer"),
        (INTERNAL + "exchange", "BackendServiceBearer"),
        (INTERNAL + "introspect", "BackendServiceBearer"),
    ):
        operation = schema["paths"][path]["post"]
        assert operation["security"] == [{scheme: []}]
        assert "no-store" in operation["description"]
        assert operation["summary"]
        request_schema = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[1]
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].rsplit("/", 1)[
            1
        ]
        assert schema["components"]["schemas"][request_schema]["examples"]
        assert schema["components"]["schemas"][response_schema]["examples"]
    operation = schema["paths"][INTERNAL + "introspect"]["post"]
    assert "access_token body" in operation["description"]
    assert schema["components"]["schemas"]["BackendIntrospectionRequest"]["required"] == ["access_token"]
    assert "/internal/v1/kernel-sessions/exchange" not in schema["paths"]


def test_second_consumer_cannot_read_snapshot_without_explicit_permission() -> None:
    consumer = second_consumer(permissions=["backend-session:exchange", "backend-session:introspect"])
    with override_settings(settings, backend_consumers=(backend_consumer(), consumer)):
        response = client.get(
            "/internal/v1/access-snapshots/00000000-0000-4000-8000-000000000001?tenant_id=anytoolai&region=ru",
            headers={"Authorization": "Bearer " + consumer.backend_to_portal_current_secret.get_secret_value()},
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "access_snapshot_forbidden"


@pytest.mark.parametrize("stage", ["issue", "exchange", "introspect"])
def test_unverified_parent_cannot_delegate_identity(stage: str) -> None:
    if stage == "issue":
        token = register_test_user(email="unverified@example.com")
        response = client.post(
            "/api/backend-session-codes",
            json={
                "consumer_id": "platform-kernel",
                "code_challenge": delegation.pkce_challenge(VERIFIER),
                "code_challenge_method": "S256",
            },
            headers={"Authorization": "Bearer " + token},
        )
    else:
        _, code = issue()
        access_token = exchange(code).json()["access_token"] if stage == "introspect" else None
        with SessionLocal() as db:
            db.query(User).one().email_verified_at = None
            db.commit()
        response = exchange(code) if stage == "exchange" else introspect(access_token)
    assert response.status_code == 401, response.text
    assert response.json()["detail"]["code"] == "backend_parent_authority_invalid"
