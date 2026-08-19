from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.domains.identity.models import User
from app.domains.identity.session import utc_now
from app.models import DocumentAcceptance, DocumentVersion


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


def get_accepted_document_version_ids_for_user(
    db: Session,
    *,
    user: User,
    document_version_ids: list[UUID],
) -> set[UUID]:
    if not document_version_ids:
        return set()

    return {
        row[0]
        for row in db.query(DocumentAcceptance.document_version_id)
        .filter(
            DocumentAcceptance.tenant_id == user.tenant_id,
            DocumentAcceptance.region == user.region,
            DocumentAcceptance.user_id == user.id,
            DocumentAcceptance.document_version_id.in_(document_version_ids),
        )
        .all()
    }
