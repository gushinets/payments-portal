from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.core.database import Base, SessionLocal
from app.legal_seed import (
    RU_DOCUMENT_VERSIONS,
    LegalDocumentSeedMismatchError,
    seed_legal_documents,
)
from app.models import (
    AuthSession,
    DocumentAcceptance,
    DocumentVersion,
    LegalAcceptanceEvent,
    LegalEntity,
    User,
)
from apps.api.tests.support.api import (
    app,
    client,
    create_document_version,
    create_legal_entity,
    register_test_user,
    reset_api_database,
)


def setup_function() -> None:
    reset_api_database()


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
        from app.domains.legal.acceptance_text import expected_acceptance_text_hash

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
        from app.domains.legal.acceptance_text import expected_acceptance_text_hash

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
    assert response.json() == {
        "status": "accepted",
        "acceptance_id": str(acceptance.id),
        "document_version_id": str(document_id),
        "doc_type": "recurring_consent",
        "version": "2026-09-generic-recurring-v1",
        "accepted_at": event.accepted_at.isoformat(),
    }


def test_seeded_registration_documents_are_accepted_atomically() -> None:
    from app.domains.legal.acceptance_text import expected_registration_acceptance_text_hash

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
            .order_by(DocumentAcceptance.created_at)
            .all()
        )
        session = db.query(AuthSession).filter(AuthSession.user_id == user.id).one()
        expected_hashes: dict[str, str] = {}
        accepted_doc_types: dict[uuid.UUID, str] = {}
        for acceptance in acceptances:
            document = db.get(DocumentVersion, acceptance.document_version_id)
            assert document is not None
            accepted_doc_types[acceptance.id] = document.doc_type
            expected_hashes[document.doc_type] = expected_registration_acceptance_text_hash(document)

    assert set(accepted_doc_types.values()) == {"privacy", "pd_consent", "offer"}
    assert {acceptance.legal_acceptance_event_id for acceptance in acceptances} == {event.id}
    assert str(event.ip) == "203.0.113.20"
    assert event.user_agent == "legal-evidence-test-agent"
    assert session.user_id == user.id
    assert event.external_billing_account_id is None
    assert event.billing_offer_id is None
    assert event.accepted_commercial_fingerprint is None
    assert {
        accepted_doc_types[acceptance.id]: acceptance.acceptance_text_hash for acceptance in acceptances
    } == expected_hashes


def test_registration_acceptance_statements_and_hashes_are_frozen() -> None:
    from app.domains.legal.acceptance_text import (
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


def test_legal_seed_rejects_scope_without_supported_legal_bootstrap() -> None:
    with SessionLocal() as db:
        with pytest.raises(ValueError, match="current bootstrap supports only anytoolai/ru"):
            seed_legal_documents(db, tenant_id="anytoolai", region="eu")


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
    from app.domains.legal.acceptance_text import expected_acceptance_text_hash

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
    assert all(event.external_billing_account_id is None for event in events)
    assert all(event.billing_offer_id is None for event in events)
    assert all(event.accepted_commercial_fingerprint is None for event in events)


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
