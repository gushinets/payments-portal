from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.generated.legal_manifest import LEGAL_MANIFEST
from app.models import DocumentVersion, LegalEntity


DEFAULT_TENANT_ID = LEGAL_MANIFEST["tenantId"]
RU_LEGAL_ENTITY_ID = uuid.UUID(LEGAL_MANIFEST["legalEntityId"])
LEGAL_PUBLISHED_AT = datetime.fromisoformat(
    LEGAL_MANIFEST["publishedAt"].replace("Z", "+00:00")
)

RU_LEGAL_ENTITY = {
    "id": RU_LEGAL_ENTITY_ID,
    "tenant_id": DEFAULT_TENANT_ID,
    "region": "ru",
    "name": "ИП Говоров Роман Стальевич",
    "entity_type": "individual_entrepreneur",
    "tax_id": "143509640374",
    "registration_id": "314547633100101",
    "legal_address": (
        "630091, Новосибирская область, г. Новосибирск, "
        "Красный пр-кт, дом 45, кв. 30"
    ),
    "support_email": "info@anytoolai.ru",
    "status": "active",
}

RU_DOCUMENT_VERSIONS = [
    {
        "id": uuid.UUID(document["id"]),
        "tenant_id": LEGAL_MANIFEST["tenantId"],
        "region": LEGAL_MANIFEST["region"],
        "legal_entity_id": RU_LEGAL_ENTITY_ID,
        "doc_type": document["docType"],
        "version": document["version"],
        "title": document["title"],
        "url_path": document["urlPath"],
        "content_hash": document["contentHash"],
        "published_at": LEGAL_PUBLISHED_AT,
        "effective_from": LEGAL_PUBLISHED_AT,
        "is_active": True,
        "requires_acceptance": document["requiresAcceptance"],
    }
    for document in LEGAL_MANIFEST["documents"]
]


def seed_legal_documents(db: Session) -> None:
    """Idempotently seed the current legal entity and document metadata."""

    entity = db.get(LegalEntity, RU_LEGAL_ENTITY_ID)
    if entity is None:
        db.add(LegalEntity(**RU_LEGAL_ENTITY))
        db.flush()

    for document_data in RU_DOCUMENT_VERSIONS:
        document = (
            db.query(DocumentVersion)
            .filter(
                DocumentVersion.tenant_id == document_data["tenant_id"],
                DocumentVersion.region == document_data["region"],
                DocumentVersion.doc_type == document_data["doc_type"],
                DocumentVersion.version == document_data["version"],
            )
            .first()
        )
        if document is not None:
            continue

        if document_data["is_active"]:
            active_document = (
                db.query(DocumentVersion)
                .filter(
                    DocumentVersion.tenant_id == document_data["tenant_id"],
                    DocumentVersion.region == document_data["region"],
                    DocumentVersion.doc_type == document_data["doc_type"],
                    DocumentVersion.is_active.is_(True),
                )
                .first()
            )
            if active_document is not None:
                continue

        db.add(DocumentVersion(**document_data))

    db.commit()
