from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.observability import record_legal_acceptance
from app.core.time import utc_now
from app.domains.legal.errors import (
    DocumentVersionNotFoundError,
    InvalidAcceptanceTextHashError,
    RegistrationLegalPackInvalidError,
    RecurringConsentContextRequiredError,
    RecurringConsentPlanInvalidError,
)
from app.infrastructure.queries.legal import (
    get_active_required_document_by_id,
    get_document_acceptance_candidate,
    get_document_version_by_id,
    list_active_required_documents,
    list_active_required_documents_for_registration,
    list_document_acceptance_fingerprints,
)
from app.infrastructure.queries.plans import get_current_sellable_plan
from app.models import (
    AcceptanceKind,
    DocumentAcceptance,
    DocumentVersion,
    LegalAcceptanceEvent,
    User,
)


ACCEPTANCE_KIND_BY_DOC_TYPE = {
    "privacy": AcceptanceKind.PRIVACY_CONSENT,
    "pd_consent": AcceptanceKind.PRIVACY_CONSENT,
    "offer": AcceptanceKind.TERMS_ACCEPTANCE,
    "recurring_consent": AcceptanceKind.RECURRING_CONSENT,
    "cookies": AcceptanceKind.COOKIES,
}

REGISTRATION_PERSONAL_CONSENT_TEXT = (
    "Я даю согласие на обработку персональных данных в соответствии с "
    "Согласием на обработку персональных данных и Политикой в отношении "
    "обработки персональных данных."
)
REGISTRATION_OFFER_CONSENT_TEXT = (
    "Я принимаю условия Публичной оферты и ознакомлен(а) с Условиями отмены "
    "подписки и возврата денежных средств."
)
REGISTRATION_DOCUMENT_TYPES = ("privacy", "pd_consent", "offer")
REGISTRATION_ACCEPTANCE_TEXT_BY_DOC_TYPE = {
    "privacy": REGISTRATION_PERSONAL_CONSENT_TEXT,
    "pd_consent": REGISTRATION_PERSONAL_CONSENT_TEXT,
    "offer": REGISTRATION_OFFER_CONSENT_TEXT,
}


@dataclass(frozen=True)
class LegalAcceptanceResult:
    acceptance_id: uuid.UUID
    document_version_id: uuid.UUID
    doc_type: str
    version: str
    accepted_at: datetime


def hash_acceptance_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_acceptance_text(document: DocumentVersion) -> str:
    return f"Я принимаю документ «{document.title}»."


def expected_acceptance_text_hash(document: DocumentVersion) -> str:
    return hash_acceptance_text(build_acceptance_text(document))


def expected_registration_acceptance_text_hash(document: DocumentVersion) -> str:
    acceptance_text = REGISTRATION_ACCEPTANCE_TEXT_BY_DOC_TYPE.get(document.doc_type)
    if acceptance_text is None:
        raise RegistrationLegalPackInvalidError()
    return hash_acceptance_text(acceptance_text)


def valid_acceptance_text_hashes(document: DocumentVersion) -> frozenset[str]:
    hashes = {expected_acceptance_text_hash(document)}
    registration_text = REGISTRATION_ACCEPTANCE_TEXT_BY_DOC_TYPE.get(document.doc_type)
    if registration_text is not None:
        hashes.add(hash_acceptance_text(registration_text))
    return frozenset(hashes)


def present_required_document(document: DocumentVersion) -> dict[str, str]:
    return {
        "document_version_id": str(document.id),
        "doc_type": document.doc_type,
        "version": document.version,
        "title": document.title,
        "url_path": document.url_path,
        "acceptance_text": build_acceptance_text(document),
        "acceptance_text_hash": expected_acceptance_text_hash(document),
    }


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
    registration_documents = [
        document for document in active_documents if document.doc_type != "recurring_consent"
    ]
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


def is_current_recurring_consent_acceptance(
    db: Session,
    *,
    acceptance: DocumentAcceptance,
    user: User,
    entrypoint_type: str,
    entrypoint_value: str,
    plan_id: uuid.UUID,
    now: datetime | None = None,
) -> bool:
    return _is_current_recurring_consent_acceptance_with_metadata(
        db,
        acceptance=acceptance,
        user=user,
        entrypoint_type=entrypoint_type,
        entrypoint_value=entrypoint_value,
        metadata_key="plan_id",
        metadata_value=str(plan_id),
        now=now,
    )


def is_current_legacy_recurring_consent_acceptance(
    db: Session,
    *,
    acceptance: DocumentAcceptance,
    user: User,
    entrypoint_type: str,
    entrypoint_value: str,
    plan_code: str,
    now: datetime | None = None,
) -> bool:
    """Validate the pre-ANY-327 consent shape for an existing order only."""
    metadata = acceptance.metadata_
    if not isinstance(metadata, dict) or "plan_id" in metadata:
        return False
    return _is_current_recurring_consent_acceptance_with_metadata(
        db,
        acceptance=acceptance,
        user=user,
        entrypoint_type=entrypoint_type,
        entrypoint_value=entrypoint_value,
        metadata_key="plan_code",
        metadata_value=plan_code,
        now=now,
    )


