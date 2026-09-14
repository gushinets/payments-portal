from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import traced
from app.domains.identity.session import (
    DEFAULT_REGION,
    DEFAULT_TENANT_ID,
)
from app.domains.legal.service import (
    LegalAcceptanceError,
    accept_legal_document,
    build_acceptance_text,
    expected_acceptance_text_hash,
    get_active_required_documents,
)
from app.http_dependencies import get_current_session
from app.models import AuthSession, DocumentVersion, User

router = APIRouter(prefix="/api/legal", tags=["legal"])


class AcceptDocumentRequest(BaseModel):
    document_version_id: uuid.UUID
    acceptance_text_hash: str = Field(min_length=32, max_length=256)
    plan_id: uuid.UUID | None = None
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
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[str, Query()] = DEFAULT_TENANT_ID,
    region: Annotated[str, Query()] = DEFAULT_REGION,
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
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
):
    user, _ = current
    try:
        result = accept_legal_document(
            db,
            user=user,
            document_version_id=payload.document_version_id,
            acceptance_text_hash=payload.acceptance_text_hash,
            plan_id=payload.plan_id,
            entrypoint_type=payload.entrypoint_type,
            entrypoint_value=payload.entrypoint_value,
            source_url=payload.source_url,
            metadata=payload.metadata,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except LegalAcceptanceError as exc:
        if exc.code == "document_version_not_found":
            raise HTTPException(status_code=404, detail=exc.code) from exc
        if exc.code in {
            "recurring_consent_context_required",
            "recurring_consent_plan_invalid",
        }:
            raise HTTPException(status_code=400, detail={"code": exc.code}) from exc
        raise HTTPException(status_code=400, detail=exc.code) from exc

    return {
        "status": "accepted",
        "acceptance_id": str(result.acceptance_id),
        "document_version_id": str(result.document_version_id),
        "doc_type": result.doc_type,
        "version": result.version,
        "accepted_at": result.accepted_at.isoformat(),
    }
