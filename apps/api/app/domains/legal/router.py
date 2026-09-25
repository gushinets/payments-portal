from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import traced
from app.core.settings import settings
from app.domains.legal.acceptance_text import (
    build_acceptance_text,
    expected_acceptance_text_hash,
)
from app.domains.legal.errors import (
    DocumentVersionNotFoundError,
    InvalidAcceptanceTextHashError,
)
from app.domains.legal.service import (
    accept_legal_document,
    get_active_required_documents,
)
from app.http.dependencies import get_current_session
from app.models import AuthSession, DocumentVersion, User

router = APIRouter(prefix="/api/legal", tags=["legal"])


class AcceptDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_version_id: uuid.UUID
    acceptance_text_hash: str = Field(min_length=32, max_length=256)


class RequiredDocumentResponse(BaseModel):
    document_version_id: str
    tenant_id: str
    region: str
    legal_entity_id: str
    doc_type: str
    version: str
    title: str
    url_path: str
    content_hash: str
    published_at: str
    effective_from: str
    requires_acceptance: bool
    acceptance_text: str
    acceptance_text_hash: str


class RequiredDocumentsResponse(BaseModel):
    documents: list[RequiredDocumentResponse]


class AcceptDocumentResponse(BaseModel):
    status: Literal["accepted"]
    acceptance_id: str
    document_version_id: str
    doc_type: str
    version: str
    accepted_at: str


def present_document(document: DocumentVersion) -> RequiredDocumentResponse:
    return RequiredDocumentResponse(
        document_version_id=str(document.id),
        tenant_id=document.tenant_id,
        region=document.region,
        legal_entity_id=str(document.legal_entity_id),
        doc_type=document.doc_type,
        version=document.version,
        title=document.title,
        url_path=document.url_path,
        content_hash=document.content_hash,
        published_at=document.published_at.isoformat(),
        effective_from=document.effective_from.isoformat(),
        requires_acceptance=document.requires_acceptance,
        acceptance_text=build_acceptance_text(document),
        acceptance_text_hash=expected_acceptance_text_hash(document),
    )


@router.get("/required-documents")
def list_required_documents(
    db: Annotated[Session, Depends(get_db)],
) -> RequiredDocumentsResponse:
    documents = get_active_required_documents(
        db,
        tenant_id=settings.instance_tenant_id,
        region=settings.instance_region,
    )
    return RequiredDocumentsResponse(
        documents=[present_document(document) for document in documents],
    )


@router.post("/acceptances")
@traced("legal.acceptance.create")
def accept_document(
    payload: AcceptDocumentRequest,
    request: Request,
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> AcceptDocumentResponse:
    user, _ = current
    try:
        result = accept_legal_document(
            db,
            user=user,
            document_version_id=payload.document_version_id,
            acceptance_text_hash=payload.acceptance_text_hash,
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
    except DocumentVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=exc.code) from exc
    except InvalidAcceptanceTextHashError as exc:
        raise HTTPException(status_code=400, detail=exc.code) from exc

    return AcceptDocumentResponse(
        status="accepted",
        acceptance_id=str(result.acceptance_id),
        document_version_id=str(result.document_version_id),
        doc_type=result.doc_type,
        version=result.version,
        accepted_at=result.accepted_at.isoformat(),
    )
