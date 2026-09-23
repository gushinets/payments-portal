from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import Mock

from apps.api.tests.support.settings import configure_api_test_environment

configure_api_test_environment()

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware  # noqa: E402

from app.domains.identity.router import present_user  # noqa: E402
import app.domains.identity.services.auth as identity_auth_service  # noqa: E402
import app.domains.identity.services.password_reset as password_reset_service  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.infrastructure.persistence.password_reset import (  # noqa: E402
    prune_expired_password_reset_rate_limits,
    prune_expired_password_reset_tokens,
)
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    AuthSession,
    DocumentAcceptance,
    DocumentVersion,
    LegalAcceptanceEvent,
    LegalEntity,
    LegalEntityStatus,
    LegalEntityType,
    MagicLinkPurpose,
    MagicLinkToken,
    PasswordResetRateLimit,
    User,
    UserStatus,
)
from app.legal_seed import (  # noqa: E402
    RU_DOCUMENT_VERSIONS,
    LegalDocumentSeedMismatchError,
    seed_legal_documents,
)


app = create_app()
client = TestClient(app)


def setup_function() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_legal_documents(db)


def create_legal_entity(db, *, tenant_id: str = "anytoolai", region: str = "ru") -> LegalEntity:
    entity = LegalEntity(
        tenant_id=tenant_id,
        region=region,
        name=f"AnytoolAI {region.upper()}",
        entity_type=(LegalEntityType.INDIVIDUAL_ENTREPRENEUR if region == "ru" else LegalEntityType.MERCHANT_OF_RECORD),
        legal_address="Draft legal address",
        support_email="support@example.com",
        status=LegalEntityStatus.ACTIVE,
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


def create_document_version(
    db,
    *,
    legal_entity: LegalEntity,
    doc_type: str = "offer",
    version: str = "2026-07-ru-v1",
    title: str = "Публичная оферта",
    is_active: bool = True,
    requires_acceptance: bool = True,
) -> DocumentVersion:
    now = datetime.now(timezone.utc)
    if is_active:
        active_documents = (
            db.query(DocumentVersion)
            .filter(
                DocumentVersion.tenant_id == legal_entity.tenant_id,
                DocumentVersion.region == legal_entity.region,
                DocumentVersion.doc_type == doc_type,
                DocumentVersion.is_active.is_(True),
            )
            .all()
        )
        for active_document in active_documents:
            active_document.is_active = False
        db.flush()
    document = DocumentVersion(
        id=uuid.uuid4(),
        tenant_id=legal_entity.tenant_id,
        region=legal_entity.region,
        legal_entity_id=legal_entity.id,
        doc_type=doc_type,
        version=version,
        title=title,
        url_path=f"/{legal_entity.region}/{doc_type}",
        content_hash=f"sha256:{version}",
        published_at=now,
        effective_from=now,
        is_active=is_active,
        requires_acceptance=requires_acceptance,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def register_test_user(*, email: str, tenant_id: str = "anytoolai", region: str = "ru") -> str:
    register_response = client.post(
        "/api/auth/register",
        json={
            "tenant_id": tenant_id,
            "region": region,
            "email": email,
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert register_response.status_code == 200, register_response.text
    return register_response.json()["token"]


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
    assert registration_user == {
        "tenant_id": "anytoolai",
        "region": "ru",
        "user_id": str(registration.user_id),
        "email": email,
    }


def test_liveness_readiness_metrics_and_request_id() -> None:
    request_id = "agent-check-123"
    canonical_live_response = client.get(
        "/api/health/live",
        headers={"X-Request-ID": request_id},
    )
    canonical_ready_response = client.get("/api/health/ready")
    metrics_response = client.get("/metrics")

    assert canonical_live_response.status_code == 200
    assert canonical_live_response.headers["X-Request-ID"] == request_id
    assert canonical_live_response.json() == {"status": "alive"}
    assert canonical_ready_response.status_code == 200
    assert canonical_ready_response.json() == {"status": "ready"}
    assert canonical_ready_response.headers["X-Request-ID"]
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain")


def test_legacy_billing_contracts_are_not_mounted_or_documented() -> None:
    removed_contracts = (
        ("get", "/api/catalog/products"),
        ("post", "/api/auth/checkout-intent"),
        ("get", "/api/account/subscriptions"),
        ("get", "/api/account/subscriptions/00000000-0000-0000-0000-000000000001"),
        ("get", "/api/auth/payment-status"),
    )

    for method, path in removed_contracts:
        response = client.request(method, path)
        assert response.status_code == 404

    openapi_paths = app.openapi()["paths"]
    assert "/api/catalog/products" not in openapi_paths
    assert "/api/auth/checkout-intent" not in openapi_paths
    assert "/api/account/subscriptions" not in openapi_paths
    assert "/api/account/subscriptions/{subscription_id}" not in openapi_paths
    assert "/api/auth/payment-status" not in openapi_paths


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
    session_parameters = app.openapi()["paths"]["/api/auth/session"]["get"].get("parameters", [])
    assert "product" not in {parameter["name"] for parameter in session_parameters}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("plan_id", "00000000-0000-0000-0000-000000000001"),
        ("entrypoint_type", "product"),
        ("entrypoint_value", "document-summary"),
        ("source_url", "https://example.com/checkout"),
        ("metadata", {"checkout": True}),
    ],
)
def test_generic_legal_acceptance_rejects_checkout_context(field: str, value: object) -> None:
    with SessionLocal() as db:
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-09-generic-recurring-v1",
        )
        document_id = document.id
        from app.domains.legal.service import expected_acceptance_text_hash

        acceptance_text_hash = expected_acceptance_text_hash(document)

    token = register_test_user(email=f"legal-extra-{field}@example.com")
    response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "document_version_id": str(document_id),
            "acceptance_text_hash": acceptance_text_hash,
            field: value,
        },
    )

    assert response.status_code == 422


