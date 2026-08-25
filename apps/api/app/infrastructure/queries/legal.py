from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domains.legal.enums import AcceptanceKind
from app.models import DocumentAcceptance, DocumentVersion


def get_document_acceptance_by_id(
    db: Session, acceptance_id: uuid.UUID, *, for_update: bool = False
) -> DocumentAcceptance | None:
    query = db.query(DocumentAcceptance).filter(DocumentAcceptance.id == acceptance_id)
    return (query.with_for_update() if for_update else query).first()


def get_recurring_consent_acceptance(
    db: Session,
    *,
    acceptance_id: uuid.UUID,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
) -> DocumentAcceptance | None:
    now = utc_now()
    return (
        db.query(DocumentAcceptance)
        .join(DocumentVersion, DocumentVersion.id == DocumentAcceptance.document_version_id)
        .filter(
            DocumentAcceptance.id == acceptance_id,
            DocumentAcceptance.tenant_id == tenant_id,
            DocumentAcceptance.region == region,
            DocumentAcceptance.user_id == user_id,
            DocumentAcceptance.doc_type == "recurring_consent",
            DocumentAcceptance.acceptance_kind == AcceptanceKind.RECURRING_CONSENT.value,
            DocumentAcceptance.accepted_at <= now,
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.region == region,
            DocumentVersion.doc_type == "recurring_consent",
            DocumentVersion.is_active.is_(True),
            DocumentVersion.requires_acceptance.is_(True),
            DocumentVersion.effective_from <= now,
        )
        .first()
    )
