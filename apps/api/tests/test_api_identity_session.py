from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from argon2 import PasswordHasher, Type
from sqlalchemy import text

import app.domains.identity.services.auth as identity_auth_service
from app.core.database import SessionLocal
from app.domains.identity.passwords import (
    ARGON2_HASH_LEN,
    ARGON2_MEMORY_COST,
    ARGON2_PARALLELISM,
    ARGON2_TIME_COST,
    PBKDF2_ITERATIONS,
    hash_password,
    password_hash_needs_rehash,
    verify_password,
)
from app.domains.identity.router import present_user
from app.models import (
    AuthSession,
    DocumentAcceptance,
    DocumentVersion,
    LegalAcceptanceEvent,
    User,
    UserStatus,
)
from apps.api.tests.support.api import app, client, register_test_user, reset_api_database


def setup_function() -> None:
    reset_api_database()


def _legacy_password_hash(password: str, *, iterations: int = PBKDF2_ITERATIONS) -> str:
    salt = "0123456789abcdef0123456789abcdef"
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    ).hex()
    return f"pbkdf2_sha256${iterations}${salt}${digest}"


def test_password_hashes_use_locked_argon2id_parameters() -> None:
    encoded = hash_password("very-secret-password")

    assert encoded.startswith(f"$argon2id$v=19$m={ARGON2_MEMORY_COST},t={ARGON2_TIME_COST},p={ARGON2_PARALLELISM}$")
    assert verify_password("very-secret-password", encoded)
    assert not verify_password("wrong-password", encoded)
    assert not password_hash_needs_rehash(encoded)


def test_password_verification_fails_safely_for_malformed_or_unsupported_hashes() -> None:
    malformed_hashes = (
        "",
        "$argon2id$malformed",
        "pbkdf2_sha256$not-an-integer$salt$digest",
        f"pbkdf2_sha256${PBKDF2_ITERATIONS}$salt$short",
        "unsupported$hash",
    )

    assert all(not verify_password("very-secret-password", encoded) for encoded in malformed_hashes)
    assert all(not password_hash_needs_rehash(encoded) for encoded in malformed_hashes)


def test_legacy_password_with_historical_iterations_is_verified_and_rehashed_on_login() -> None:
    password = "very-secret-password"
    email = "legacy-password@example.com"
    legacy_hash = _legacy_password_hash(password, iterations=100_000)

    assert verify_password(password, legacy_hash)
    assert not verify_password("wrong-password", legacy_hash)
    assert password_hash_needs_rehash(legacy_hash)

    with SessionLocal() as db:
        registration = identity_auth_service.register_user(
            db,
            tenant_id="anytoolai",
            region="ru",
            email=email,
            password=password,
            personal_consent=True,
            offer_consent=True,
            client_ip=None,
            user_agent=None,
        )
        user = db.get(User, registration.user_id)
        assert user is not None
        user.password_hash = legacy_hash
        db.commit()

    with SessionLocal() as db:
        identity_auth_service.login_user(
            db,
            tenant_id="anytoolai",
            region="ru",
            email=email,
            password=password,
            client_ip=None,
            user_agent=None,
        )

    with SessionLocal() as db:
        user = db.get(User, registration.user_id)
        assert user is not None
        assert user.password_hash != legacy_hash
        assert user.password_hash.startswith("$argon2id$")
        assert verify_password(password, user.password_hash)


def test_argon2_password_with_stale_parameters_is_rehashed_on_login() -> None:
    password = "very-secret-password"
    email = "stale-argon2-password@example.com"
    stale_hash = PasswordHasher(
        memory_cost=ARGON2_MEMORY_COST,
        time_cost=1,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID,
    ).hash(password)
    assert password_hash_needs_rehash(stale_hash)

    with SessionLocal() as db:
        registration = identity_auth_service.register_user(
            db,
            tenant_id="anytoolai",
            region="ru",
            email=email,
            password=password,
            personal_consent=True,
            offer_consent=True,
            client_ip=None,
            user_agent=None,
        )
        user = db.get(User, registration.user_id)
        assert user is not None
        user.password_hash = stale_hash
        db.commit()

    with SessionLocal() as db:
        identity_auth_service.login_user(
            db,
            tenant_id="anytoolai",
            region="ru",
            email=email,
            password=password,
            client_ip=None,
            user_agent=None,
        )

    with SessionLocal() as db:
        user = db.get(User, registration.user_id)
        assert user is not None
        assert user.password_hash != stale_hash
        assert not password_hash_needs_rehash(user.password_hash)


