from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import record_legal_acceptance, traced
from app.domains.identity.session import DEFAULT_REGION, DEFAULT_TENANT_ID, get_current_session
from app.domains.legal.service import (
    build_acceptance_text,
    create_document_acceptance,
    expected_acceptance_text_hash,
    get_active_required_documents,
    utc_now,
)
from app.models import AuthSession, DocumentVersion, User

router = APIRouter(prefix="/api/legal", tags=["legal"])


class AcceptDocumentRequest(BaseModel):
    document_version_id: uuid.UUID
    acceptance_text_hash: str = Field(min_length=32, max_length=256)
    entrypoint_type: str | None = None
    entrypoint_value: str | None = None
    source_url: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


def present_document(document: DocumentVersion) -> dict:
    return {
        "document_version_id": str(document.id),
        "tenant_id": document.tenant_id,
        "region": document.region,
        "legal_entity_id": str(document.legal_entity_id),
        "doc_type": document.doc_type,
        "version": document.version,
        "title": document.title,
        "url_path": document.url_path,
        "content_hash": document.content_hash,
        "published_at": document.published_at.isoformat(),
        "effective_from": document.effective_from.isoformat(),
        "requires_acceptance": document.requires_acceptance,
        "acceptance_text": build_acceptance_text(document),
        "acceptance_text_hash": expected_acceptance_text_hash(document),
    }


@router.get("/required-documents")
def list_required_documents(
    tenant_id: str = Query(default=DEFAULT_TENANT_ID),
    region: str = Query(default=DEFAULT_REGION),
    db: Session = Depends(get_db),
):
    documents = get_active_required_documents(
        db,
        tenant_id=tenant_id.strip().lower(),
        region=region.strip().lower(),
    )
    return {"documents": [present_document(document) for document in documents]}


@router.post("/acceptances")
@traced("legal.acceptance.create")
def accept_document(
    payload: AcceptDocumentRequest,
    request: Request,
    current: tuple[User, AuthSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user, _ = current
    document = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.id == payload.document_version_id,
            DocumentVersion.tenant_id == user.tenant_id,
            DocumentVersion.region == user.region,
            DocumentVersion.is_active.is_(True),
            DocumentVersion.requires_acceptance.is_(True),
            DocumentVersion.effective_from <= utc_now(),
        )
        .first()
    )
    if document is None:
        record_legal_acceptance("document_not_found")
        raise HTTPException(status_code=404, detail="document_version_not_found")
    expected_hash = expected_acceptance_text_hash(document)
    if payload.acceptance_text_hash != expected_hash:
        record_legal_acceptance("invalid_text_hash")
        raise HTTPException(status_code=400, detail="invalid_acceptance_text_hash")

    acceptance = create_document_acceptance(
        db,
        document=document,
        user_id=user.id,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        acceptance_text_hash=payload.acceptance_text_hash,
        entrypoint_type=payload.entrypoint_type,
        entrypoint_value=payload.entrypoint_value,
        source_url=payload.source_url,
        metadata=payload.metadata,
    )
    db.commit()
    db.refresh(acceptance)
    record_legal_acceptance("accepted")

    return {
        "status": "accepted",
        "acceptance_id": str(acceptance.id),
        "document_version_id": str(acceptance.document_version_id),
        "doc_type": acceptance.doc_type,
        "version": acceptance.version,
        "accepted_at": acceptance.accepted_at.isoformat(),
    }
