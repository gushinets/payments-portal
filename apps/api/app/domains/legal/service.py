from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.core.observability import record_legal_acceptance
from app.core.time import utc_now
from app.domains.legal.acceptance_text import (
    ACCEPTANCE_KIND_BY_DOC_TYPE,
    REGISTRATION_DOCUMENT_TYPES,
    expected_acceptance_text_hash,
    expected_registration_acceptance_text_hash,
    valid_acceptance_text_hashes,
)
from app.domains.legal.errors import (
    DocumentVersionNotFoundError,
    InvalidAcceptanceTextHashError,
    RegistrationLegalPackInvalidError,
)
from app.infrastructure.queries.legal import (
    get_active_required_document_by_id,
    list_active_required_documents,
    list_active_required_documents_for_registration,
    list_document_acceptance_fingerprints,
)
from app.models import (
    AcceptanceKind,
    DocumentAcceptance,
    DocumentVersion,
    LegalAcceptanceEvent,
    User,
)


@dataclass(frozen=True)
class LegalAcceptanceResult:
    acceptance_id: uuid.UUID
    document_version_id: uuid.UUID
    doc_type: str
    version: str
    accepted_at: datetime


def get_active_required_documents(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    now: datetime | None = None,
) -> list[DocumentVersion]:
    effective_at = now or utc_now()
    return list_active_required_documents(
        db,
        tenant_id=tenant_id,
        region=region,
        effective_at=effective_at,
    )


def get_registration_required_documents(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    now: datetime | None = None,
) -> list[DocumentVersion]:
    effective_at = now or utc_now()
    active_documents = list_active_required_documents_for_registration(
        db,
        tenant_id=tenant_id,
        region=region,
    )
    registration_documents = [document for document in active_documents if document.doc_type != "recurring_consent"]
    documents_by_type = {document.doc_type: document for document in registration_documents}
    if (
        len(registration_documents) != len(REGISTRATION_DOCUMENT_TYPES)
        or set(documents_by_type) != set(REGISTRATION_DOCUMENT_TYPES)
        or any(
            _as_utc_naive(documents_by_type[doc_type].effective_from) > _as_utc_naive(effective_at)
            for doc_type in REGISTRATION_DOCUMENT_TYPES
        )
    ):
        raise RegistrationLegalPackInvalidError()
    return [documents_by_type[doc_type] for doc_type in REGISTRATION_DOCUMENT_TYPES]


def get_missing_required_documents_for_user(
    db: Session,
    *,
    user: User,
    require_recurring_consent: bool = False,
    now: datetime | None = None,
) -> list[DocumentVersion]:
    effective_at = now or utc_now()
    required_documents = get_active_required_documents(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        now=effective_at,
    )
    if not require_recurring_consent:
        required_documents = [document for document in required_documents if document.doc_type != "recurring_consent"]
    if not required_documents:
        return []

    accepted_version_fingerprints = set(
        list_document_acceptance_fingerprints(
            db,
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            document_version_ids=[document.id for document in required_documents],
            accepted_at=effective_at,
        )
    )
    return [
        document
        for document in required_documents
        if not any(
            (
                document.id,
                ACCEPTANCE_KIND_BY_DOC_TYPE.get(document.doc_type, AcceptanceKind.TERMS_ACCEPTANCE),
                acceptance_text_hash,
            )
            in accepted_version_fingerprints
            for acceptance_text_hash in valid_acceptance_text_hashes(document)
        )
    ]


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def create_document_acceptance(
    db: Session,
    *,
    document: DocumentVersion,
    acceptance_event: LegalAcceptanceEvent,
    acceptance_text_hash: str,
) -> DocumentAcceptance:
    if acceptance_text_hash != expected_acceptance_text_hash(document):
        raise InvalidAcceptanceTextHashError()

    return _create_document_acceptance(
        db,
        document=document,
        acceptance_event=acceptance_event,
        acceptance_text_hash=acceptance_text_hash,
    )


def _create_document_acceptance(
    db: Session,
    *,
    document: DocumentVersion,
    acceptance_event: LegalAcceptanceEvent,
    acceptance_text_hash: str,
) -> DocumentAcceptance:
    acceptance = DocumentAcceptance(
        legal_acceptance_event_id=acceptance_event.id,
        tenant_id=acceptance_event.tenant_id,
        region=acceptance_event.region,
        user_id=acceptance_event.user_id,
        document_version_id=document.id,
        acceptance_kind=ACCEPTANCE_KIND_BY_DOC_TYPE.get(document.doc_type, AcceptanceKind.TERMS_ACCEPTANCE),
        acceptance_text_hash=acceptance_text_hash,
    )
    db.add(acceptance)
    return acceptance


def create_noncommercial_legal_acceptance_event(
    db: Session,
    *,
    user: User,
    accepted_at: datetime | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> LegalAcceptanceEvent:
    acceptance_event = LegalAcceptanceEvent(
        id=uuid.uuid4(),
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        accepted_at=accepted_at or utc_now(),
        ip=ip,
        user_agent=user_agent,
    )
    db.add(acceptance_event)
    db.flush()
    return acceptance_event


def create_registration_legal_evidence(
    db: Session,
    *,
    user: User,
    documents: list[DocumentVersion],
    accepted_at: datetime,
    ip: str | None,
    user_agent: str | None,
) -> LegalAcceptanceEvent:
    if [document.doc_type for document in documents] != list(REGISTRATION_DOCUMENT_TYPES):
        raise RegistrationLegalPackInvalidError()

    acceptance_event = create_noncommercial_legal_acceptance_event(
        db,
        user=user,
        accepted_at=accepted_at,
        ip=ip,
        user_agent=user_agent,
    )
    for document in documents:
        _create_document_acceptance(
            db,
            document=document,
            acceptance_event=acceptance_event,
            acceptance_text_hash=expected_registration_acceptance_text_hash(document),
        )
    return acceptance_event


def accept_legal_document(
    db: Session,
    *,
    user: User,
    document_version_id: uuid.UUID,
    acceptance_text_hash: str,
    client_ip: str | None,
    user_agent: str | None,
) -> LegalAcceptanceResult:
    document = get_active_required_document_by_id(
        db,
        document_version_id=document_version_id,
        tenant_id=user.tenant_id,
        region=user.region,
        effective_at=utc_now(),
    )
    if document is None:
        record_legal_acceptance("document_not_found")
        raise DocumentVersionNotFoundError()

    try:
        if acceptance_text_hash != expected_acceptance_text_hash(document):
            raise InvalidAcceptanceTextHashError()
        acceptance_event = create_noncommercial_legal_acceptance_event(
            db,
            user=user,
            ip=client_ip,
            user_agent=user_agent,
        )
        acceptance = create_document_acceptance(
            db,
            document=document,
            acceptance_event=acceptance_event,
            acceptance_text_hash=acceptance_text_hash,
        )
    except InvalidAcceptanceTextHashError:
        record_legal_acceptance("invalid_text_hash")
        raise

    db.commit()
    db.refresh(acceptance)
    db.refresh(acceptance_event)
    result = LegalAcceptanceResult(
        acceptance_id=acceptance.id,
        document_version_id=acceptance.document_version_id,
        doc_type=document.doc_type,
        version=document.version,
        accepted_at=acceptance_event.accepted_at,
    )
    record_legal_acceptance("accepted")
    return result
