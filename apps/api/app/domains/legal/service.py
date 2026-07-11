from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.models import DocumentAcceptance, DocumentVersion, User


ACCEPTANCE_KIND_BY_DOC_TYPE = {
    "privacy": "privacy_consent",
    "pd_consent": "privacy_consent",
    "offer": "terms_acceptance",
    "recurring_consent": "recurring_consent",
    "cookies": "cookies",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def hash_acceptance_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_acceptance_text(document: DocumentVersion) -> str:
    return f"Я принимаю документ «{document.title}»."


def expected_acceptance_text_hash(document: DocumentVersion) -> str:
    return hash_acceptance_text(build_acceptance_text(document))


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
    now: datetime | None = None,
) -> list[DocumentVersion]:
    required_documents = get_active_required_documents(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        now=now,
    )
    if not required_documents:
        return []

    accepted_version_ids = {
        row[0]
        for row in db.query(DocumentAcceptance.document_version_id)
        .filter(
            DocumentAcceptance.tenant_id == user.tenant_id,
            DocumentAcceptance.region == user.region,
            DocumentAcceptance.user_id == user.id,
            DocumentAcceptance.document_version_id.in_(
                [document.id for document in required_documents]
            ),
        )
        .all()
    }
    return [
        document
        for document in required_documents
        if document.id not in accepted_version_ids
    ]


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
    accepted_at: datetime | None = None,
) -> DocumentAcceptance:
    acceptance = DocumentAcceptance(
        tenant_id=document.tenant_id,
        region=document.region,
        user_id=user_id,
        guest_id=guest_id,
        entrypoint_session_id=entrypoint_session_id,
        document_version_id=document.id,
        doc_type=document.doc_type,
        version=document.version,
        acceptance_kind=ACCEPTANCE_KIND_BY_DOC_TYPE.get(
            document.doc_type, "terms_acceptance"
        ),
        accepted_at=accepted_at or utc_now(),
        ip=ip,
        user_agent=user_agent,
        acceptance_text_hash=acceptance_text_hash,
        entrypoint_type=entrypoint_type,
        entrypoint_value=entrypoint_value,
        source_url=source_url,
        metadata_=metadata or {},
    )
    db.add(acceptance)
    return acceptance