def test_generic_legal_acceptance_keeps_exact_version_event_evidence() -> None:
    with SessionLocal() as db:
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-09-generic-recurring-v1",
        )
        document_id = document.id
        from app.domains.legal.service import expected_acceptance_text_hash

        acceptance_text_hash = expected_acceptance_text_hash(document)

    token = register_test_user(email="generic-recurring-acceptance@example.com")
    response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "document_version_id": str(document_id),
            "acceptance_text_hash": acceptance_text_hash,
        },
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        acceptance = db.get(DocumentAcceptance, uuid.UUID(response.json()["acceptance_id"]))
        assert acceptance is not None
        event = db.get(LegalAcceptanceEvent, acceptance.legal_acceptance_event_id)
        assert event is not None

    assert acceptance.document_version_id == document_id
    assert acceptance.acceptance_text_hash == acceptance_text_hash
    assert acceptance.entrypoint_session_id is None
    assert acceptance.entrypoint_type is None
    assert acceptance.entrypoint_value is None
    assert acceptance.source_url is None
    assert acceptance.metadata_ == {}
    assert acceptance.accepted_at == event.accepted_at


def test_invalid_request_id_is_replaced() -> None:
    response = client.get(
        "/api/health/live",
        headers={"X-Request-ID": "invalid request id"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "invalid request id"
    assert len(response.headers["X-Request-ID"]) == 32


def test_seeded_registration_documents_are_accepted_atomically() -> None:
    from app.domains.legal.service import expected_registration_acceptance_text_hash

    with SessionLocal() as db:
        legal_entity = db.query(LegalEntity).filter(LegalEntity.region == "ru").one()
        create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-09-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    registration_client = TestClient(
        ProxyHeadersMiddleware(app, trusted_hosts=["testclient"]),
    )
    register_response = registration_client.post(
        "/api/auth/register",
        headers={
            "user-agent": "legal-evidence-test-agent",
            "x-forwarded-for": "203.0.113.20",
        },
        json={
            "email": "seeded-legal@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert register_response.status_code == 200, register_response.text
    with SessionLocal() as db:
        user = db.query(User).filter(User.email_normalized == "seeded-legal@example.com").one()
        event = db.query(LegalAcceptanceEvent).filter(LegalAcceptanceEvent.user_id == user.id).one()
        acceptances = (
            db.query(DocumentAcceptance)
            .filter(DocumentAcceptance.user_id == user.id)
            .order_by(DocumentAcceptance.doc_type)
            .all()
        )
        session = db.query(AuthSession).filter(AuthSession.user_id == user.id).one()
        expected_hashes: dict[str, str] = {}
        for acceptance in acceptances:
            document = db.get(DocumentVersion, acceptance.document_version_id)
            assert document is not None
            expected_hashes[acceptance.doc_type] = expected_registration_acceptance_text_hash(document)

    assert {acceptance.doc_type for acceptance in acceptances} == {"privacy", "pd_consent", "offer"}
    assert {acceptance.legal_acceptance_event_id for acceptance in acceptances} == {event.id}
    assert {acceptance.accepted_at for acceptance in acceptances} == {event.accepted_at}
    assert str(event.ip) == "203.0.113.20"
    assert event.user_agent == "legal-evidence-test-agent"
    assert all(acceptance.ip is None for acceptance in acceptances)
    assert all(acceptance.user_agent is None for acceptance in acceptances)
    assert session.user_id == user.id
    assert event.external_billing_account_id is None
    assert event.billing_offer_id is None
    assert event.accepted_commercial_fingerprint is None
    assert {acceptance.doc_type: acceptance.acceptance_text_hash for acceptance in acceptances} == expected_hashes


def test_registration_acceptance_statements_and_hashes_are_frozen() -> None:
    from app.domains.legal.service import (
        REGISTRATION_OFFER_CONSENT_TEXT,
        REGISTRATION_PERSONAL_CONSENT_TEXT,
        expected_registration_acceptance_text_hash,
        hash_acceptance_text,
    )

    expected_personal_statement = (
        "Я даю согласие на обработку персональных данных в соответствии с "
        "Согласием на обработку персональных данных и Политикой в отношении "
        "обработки персональных данных."
    )
    expected_offer_statement = "Я принимаю условия Публичной оферты."
    with SessionLocal() as db:
        documents = (
            db.query(DocumentVersion)
            .filter(
                DocumentVersion.doc_type.in_(("privacy", "pd_consent", "offer")),
                DocumentVersion.is_active.is_(True),
            )
            .all()
        )
        registration_documents = {document.doc_type: document for document in documents}

    assert REGISTRATION_PERSONAL_CONSENT_TEXT == expected_personal_statement
    assert REGISTRATION_OFFER_CONSENT_TEXT == expected_offer_statement
    assert (
        expected_registration_acceptance_text_hash(registration_documents["privacy"])
        == "fa093c89e1a09dd82691c41a5dfb51298be1680e8e8462e138280fbcf61788b3"
    )
    assert (
        expected_registration_acceptance_text_hash(registration_documents["pd_consent"])
        == "fa093c89e1a09dd82691c41a5dfb51298be1680e8e8462e138280fbcf61788b3"
    )
    assert expected_registration_acceptance_text_hash(registration_documents["offer"]) == hash_acceptance_text(
        expected_offer_statement
    )


@pytest.mark.parametrize("invalid_pack", ["missing_expected", "unmapped_required"])
def test_registration_fails_closed_for_incomplete_or_unmapped_legal_pack(invalid_pack: str) -> None:
    with SessionLocal() as db:
        if invalid_pack == "missing_expected":
            privacy = (
                db.query(DocumentVersion)
                .filter(
                    DocumentVersion.doc_type == "privacy",
                    DocumentVersion.is_active.is_(True),
                )
                .one()
            )
            privacy.is_active = False
            db.commit()
        else:
            legal_entity = db.query(LegalEntity).filter(LegalEntity.region == "ru").one()
            assert legal_entity is not None
            create_document_version(
                db,
                legal_entity=legal_entity,
                doc_type="unmapped_registration_consent",
                version="2026-09-unmapped-v1",
                title="Unmapped registration consent",
            )

    response = client.post(
        "/api/auth/register",
        json={
            "email": f"invalid-pack-{invalid_pack}@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )

    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_server_error"}}
    with SessionLocal() as db:
        assert db.query(User).count() == 0
        assert db.query(LegalAcceptanceEvent).count() == 0
        assert db.query(DocumentAcceptance).count() == 0
        assert db.query(AuthSession).count() == 0


def test_legal_seed_replaces_existing_active_document_type() -> None:
    with SessionLocal() as db:
        legal_entity = create_legal_entity(db, region="ru")
        existing_offer = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="offer",
            version="2026-07-custom",
        )
        existing_material = (
            existing_offer.legal_entity_id,
            existing_offer.title,
            existing_offer.url_path,
            existing_offer.content_hash,
            existing_offer.published_at,
            existing_offer.effective_from,
            existing_offer.requires_acceptance,
        )

        seed_legal_documents(db)

        offers = (
            db.query(DocumentVersion)
            .filter(
                DocumentVersion.tenant_id == "anytoolai",
                DocumentVersion.region == "ru",
                DocumentVersion.doc_type == "offer",
                DocumentVersion.is_active.is_(True),
            )
            .all()
        )
        seeded_documents_count = db.query(DocumentVersion).filter(DocumentVersion.version == "2026-07-11").count()
        db.refresh(existing_offer)

    assert existing_offer.is_active is False
    assert (
        existing_offer.legal_entity_id,
        existing_offer.title,
        existing_offer.url_path,
        existing_offer.content_hash,
        existing_offer.published_at,
        existing_offer.effective_from,
        existing_offer.requires_acceptance,
    ) == existing_material
    assert [offer.id for offer in offers] == [
        RU_DOCUMENT_VERSIONS[2]["id"],
    ]
    assert seeded_documents_count == len(RU_DOCUMENT_VERSIONS)


def test_legal_seed_is_idempotent_for_exact_immutable_versions() -> None:
    with SessionLocal() as db:
        seed_legal_documents(db)
        first_snapshot = [
            (
                document.id,
                document.legal_entity_id,
                document.title,
                document.url_path,
                document.content_hash,
                document.published_at,
                document.effective_from,
                document.requires_acceptance,
                document.is_active,
            )
            for document in db.query(DocumentVersion).order_by(DocumentVersion.id).all()
        ]

        seed_legal_documents(db)
        second_snapshot = [
            (
                document.id,
                document.legal_entity_id,
                document.title,
                document.url_path,
                document.content_hash,
                document.published_at,
                document.effective_from,
                document.requires_acceptance,
                document.is_active,
            )
            for document in db.query(DocumentVersion).order_by(DocumentVersion.id).all()
        ]

    assert second_snapshot == first_snapshot


def test_legal_seed_fails_closed_on_same_version_material_mismatch() -> None:
    with SessionLocal() as db:
        seed_legal_documents(db)
        offer = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.doc_type == "offer", DocumentVersion.version == "2026-07-11")
            .one()
        )
        offer.title = "Rewritten historical offer"
        db.commit()

        with pytest.raises(LegalDocumentSeedMismatchError, match="immutable fields differ: title"):
            seed_legal_documents(db)

        db.rollback()
        persisted_offer = db.get(DocumentVersion, offer.id)
        assert persisted_offer is not None
        assert persisted_offer.title == "Rewritten historical offer"


def test_legal_seed_keeps_operator_metadata_separate_from_historical_document_identity() -> None:
    with SessionLocal() as db:
        seed_legal_documents(db)
        historical_offer = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.doc_type == "offer", DocumentVersion.version == "2026-07-11")
            .one()
        )
        historical_identity = (
            historical_offer.legal_entity_id,
            historical_offer.content_hash,
            historical_offer.title,
        )
        current_operator = db.get(LegalEntity, historical_offer.legal_entity_id)
        assert current_operator is not None
        current_operator.support_email = "updated-support@example.com"
        db.commit()
        seed_legal_documents(db)

        replacement_operator = create_legal_entity(db, region="ru")
        replacement_document = create_document_version(
            db,
            legal_entity=replacement_operator,
            doc_type="offer",
            version="2026-09-replacement-operator",
            is_active=False,
        )

        db.refresh(historical_offer)

    assert (
        historical_offer.legal_entity_id,
        historical_offer.content_hash,
        historical_offer.title,
    ) == historical_identity
    assert replacement_document.legal_entity_id != historical_offer.legal_entity_id
    assert "legal_entity_versions" not in Base.metadata.tables


def test_required_document_acceptance_creates_a_new_noncommercial_event_per_call() -> None:
    with SessionLocal() as db:
        legal_entity = create_legal_entity(db)
        document = create_document_version(db, legal_entity=legal_entity, doc_type="offer")

    token = register_test_user(email="acceptance-events@example.com")
    from app.domains.legal.service import expected_acceptance_text_hash

    request_payload = {
        "document_version_id": str(document.id),
        "acceptance_text_hash": expected_acceptance_text_hash(document),
    }
    first_response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json=request_payload,
    )
    second_response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json=request_payload,
    )

    assert first_response.status_code == 200, first_response.text
    assert second_response.status_code == 200, second_response.text
    acceptance_ids = {
        uuid.UUID(first_response.json()["acceptance_id"]),
        uuid.UUID(second_response.json()["acceptance_id"]),
    }
    with SessionLocal() as db:
        acceptances = (
            db.query(DocumentAcceptance)
            .filter(DocumentAcceptance.id.in_(acceptance_ids))
            .order_by(DocumentAcceptance.created_at)
            .all()
        )
        event_ids = {acceptance.legal_acceptance_event_id for acceptance in acceptances}
        events = db.query(LegalAcceptanceEvent).filter(LegalAcceptanceEvent.id.in_(event_ids)).all()

    assert len(acceptances) == 2
    assert len(events) == 2
    assert {acceptance.legal_acceptance_event_id for acceptance in acceptances} == {event.id for event in events}
    assert all(
        acceptance.accepted_at
        == next(event.accepted_at for event in events if event.id == acceptance.legal_acceptance_event_id)
        for acceptance in acceptances
    )
    assert all(event.external_billing_account_id is None for event in events)
    assert all(event.billing_offer_id is None for event in events)
    assert all(event.accepted_commercial_fingerprint is None for event in events)
    assert all(acceptance.guest_id is None for acceptance in acceptances)


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
        assert session.user_id == user.id
        assert {acceptance.legal_acceptance_event_id for acceptance in acceptances} == {event.id}
        assert {acceptance.doc_type for acceptance in acceptances} == {"privacy", "pd_consent", "offer"}


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

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "user@example.com",
            "password": "very-secret-password",
        },
    )

    assert login_response.status_code == 200
    token = login_response.json()["token"]
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
    assert logout_response.json()["status"] == "logged_out"

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


