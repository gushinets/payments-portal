from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import DocumentAcceptance


def get_document_acceptance_by_id(
    db: Session, acceptance_id: uuid.UUID, *, for_update: bool = False
) -> DocumentAcceptance | None:
    query = db.query(DocumentAcceptance).filter(DocumentAcceptance.id == acceptance_id)
    return (query.with_for_update() if for_update else query).first()
