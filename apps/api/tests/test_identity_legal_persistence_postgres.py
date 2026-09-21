from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

import app.domains.identity.services.auth as identity_auth_service
from app.domains.identity.errors import EmailAlreadyRegisteredError
from app.domains.identity.passwords import hash_password
from app.models import (
    AcceptanceKind,
    AuthSession,
    DocumentAcceptance,
    DocumentVersion,
    LegalAcceptanceEvent,
    LegalEntity,
    LegalEntityStatus,
    LegalEntityType,
    MagicLinkPurpose,
    MagicLinkToken,
    User,
    UserStatus,
)


pytestmark = pytest.mark.postgres


def create_user(db_session: Session, *, email: str) -> User:
    user = User(
        tenant_id="anytoolai",
        region="ru",
        email=email,
        email_normalized=email,
        password_hash=hash_password("very-secret-password"),
        status=UserStatus.ACTIVE,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def create_legal_evidence(
    db_session: Session,
    *,
    email: str,
) -> tuple[User, DocumentVersion, LegalAcceptanceEvent, DocumentAcceptance]:
    user = create_user(db_session, email=email)
    accepted_at = datetime.now(UTC)
    entity = LegalEntity(
        tenant_id=user.tenant_id,
        region=user.region,
        name="Test legal entity",
        entity_type=LegalEntityType.COMPANY,
        legal_address="Test address",
        support_email="support@example.com",
        status=LegalEntityStatus.ACTIVE,
    )
    db_session.add(entity)
    db_session.flush()
    document = DocumentVersion(
        tenant_id=user.tenant_id,
        region=user.region,
        legal_entity_id=entity.id,
        doc_type=f"test_notice_{user.id.hex}",
        version="v1",
        title="Test legal notice",
        url_path=f"/ru/test-notice-{user.id.hex}",
        content_hash=f"sha256:{user.id.hex}",
        published_at=accepted_at,
        effective_from=accepted_at,
        is_active=True,
        requires_acceptance=True,
    )
    db_session.add(document)
    db_session.flush()
    acceptance_event = LegalAcceptanceEvent(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        accepted_at=accepted_at,
        ip="192.0.2.1",
        user_agent="test-agent",
    )
    db_session.add(acceptance_event)
    db_session.flush()
    acceptance = DocumentAcceptance(
        legal_acceptance_event_id=acceptance_event.id,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        document_version_id=document.id,
        doc_type=document.doc_type,
        version=document.version,
        acceptance_kind=AcceptanceKind.TERMS_ACCEPTANCE,
        accepted_at=accepted_at,
        ip=acceptance_event.ip,
        user_agent=acceptance_event.user_agent,
        acceptance_text_hash=f"acceptance:{user.id.hex}",
        metadata_={},
    )
    db_session.add(acceptance)
    db_session.commit()
    return user, document, acceptance_event, acceptance


def test_auth_session_scope_must_match_canonical_user(db_session: Session) -> None:
    user = create_user(db_session, email="session-scope@example.com")
    db_session.add(
        AuthSession(
            tenant_id=user.tenant_id,
            region="eu",
            user_id=user.id,
            token_hash=hashlib.sha256(b"mismatched-session-token").hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_known_reset_token_scope_must_match_canonical_user(db_session: Session) -> None:
    user = create_user(db_session, email="reset-scope@example.com")
    db_session.add(
        MagicLinkToken(
            tenant_id=user.tenant_id,
            region="eu",
            user_id=user.id,
            email_normalized=user.email_normalized,
            token_hash=hashlib.sha256(b"mismatched-reset-token").hexdigest(),
            purpose=MagicLinkPurpose.PASSWORD_RESET,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_canonical_user_delete_is_restricted_by_auth_session(db_session: Session) -> None:
    user = create_user(db_session, email="retained-user@example.com")
    db_session.add(
        AuthSession(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            token_hash=hashlib.sha256(b"retained-session-token").hexdigest(),
            expires_at=datetime.now(UTC) + timedelta(days=30),
        )
    )
    db_session.commit()

    db_session.delete(user)
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_legal_acceptance_event_core_evidence_cannot_be_updated_or_deleted(
    db_session: Session,
) -> None:
    _, _, acceptance_event, _ = create_legal_evidence(
        db_session,
        email="immutable-event@example.com",
    )

    with pytest.raises(DatabaseError, match="core legal acceptance event evidence is immutable"):
        db_session.execute(
            text(
                "UPDATE legal_acceptance_events "
                "SET accepted_at = accepted_at + interval '1 second' "
                "WHERE id = :event_id"
            ),
            {"event_id": acceptance_event.id},
        )
    db_session.rollback()

    with pytest.raises(DatabaseError, match="legal acceptance events are immutable"):
        db_session.execute(
            text("DELETE FROM legal_acceptance_events WHERE id = :event_id"),
            {"event_id": acceptance_event.id},
        )
    db_session.rollback()


def test_legal_acceptance_event_audit_metadata_may_only_be_cleared(
    db_session: Session,
) -> None:
    _, _, acceptance_event, _ = create_legal_evidence(
        db_session,
        email="redactable-event@example.com",
    )

    db_session.execute(
        text(
            "UPDATE legal_acceptance_events "
            "SET ip = NULL, user_agent = NULL "
            "WHERE id = :event_id"
        ),
        {"event_id": acceptance_event.id},
    )
    db_session.commit()

    with pytest.raises(DatabaseError, match="audit metadata may only be cleared"):
        db_session.execute(
            text(
                "UPDATE legal_acceptance_events "
                "SET user_agent = 'replacement-agent' "
                "WHERE id = :event_id"
            ),
            {"event_id": acceptance_event.id},
        )


def test_document_acceptance_rows_are_append_only(db_session: Session) -> None:
    _, _, _, acceptance = create_legal_evidence(
        db_session,
        email="append-only-acceptance@example.com",
    )

    with pytest.raises(DatabaseError, match="document acceptances are append-only"):
        db_session.execute(
            text(
                "UPDATE document_acceptances "
                "SET acceptance_text_hash = 'replacement' "
                "WHERE id = :acceptance_id"
            ),
            {"acceptance_id": acceptance.id},
        )
    db_session.rollback()

    with pytest.raises(DatabaseError, match="document acceptances are append-only"):
        db_session.execute(
            text("DELETE FROM document_acceptances WHERE id = :acceptance_id"),
            {"acceptance_id": acceptance.id},
        )


def test_document_version_material_is_immutable_but_active_selection_may_change(
    db_session: Session,
) -> None:
    _, document, _, _ = create_legal_evidence(
        db_session,
        email="immutable-document@example.com",
    )

    db_session.execute(
        text(
            "UPDATE document_versions "
            "SET is_active = false, updated_at = now() "
            "WHERE id = :document_id"
        ),
        {"document_id": document.id},
    )
    db_session.commit()

    with pytest.raises(DatabaseError, match="published legal document material is immutable"):
        db_session.execute(
            text(
                "UPDATE document_versions "
                "SET content_hash = 'sha256:replacement', updated_at = now() "
                "WHERE id = :document_id"
            ),
            {"document_id": document.id},
        )


def test_legal_event_scope_must_match_canonical_user(db_session: Session) -> None:
    user = create_user(db_session, email="event-scope@example.com")
    db_session.add(
        LegalAcceptanceEvent(
            tenant_id=user.tenant_id,
            region="eu",
            user_id=user.id,
            accepted_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_document_version_scope_must_match_legal_entity(db_session: Session) -> None:
    entity = LegalEntity(
        tenant_id="anytoolai",
        region="ru",
        name="Scoped legal entity",
        entity_type=LegalEntityType.COMPANY,
        legal_address="Test address",
        support_email="support@example.com",
        status=LegalEntityStatus.ACTIVE,
    )
    db_session.add(entity)
    db_session.flush()
    db_session.add(
        DocumentVersion(
            tenant_id=entity.tenant_id,
            region="eu",
            legal_entity_id=entity.id,
            doc_type="scope_mismatch",
            version="v1",
            title="Scope mismatch",
            url_path="/eu/scope-mismatch",
            content_hash="sha256:scope-mismatch",
            published_at=datetime.now(UTC),
            effective_from=datetime.now(UTC),
            is_active=True,
            requires_acceptance=True,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_document_acceptance_scope_must_match_event_user(db_session: Session) -> None:
    owner, document, _, _ = create_legal_evidence(
        db_session,
        email="acceptance-scope-owner@example.com",
    )
    other_user = create_user(db_session, email="acceptance-scope-other@example.com")
    acceptance_event = LegalAcceptanceEvent(
        tenant_id=owner.tenant_id,
        region=owner.region,
        user_id=owner.id,
        accepted_at=datetime.now(UTC),
    )
    db_session.add(acceptance_event)
    db_session.flush()
    mismatched_acceptance = DocumentAcceptance(
        legal_acceptance_event_id=acceptance_event.id,
        tenant_id=owner.tenant_id,
        region=owner.region,
        user_id=other_user.id,
        document_version_id=document.id,
        doc_type=document.doc_type,
        version=document.version,
        acceptance_kind=AcceptanceKind.TERMS_ACCEPTANCE,
        accepted_at=acceptance_event.accepted_at,
        acceptance_text_hash="acceptance:scope-mismatch",
        metadata_={},
    )
    db_session.add(mismatched_acceptance)

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_document_acceptance_scope_must_match_document_version(db_session: Session) -> None:
    owner = create_user(db_session, email="acceptance-document-scope@example.com")
    eu_entity = LegalEntity(
        tenant_id=owner.tenant_id,
        region="eu",
        name="EU test legal entity",
        entity_type=LegalEntityType.COMPANY,
        legal_address="Test address",
        support_email="support@example.com",
        status=LegalEntityStatus.ACTIVE,
    )
    db_session.add(eu_entity)
    db_session.flush()
    eu_document = DocumentVersion(
        tenant_id=owner.tenant_id,
        region="eu",
        legal_entity_id=eu_entity.id,
        doc_type="eu_scope_notice",
        version="v1",
        title="EU scope notice",
        url_path="/eu/scope-notice",
        content_hash="sha256:eu-scope-notice",
        published_at=datetime.now(UTC),
        effective_from=datetime.now(UTC),
        is_active=True,
        requires_acceptance=True,
    )
    acceptance_event = LegalAcceptanceEvent(
        tenant_id=owner.tenant_id,
        region=owner.region,
        user_id=owner.id,
        accepted_at=datetime.now(UTC),
    )
    db_session.add_all([eu_document, acceptance_event])
    db_session.flush()
    db_session.add(
        DocumentAcceptance(
            legal_acceptance_event_id=acceptance_event.id,
            tenant_id=owner.tenant_id,
            region=owner.region,
            user_id=owner.id,
            document_version_id=eu_document.id,
            doc_type=eu_document.doc_type,
            version=eu_document.version,
            acceptance_kind=AcceptanceKind.TERMS_ACCEPTANCE,
            accepted_at=acceptance_event.accepted_at,
            acceptance_text_hash="acceptance:document-scope-mismatch",
            metadata_={},
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


@pytest.mark.parametrize(
    ("external_billing_account_id", "billing_offer_id", "accepted_commercial_fingerprint"),
    [
        ("billing-account", None, None),
        ("billing-account", "", "fingerprint"),
        ("billing-account", "offer", "   "),
    ],
)
def test_legal_acceptance_event_commercial_triplet_is_all_or_none_and_nonempty(
    db_session: Session,
    external_billing_account_id: str | None,
    billing_offer_id: str | None,
    accepted_commercial_fingerprint: str | None,
) -> None:
    user = create_user(
        db_session,
        email="commercial-triplet@example.com",
    )
    db_session.add(
        LegalAcceptanceEvent(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            external_billing_account_id=external_billing_account_id,
            billing_offer_id=billing_offer_id,
            accepted_commercial_fingerprint=accepted_commercial_fingerprint,
            accepted_at=datetime.now(UTC),
        )
    )

    with pytest.raises(IntegrityError):
        db_session.flush()


def test_legal_acceptance_event_accepts_a_complete_commercial_triplet(
    db_session: Session,
) -> None:
    user = create_user(db_session, email="complete-commercial-triplet@example.com")
    acceptance_event = LegalAcceptanceEvent(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        external_billing_account_id="billing-account",
        billing_offer_id="offer",
        accepted_commercial_fingerprint="fingerprint",
        accepted_at=datetime.now(UTC),
    )
    db_session.add(acceptance_event)
    db_session.flush()

    assert acceptance_event.id is not None


def test_concurrent_duplicate_registration_keeps_one_complete_result(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    del migrated_database
    email = "concurrent-registration@example.com"
    precheck_barrier = Barrier(2)
    original_get_user = identity_auth_service.get_user_by_normalized_email

    def synchronized_get_user(
        db: Session,
        *,
        tenant_id: str,
        region: str,
        email_normalized: str,
    ) -> User | None:
        user = original_get_user(
            db,
            tenant_id=tenant_id,
            region=region,
            email_normalized=email_normalized,
        )
        if user is None:
            precheck_barrier.wait(timeout=10)
        return user

    monkeypatch.setattr(identity_auth_service, "get_user_by_normalized_email", synchronized_get_user)

    def register_once() -> str:
        with postgres_session_factory() as session:
            try:
                identity_auth_service.register_user(
                    session,
                    tenant_id="anytoolai",
                    region="ru",
                    email=email,
                    password="very-secret-password",
                    personal_consent=True,
                    offer_consent=True,
                    client_ip="192.0.2.10",
                    user_agent="registration-concurrency-test",
                )
            except EmailAlreadyRegisteredError:
                return "duplicate"
        return "registered"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(lambda _: register_once(), range(2)))

    assert sorted(outcomes) == ["duplicate", "registered"]
    with postgres_session_factory() as session:
        users = session.query(User).filter(User.email_normalized == email).all()
        assert len(users) == 1
        user = users[0]
        sessions = session.query(AuthSession).filter(AuthSession.user_id == user.id).all()
        events = (
            session.query(LegalAcceptanceEvent)
            .filter(LegalAcceptanceEvent.user_id == user.id)
            .all()
        )
        acceptances = (
            session.query(DocumentAcceptance)
            .filter(DocumentAcceptance.user_id == user.id)
            .all()
        )

    assert len(sessions) == 1
    assert len(events) == 1
    assert len(acceptances) == 3
    assert {acceptance.legal_acceptance_event_id for acceptance in acceptances} == {
        events[0].id
    }
    assert {acceptance.doc_type for acceptance in acceptances} == {"privacy", "pd_consent", "offer"}