def test_create_document_acceptance_rejects_substituted_hash_in_endpoint_and_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domains.legal.errors import InvalidAcceptanceTextHashError
    from app.domains.legal.service import (
        create_document_acceptance,
    )

    with SessionLocal() as db:
        legal_entity = create_legal_entity(db, region="ru")
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="offer",
            version="2026-08-offer-v1",
            title="Публичная оферта",
        )
        document_id = document.id
        with pytest.raises(InvalidAcceptanceTextHashError) as error:
            create_document_acceptance(
                db,
                document=document,
                acceptance_event=LegalAcceptanceEvent(
                    id=uuid.uuid4(),
                    tenant_id=document.tenant_id,
                    region=document.region,
                    user_id=uuid.uuid4(),
                    accepted_at=datetime.now(timezone.utc),
                ),
                acceptance_text_hash="f" * 64,
            )
        assert error.value.code == "invalid_acceptance_text_hash"
        assert db.query(DocumentAcceptance).count() == 0

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "legal-service-hash@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]
    event_creator = Mock(side_effect=AssertionError("invalid acceptance must not create an event"))
    monkeypatch.setattr(
        "app.domains.legal.service.create_noncommercial_legal_acceptance_event",
        event_creator,
    )

    response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "document_version_id": str(document_id),
            "acceptance_text_hash": "f" * 64,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_acceptance_text_hash"
    event_creator.assert_not_called()
    with SessionLocal() as db:
        assert db.query(LegalAcceptanceEvent).count() == 1


