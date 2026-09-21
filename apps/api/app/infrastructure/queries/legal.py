from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import (
    AcceptanceKind,
    DocumentAcceptance,
    DocumentVersion,
    LegalAcceptanceEvent,
)


def list_active_required_documents(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    effective_at: datetime,
) -> list[DocumentVersion]:
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


def list_document_acceptance_fingerprints(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
    document_version_ids: list[uuid.UUID],
    accepted_at: datetime,
) -> list[tuple[uuid.UUID, AcceptanceKind, str]]:
    rows = (
        db.query(
            DocumentAcceptance.document_version_id,
            DocumentAcceptance.acceptance_kind,
            DocumentAcceptance.acceptance_text_hash,
        )
        .join(
            LegalAcceptanceEvent,
            LegalAcceptanceEvent.id == DocumentAcceptance.legal_acceptance_event_id,
        )
        .filter(
            DocumentAcceptance.tenant_id == tenant_id,
            DocumentAcceptance.region == region,
            DocumentAcceptance.user_id == user_id,
            DocumentAcceptance.document_version_id.in_(document_version_ids),
            LegalAcceptanceEvent.tenant_id == tenant_id,
            LegalAcceptanceEvent.region == region,
            LegalAcceptanceEvent.user_id == user_id,
            LegalAcceptanceEvent.accepted_at <= accepted_at,
        )
        .all()
    )
    return [(row[0], row[1], row[2]) for row in rows]


def get_document_version_by_id(db: Session, document_version_id: uuid.UUID) -> DocumentVersion | None:
    return db.get(DocumentVersion, document_version_id)


def get_document_acceptance_candidate(
    db: Session,
    *,
    acceptance_id: uuid.UUID,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
    doc_type: str,
    acceptance_kind: AcceptanceKind,
    effective_at: datetime,
) -> DocumentAcceptance | None:
    return (
        db.query(DocumentAcceptance)
        .join(DocumentVersion, DocumentVersion.id == DocumentAcceptance.document_version_id)
        .join(
            LegalAcceptanceEvent,
            LegalAcceptanceEvent.id == DocumentAcceptance.legal_acceptance_event_id,
        )
        .filter(
            DocumentAcceptance.id == acceptance_id,
            DocumentAcceptance.tenant_id == tenant_id,
            DocumentAcceptance.region == region,
            DocumentAcceptance.user_id == user_id,
            DocumentAcceptance.doc_type == doc_type,
            DocumentAcceptance.acceptance_kind == acceptance_kind,
            LegalAcceptanceEvent.tenant_id == tenant_id,
            LegalAcceptanceEvent.region == region,
            LegalAcceptanceEvent.user_id == user_id,
            LegalAcceptanceEvent.accepted_at <= effective_at,
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.region == region,
            DocumentVersion.doc_type == doc_type,
            DocumentVersion.is_active.is_(True),
            DocumentVersion.requires_acceptance.is_(True),
            DocumentVersion.effective_from <= effective_at,
        )
        .first()
    )


def get_active_required_document_by_id(
    db: Session,
    *,
    document_version_id: uuid.UUID,
    tenant_id: str,
    region: str,
    effective_at: datetime,
) -> DocumentVersion | None:
    return (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.id == document_version_id,
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.region == region,
            DocumentVersion.is_active.is_(True),
            DocumentVersion.requires_acceptance.is_(True),
            DocumentVersion.effective_from <= effective_at,
        )
        .first()
    )


def get_document_acceptance_by_id(
    db: Session, acceptance_id: uuid.UUID, *, for_update: bool = False
) -> DocumentAcceptance | None:
    query = db.query(DocumentAcceptance).filter(DocumentAcceptance.id == acceptance_id)
    return (query.with_for_update() if for_update else query).first()