def test_register_and_login_results_are_presentable_after_session_close() -> None:
    email = "auth-result-snapshot@example.com"
    with SessionLocal() as db:
        registration = identity_auth_service.register_user(
            db,
            tenant_id="anytoolai",
            region="ru",
            email=email,
            password="very-secret-password",
            personal_consent=True,
            offer_consent=True,
            client_ip=None,
            user_agent=None,
        )

    registration_user = present_user(registration)

    with SessionLocal() as db:
        authentication = identity_auth_service.login_user(
            db,
            tenant_id="anytoolai",
            region="ru",
            email=email,
            password="very-secret-password",
            client_ip=None,
            user_agent=None,
        )

    authentication_user = present_user(authentication)

    assert registration_user == authentication_user
    assert registration_user.model_dump(mode="json") == {
        "tenant_id": "anytoolai",
        "region": "ru",
        "user_id": str(registration.user_id),
        "email": email,
    }


def test_session_contract_returns_only_canonical_identity() -> None:
    token = register_test_user(email="identity-session-only@example.com")

    response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "authenticated": True,
        "user": {
            "tenant_id": "anytoolai",
            "region": "ru",
            "user_id": response.json()["user"]["user_id"],
            "email": "identity-session-only@example.com",
        },
    }
    assert "product_state" not in response.json()
    session_parameters = app.openapi()["paths"]["/api/auth/session"]["get"].get("parameters", [])
    assert "product" not in {parameter["name"] for parameter in session_parameters}
    session_schema = app.openapi()["paths"]["/api/auth/session"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert session_schema == {"$ref": "#/components/schemas/SessionResponse"}
    schemas = app.openapi()["components"]["schemas"]
    assert set(schemas["SessionResponse"]["properties"]) == {"authenticated", "user"}
    assert schemas["SessionResponse"]["properties"]["user"] == {"$ref": "#/components/schemas/SessionUserResponse"}
    assert set(schemas["SessionUserResponse"]["properties"]) == {
        "tenant_id",
        "region",
        "user_id",
        "email",
    }


def test_same_email_foreign_client_scope_cannot_create_foreign_contour_user() -> None:
    first_response = client.post(
        "/api/auth/register",
        json={
            "tenant_id": "foreign-tenant",
            "region": "eu",
            "email": "shared@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    second_response = client.post(
        "/api/auth/register",
        json={
            "tenant_id": "another-foreign-tenant",
            "region": "eu",
            "email": "shared@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json() == {"detail": {"code": "email_already_registered"}}
    assert first_response.json()["user"]["tenant_id"] == "anytoolai"
    assert first_response.json()["user"]["region"] == "ru"

    with SessionLocal() as db:
        users = db.query(User).filter(User.email_normalized == "shared@example.com").all()

    assert [(user.tenant_id, user.region) for user in users] == [("anytoolai", "ru")]


def test_register_and_login_foreign_client_scope_cannot_select_foreign_contour_user() -> None:
    from app.domains.identity.passwords import hash_password

    email = "foreign-login@example.com"
    with SessionLocal() as db:
        identity_auth_service.register_user(
            db,
            tenant_id="anytoolai",
            region="ru",
            email=email,
            password="local-password-123",
            personal_consent=True,
            offer_consent=True,
            client_ip=None,
            user_agent=None,
        )
    with SessionLocal() as db:
        db.add(
            User(
                tenant_id="anytoolai",
                region="eu",
                email=email,
                email_normalized=email,
                password_hash=hash_password("foreign-password-123"),
                status=UserStatus.ACTIVE,
            )
        )
        db.commit()

    foreign_password_response = client.post(
        "/api/auth/login",
        json={
            "tenant_id": "anytoolai",
            "region": "eu",
            "email": email,
            "password": "foreign-password-123",
        },
    )
    local_password_response = client.post(
        "/api/auth/login",
        json={
            "tenant_id": "foreign-tenant",
            "region": "eu",
            "email": email,
            "password": "local-password-123",
        },
    )

    assert foreign_password_response.status_code == 401
    assert local_password_response.status_code == 200
    assert local_password_response.json()["user"]["tenant_id"] == "anytoolai"
    assert local_password_response.json()["user"]["region"] == "ru"


def test_same_email_cannot_register_twice_in_local_scope() -> None:
    payload = {
        "region": "ru",
        "email": "shared@example.com",
        "password": "very-secret-password",
        "personal_consent": True,
        "offer_consent": True,
    }

    first_response = client.post("/api/auth/register", json=payload)
    second_response = client.post("/api/auth/register", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json() == {"detail": {"code": "email_already_registered"}}


def test_registration_failure_before_initial_session_rolls_back_and_allows_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {
        "region": "ru",
        "email": "atomic-registration@example.com",
        "password": "very-secret-password",
        "personal_consent": True,
        "offer_consent": True,
    }

    def fail_session_token_generation() -> tuple[str, str, datetime]:
        raise RuntimeError("session token generation failed")

    with monkeypatch.context() as context:
        context.setattr(
            identity_auth_service,
            "make_session_token",
            fail_session_token_generation,
        )
        failed_response = client.post("/api/auth/register", json=payload)

    assert failed_response.status_code == 500
    with SessionLocal() as db:
        assert db.query(User).filter(User.email_normalized == payload["email"]).count() == 0
        assert db.query(LegalAcceptanceEvent).count() == 0
        assert db.query(DocumentAcceptance).count() == 0
        assert db.query(AuthSession).count() == 0

    retry_response = client.post("/api/auth/register", json=payload)

    assert retry_response.status_code == 200
    with SessionLocal() as db:
        user = db.query(User).filter(User.email_normalized == payload["email"]).one()
        session = db.query(AuthSession).filter(AuthSession.user_id == user.id).one()
        event = db.query(LegalAcceptanceEvent).filter(LegalAcceptanceEvent.user_id == user.id).one()
        acceptances = db.query(DocumentAcceptance).filter(DocumentAcceptance.user_id == user.id).all()
        documents = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.id.in_([acceptance.document_version_id for acceptance in acceptances]))
            .all()
        )
        assert session.user_id == user.id
        assert {acceptance.legal_acceptance_event_id for acceptance in acceptances} == {event.id}
        assert {document.doc_type for document in documents} == {"privacy", "pd_consent", "offer"}


def test_selected_auth_failures_use_structured_error_codes() -> None:
    missing_personal_consent = client.post(
        "/api/auth/register",
        json={
            "email": "missing-personal-consent@example.com",
            "password": "very-secret-password",
            "personal_consent": False,
            "offer_consent": True,
        },
    )
    missing_offer_consent = client.post(
        "/api/auth/register",
        json={
            "email": "missing-offer-consent@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": False,
        },
    )
    invalid_login = client.post(
        "/api/auth/login",
        json={"email": "missing@example.com", "password": "wrong-password"},
    )

    assert missing_personal_consent.status_code == 400
    assert missing_personal_consent.json() == {"detail": {"code": "missing_personal_consent"}}
    assert missing_offer_consent.status_code == 400
    assert missing_offer_consent.json() == {"detail": {"code": "missing_offer_consent"}}
    assert invalid_login.status_code == 401
    assert invalid_login.json() == {"detail": {"code": "invalid_credentials"}}


def test_auth_sessions_store_only_token_hash() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]

    with SessionLocal() as db:
        session = db.query(AuthSession).one()

    assert session.token_hash
    assert session.token_hash != token
    assert len(session.token_hash) == 64
    assert not hasattr(session, "token")


def test_login_and_logout_flow() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert register_response.status_code == 200
    register_payload = register_response.json()
    assert register_payload == {
        "status": "registered",
        "token": register_payload["token"],
        "user": {
            "tenant_id": "anytoolai",
            "region": "ru",
            "user_id": register_payload["user"]["user_id"],
            "email": "user@example.com",
        },
    }

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "user@example.com",
            "password": "very-secret-password",
        },
    )

    assert login_response.status_code == 200
    login_payload = login_response.json()
    assert login_payload == {
        "status": "authenticated",
        "token": login_payload["token"],
        "user": register_payload["user"],
    }
    token = login_payload["token"]
    login_token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    with SessionLocal() as db:
        assert db.query(AuthSession).count() == 2
        assert db.query(AuthSession).filter(AuthSession.token_hash == login_token_hash).one()

    logout_response = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert logout_response.status_code == 200
    assert logout_response.json() == {"status": "logged_out"}

    with SessionLocal() as db:
        remaining_session = db.query(AuthSession).one()
        assert (
            remaining_session.token_hash
            == hashlib.sha256(register_response.json()["token"].encode("utf-8")).hexdigest()
        )

    session_response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert session_response.status_code == 401
    assert session_response.json() == {"detail": "invalid_session"}