def test_legal_required_documents_use_instance_scope() -> None:
    with SessionLocal() as db:
        ru_entity = create_legal_entity(db, region="ru")
        eu_entity = create_legal_entity(db, region="eu")
        ru_document = create_document_version(
            db,
            legal_entity=ru_entity,
            doc_type="offer",
            version="2026-07-ru-v1",
        )
        eu_document = create_document_version(
            db,
            legal_entity=eu_entity,
            doc_type="offer",
            version="2026-07-eu-v1",
        )
        ru_document_id = ru_document.id
        eu_document_id = eu_document.id

    default_response = client.get("/api/legal/required-documents")
    foreign_scope_response = client.get("/api/legal/required-documents?tenant_id=foreign-tenant&region=eu")

    assert default_response.status_code == 200
    assert foreign_scope_response.status_code == 200
    default_documents = default_response.json()["documents"]
    foreign_scope_documents = foreign_scope_response.json()["documents"]
    assert foreign_scope_documents == default_documents
    default_document_ids = {document["document_version_id"] for document in default_documents}
    assert str(ru_document_id) in default_document_ids
    assert str(eu_document_id) not in default_document_ids
    assert all(document["tenant_id"] == "anytoolai" for document in default_documents)
    assert all(document["region"] == "ru" for document in default_documents)
    assert all(document["acceptance_text_hash"] for document in default_documents)