def _is_current_recurring_consent_acceptance_with_metadata(
    db: Session,
    *,
    acceptance: DocumentAcceptance,
    user: User,
    entrypoint_type: str,
    entrypoint_value: str,
    metadata_key: str,
    metadata_value: str,
    now: datetime | None = None,
) -> bool:
    effective_at = now or utc_now()
    comparable_effective_at = _as_utc_naive(effective_at)
    document = get_document_version_by_id(db, acceptance.document_version_id)
    acceptance_event = db.get(LegalAcceptanceEvent, acceptance.legal_acceptance_event_id)
    metadata = acceptance.metadata_
    persisted_metadata_value = metadata.get(metadata_key) if isinstance(metadata, dict) else None
    return not (
        document is None
        or acceptance_event is None
        or document.tenant_id != user.tenant_id
        or document.region != user.region
        or document.doc_type != "recurring_consent"
        or not document.is_active
        or not document.requires_acceptance
        or _as_utc_naive(document.effective_from) > comparable_effective_at
        or acceptance.tenant_id != user.tenant_id
        or acceptance.region != user.region
        or acceptance.user_id != user.id
        or acceptance_event.tenant_id != user.tenant_id
        or acceptance_event.region != user.region
        or acceptance_event.user_id != user.id
        or acceptance.doc_type != "recurring_consent"
        or acceptance.acceptance_kind != AcceptanceKind.RECURRING_CONSENT
        or _as_utc_naive(acceptance_event.accepted_at) > comparable_effective_at
        or acceptance.acceptance_text_hash != expected_acceptance_text_hash(document)
        or acceptance.entrypoint_type != entrypoint_type
        or acceptance.entrypoint_value != entrypoint_value
        or not isinstance(metadata, dict)
        or metadata_key not in metadata
        or not isinstance(persisted_metadata_value, str)
        or persisted_metadata_value != metadata_value
    )


def _as_utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def get_current_recurring_consent_acceptance(
    db: Session,
    *,
    acceptance_id: uuid.UUID,
    user: User,
    entrypoint_type: str,
    entrypoint_value: str,
    plan_id: uuid.UUID,
    now: datetime | None = None,
) -> DocumentAcceptance | None:
    effective_at = now or utc_now()
    acceptance = get_document_acceptance_candidate(
        db,
        acceptance_id=acceptance_id,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        doc_type="recurring_consent",
        acceptance_kind=AcceptanceKind.RECURRING_CONSENT,
        effective_at=effective_at,
    )
    if acceptance is None:
        return None
    if not is_current_recurring_consent_acceptance(
        db,
        acceptance=acceptance,
        user=user,
        entrypoint_type=entrypoint_type,
        entrypoint_value=entrypoint_value,
        plan_id=plan_id,
        now=effective_at,
    ):
        return None
    return acceptance


def create_document_acceptance(
    db: Session,
    *,
    document: DocumentVersion,
    acceptance_event: LegalAcceptanceEvent,
    acceptance_text_hash: str,
    entrypoint_session_id: uuid.UUID | None = None,
    entrypoint_type: str | None = None,
    entrypoint_value: str | None = None,
    source_url: str | None = None,
    metadata: dict[str, Any] | None = None,
    plan_id: uuid.UUID | None = None,
) -> DocumentAcceptance:
    if acceptance_text_hash != expected_acceptance_text_hash(document):
        raise InvalidAcceptanceTextHashError()

    return _create_document_acceptance(
        db,
        document=document,
        acceptance_event=acceptance_event,
        acceptance_text_hash=acceptance_text_hash,
        entrypoint_session_id=entrypoint_session_id,
        entrypoint_type=entrypoint_type,
        entrypoint_value=entrypoint_value,
        source_url=source_url,
        metadata=metadata,
        plan_id=plan_id,
    )


def _create_document_acceptance(
    db: Session,
    *,
    document: DocumentVersion,
    acceptance_event: LegalAcceptanceEvent,
    acceptance_text_hash: str,
    entrypoint_session_id: uuid.UUID | None = None,
    entrypoint_type: str | None = None,
    entrypoint_value: str | None = None,
    source_url: str | None = None,
    metadata: dict[str, Any] | None = None,
    plan_id: uuid.UUID | None = None,
) -> DocumentAcceptance:
    acceptance_metadata = {key: value for key, value in (metadata or {}).items() if key != "plan_id"}
    if document.doc_type == "recurring_consent" and plan_id is not None:
        acceptance_metadata["plan_id"] = str(plan_id)

    acceptance = DocumentAcceptance(
        legal_acceptance_event_id=acceptance_event.id,
        tenant_id=acceptance_event.tenant_id,
        region=acceptance_event.region,
        user_id=acceptance_event.user_id,
        entrypoint_session_id=entrypoint_session_id,
        document_version_id=document.id,
        doc_type=document.doc_type,
        version=document.version,
        acceptance_kind=ACCEPTANCE_KIND_BY_DOC_TYPE.get(document.doc_type, AcceptanceKind.TERMS_ACCEPTANCE),
        accepted_at=acceptance_event.accepted_at,
        ip=acceptance_event.ip,
        user_agent=acceptance_event.user_agent,
        acceptance_text_hash=acceptance_text_hash,
        entrypoint_type=entrypoint_type,
        entrypoint_value=entrypoint_value,
        source_url=source_url,
        metadata_=acceptance_metadata,
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
    plan_id: uuid.UUID | None,
    entrypoint_type: str | None,
    entrypoint_value: str | None,
    source_url: str | None,
    metadata: dict[str, Any],
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

    if document.doc_type == "recurring_consent":
        if plan_id is None or not entrypoint_type or not entrypoint_value:
            raise RecurringConsentContextRequiredError()
        if (
            get_current_sellable_plan(
                db,
                plan_id=plan_id,
                tenant_id=user.tenant_id,
                region=user.region,
                now=utc_now(),
            )
            is None
        ):
            raise RecurringConsentPlanInvalidError()

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
            entrypoint_type=entrypoint_type,
            entrypoint_value=entrypoint_value,
            source_url=source_url,
            metadata=metadata,
            plan_id=plan_id,
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
        doc_type=acceptance.doc_type,
        version=acceptance.version,
        accepted_at=acceptance_event.accepted_at,
    )
    record_legal_acceptance("accepted")
    return result