def test_security_revoked_and_expired_auth_sessions_remain_invalid() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "inactive-sessions@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "inactive-sessions@example.com",
            "password": "very-secret-password",
        },
    )
    revoked_token = register_response.json()["token"]
    expired_token = login_response.json()["token"]
    revoked_token_hash = hashlib.sha256(revoked_token.encode("utf-8")).hexdigest()
    expired_token_hash = hashlib.sha256(expired_token.encode("utf-8")).hexdigest()

    with SessionLocal() as db:
        revoked_session = db.query(AuthSession).filter(AuthSession.token_hash == revoked_token_hash).one()
        expired_session = db.query(AuthSession).filter(AuthSession.token_hash == expired_token_hash).one()
        revoked_session.revoked_at = datetime.now(UTC)
        expired_session.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()

    for inactive_token in (revoked_token, expired_token):
        response = client.get(
            "/api/auth/session",
            headers={"Authorization": f"Bearer {inactive_token}"},
        )
        assert response.status_code == 401
        assert response.json() == {"detail": "invalid_session"}

    with SessionLocal() as db:
        assert db.query(AuthSession).count() == 2
        retained_revoked_session = db.query(AuthSession).filter(AuthSession.token_hash == revoked_token_hash).one()
        assert retained_revoked_session.revoked_at is not None


