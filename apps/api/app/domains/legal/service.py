from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domains.legal.enums import AcceptanceKind
from app.models import DocumentAcceptance, DocumentVersion, User


ACCEPTANCE_KIND_BY_DOC_TYPE = {
    "privacy": AcceptanceKind.PRIVACY_CONSENT.value,
    "pd_consent": AcceptanceKind.PRIVACY_CONSENT.value,
    "offer": AcceptanceKind.TERMS_ACCEPTANCE.value,
    "recurring_consent": AcceptanceKind.RECURRING_CONSENT.value,
    "cookies": AcceptanceKind.COOKIES.value,
}


class LegalAcceptanceError(ValueError):
    """Raised when a legal acceptance cannot be recorded safely."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def hash_acceptance_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_acceptance_text(document: DocumentVersion) -> str:
    return f"Я принимаю документ «{document.title}»."


def expected_acceptance_text_hash(document: DocumentVersion) -> str:
    return hash_acceptance_text(build_acceptance_text(document))


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
    return (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.region == region,
            DocumentVersion.is_active.is_(True),
            DocumentVersion.requires_acceptance.is_(True),
            DocumentVersion.effective_from <= effective_at,
        )
        .order_by(DocumentVersion.doc_type.asc(), DocumentVersion.published_at.desc())
        .all()
    )


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

    accepted_version_kinds = {
        (row[0], row[1], row[2])
        for row in db.query(
            DocumentAcceptance.document_version_id,
            DocumentAcceptance.acceptance_kind,
            DocumentAcceptance.acceptance_text_hash,
        )
        .filter(
            DocumentAcceptance.tenant_id == user.tenant_id,
            DocumentAcceptance.region == user.region,
            DocumentAcceptance.user_id == user.id,
            DocumentAcceptance.document_version_id.in_([document.id for document in required_documents]),
            DocumentAcceptance.accepted_at <= effective_at,
        )
        .all()
    }
    return [
        document
        for document in required_documents
        if (
            document.id,
            ACCEPTANCE_KIND_BY_DOC_TYPE.get(document.doc_type, "terms_acceptance"),
            expected_acceptance_text_hash(document),
        )
        not in accepted_version_kinds
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
    effective_at = now or utc_now()
    comparable_effective_at = _as_utc_naive(effective_at)
    document = db.get(DocumentVersion, acceptance.document_version_id)
    metadata = acceptance.metadata_
    metadata_plan_id = metadata.get("plan_id") if isinstance(metadata, dict) else None
    return not (
        document is None
        or document.tenant_id != user.tenant_id
        or document.region != user.region
        or document.doc_type != "recurring_consent"
        or not document.is_active
        or not document.requires_acceptance
        or _as_utc_naive(document.effective_from) > comparable_effective_at
        or acceptance.tenant_id != user.tenant_id
        or acceptance.region != user.region
        or acceptance.user_id != user.id
        or acceptance.doc_type != "recurring_consent"
        or acceptance.acceptance_kind != AcceptanceKind.RECURRING_CONSENT.value
        or _as_utc_naive(acceptance.accepted_at) > comparable_effective_at
        or acceptance.acceptance_text_hash != expected_acceptance_text_hash(document)
        or acceptance.entrypoint_type != entrypoint_type
        or acceptance.entrypoint_value != entrypoint_value
        or not isinstance(metadata, dict)
        or "plan_id" not in metadata
        or not isinstance(metadata_plan_id, str)
        or metadata_plan_id != str(plan_id)
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
    acceptance = (
        db.query(DocumentAcceptance)
        .join(DocumentVersion, DocumentVersion.id == DocumentAcceptance.document_version_id)
        .filter(
            DocumentAcceptance.id == acceptance_id,
            DocumentAcceptance.tenant_id == user.tenant_id,
            DocumentAcceptance.region == user.region,
            DocumentAcceptance.user_id == user.id,
            DocumentAcceptance.doc_type == "recurring_consent",
            DocumentAcceptance.acceptance_kind == AcceptanceKind.RECURRING_CONSENT.value,
            DocumentAcceptance.accepted_at <= effective_at,
            DocumentVersion.tenant_id == user.tenant_id,
            DocumentVersion.region == user.region,
            DocumentVersion.doc_type == "recurring_consent",
            DocumentVersion.is_active.is_(True),
            DocumentVersion.requires_acceptance.is_(True),
            DocumentVersion.effective_from <= effective_at,
        )
        .first()
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
    acceptance_text_hash: str,
    user_id: uuid.UUID | None = None,
    guest_id: str | None = None,
    entrypoint_session_id: uuid.UUID | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
    entrypoint_type: str | None = None,
    entrypoint_value: str | None = None,
    source_url: str | None = None,
    metadata: dict[str, Any] | None = None,
    plan_id: uuid.UUID | None = None,
    accepted_at: datetime | None = None,
) -> DocumentAcceptance:
    if acceptance_text_hash != expected_acceptance_text_hash(document):
        raise LegalAcceptanceError("invalid_acceptance_text_hash")

    acceptance_metadata = {key: value for key, value in (metadata or {}).items() if key != "plan_id"}
    if document.doc_type == "recurring_consent" and plan_id is not None:
        acceptance_metadata["plan_id"] = str(plan_id)

    acceptance = DocumentAcceptance(
        tenant_id=document.tenant_id,
        region=document.region,
        user_id=user_id,
        guest_id=guest_id,
        entrypoint_session_id=entrypoint_session_id,
        document_version_id=document.id,
        doc_type=document.doc_type,
        version=document.version,
        acceptance_kind=ACCEPTANCE_KIND_BY_DOC_TYPE.get(document.doc_type, "terms_acceptance"),
        accepted_at=accepted_at or utc_now(),
        ip=ip,
        user_agent=user_agent,
        acceptance_text_hash=acceptance_text_hash,
        entrypoint_type=entrypoint_type,
        entrypoint_value=entrypoint_value,
        source_url=source_url,
        metadata_=acceptance_metadata,
    )
    db.add(acceptance)
    return acceptance