def test_foreign_contour_bearer_session_is_rejected_without_mutation() -> None:
    local_registration = client.post(
        "/api/auth/register",
        json={
            "email": "local-session@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert local_registration.status_code == 200
    local_session_response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {local_registration.json()['token']}"},
    )
    assert local_session_response.status_code == 200

    foreign_token = "foreign-contour-session-token"
    with SessionLocal() as db:
        foreign_user = User(
            tenant_id="anytoolai",
            region="eu",
            email="foreign-session@example.com",
            email_normalized="foreign-session@example.com",
            status=UserStatus.ACTIVE,
        )
        db.add(foreign_user)
        db.flush()
        foreign_session = AuthSession(
            tenant_id=foreign_user.tenant_id,
            region=foreign_user.region,
            user_id=foreign_user.id,
            token_hash=hashlib.sha256(foreign_token.encode("utf-8")).hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(days=30),
            last_seen_at=datetime.now(UTC) - timedelta(days=1),
        )
        db.add(foreign_session)
        db.commit()
        foreign_user_id = foreign_user.id
        foreign_session_id = foreign_session.id
        last_seen_at_before = foreign_session.last_seen_at

    response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {foreign_token}"},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "invalid_session"}
    with SessionLocal() as db:
        retained_user = db.get(User, foreign_user_id)
        retained_session = db.get(AuthSession, foreign_session_id)
        assert retained_user is not None
        assert retained_user.status == UserStatus.ACTIVE
        assert retained_session is not None
        assert retained_session.last_seen_at == last_seen_at_before
        assert retained_session.revoked_at is None


def test_auth_sessions_and_login_require_active_user() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "non-active-user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]

    with SessionLocal() as db:
        db.execute(
            text("UPDATE users SET status = 'future_non_active' WHERE email_normalized = :email"),
            {"email": "non-active-user@example.com"},
        )
        db.commit()

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "non-active-user@example.com",
            "password": "very-secret-password",
        },
    )
    session_response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert login_response.status_code == 401
    assert login_response.json() == {"detail": {"code": "invalid_credentials"}}
    assert session_response.status_code == 401
    assert session_response.json() == {"detail": "invalid_session"}
