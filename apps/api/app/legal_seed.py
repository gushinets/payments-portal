from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.generated.legal_manifest import LEGAL_MANIFEST
from app.models import DocumentVersion, LegalEntity, LegalEntityStatus, LegalEntityType

DEFAULT_TENANT_ID = LEGAL_MANIFEST["tenantId"]
RU_LEGAL_ENTITY_ID = uuid.UUID(LEGAL_MANIFEST["legalEntityId"])
LEGAL_PUBLISHED_AT = datetime.fromisoformat(LEGAL_MANIFEST["publishedAt"])

RU_LEGAL_ENTITY = {
    "id": RU_LEGAL_ENTITY_ID,
    "tenant_id": DEFAULT_TENANT_ID,
    "region": "ru",
    "name": "ИП Говоров Роман Стальевич",
    "entity_type": LegalEntityType.INDIVIDUAL_ENTREPRENEUR,
    "tax_id": "143509640374",
    "registration_id": "314547633100101",
    "legal_address": "630091 , Новосибирская область, г. Новосибирск",
    "support_email": "support@any-tool-ai.ru",
    "status": LegalEntityStatus.ACTIVE,
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

IMMUTABLE_DOCUMENT_VERSION_FIELDS = (
    "id",
    "tenant_id",
    "region",
    "legal_entity_id",
    "doc_type",
    "version",
    "title",
    "url_path",
    "content_hash",
    "published_at",
    "effective_from",
    "requires_acceptance",
)


class LegalDocumentSeedMismatchError(RuntimeError):
    """Raised when a published legal version no longer matches its manifest identity."""


def _comparable_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _document_material_mismatches(
    document: DocumentVersion,
    document_data: dict[str, object],
) -> list[str]:
    mismatches: list[str] = []
    for field in IMMUTABLE_DOCUMENT_VERSION_FIELDS:
        current_value = getattr(document, field)
        expected_value = document_data[field]
        if isinstance(current_value, datetime) and isinstance(expected_value, datetime):
            current_value = _comparable_datetime(current_value)
            expected_value = _comparable_datetime(expected_value)
        if current_value != expected_value:
            mismatches.append(field)
    return mismatches


def seed_legal_documents(db: Session) -> None:
    """Idempotently seed the current legal entity and document metadata."""

    existing_documents: dict[tuple[str, str, str, str], DocumentVersion] = {}
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
        key = (
            str(document_data["tenant_id"]),
            str(document_data["region"]),
            str(document_data["doc_type"]),
            str(document_data["version"]),
        )
        if document is not None:
            mismatches = _document_material_mismatches(document, document_data)
            if mismatches:
                fields = ", ".join(mismatches)
                raise LegalDocumentSeedMismatchError(
                    "legal document seed mismatch for "
                    f"{key[0]}/{key[1]}/{key[2]}/{key[3]}: immutable fields differ: {fields}"
                )
            existing_documents[key] = document

    entity = db.get(LegalEntity, RU_LEGAL_ENTITY_ID)
    if entity is None:
        db.add(LegalEntity(**RU_LEGAL_ENTITY))
        db.flush()
    else:
        for key, value in RU_LEGAL_ENTITY.items():
            if key != "id":
                setattr(entity, key, value)

    for document_data in RU_DOCUMENT_VERSIONS:
        key = (
            str(document_data["tenant_id"]),
            str(document_data["region"]),
            str(document_data["doc_type"]),
            str(document_data["version"]),
        )
        document = existing_documents.get(key)
        if document_data["is_active"]:
            active_documents = (
                db.query(DocumentVersion)
                .filter(
                    DocumentVersion.tenant_id == document_data["tenant_id"],
                    DocumentVersion.region == document_data["region"],
                    DocumentVersion.doc_type == document_data["doc_type"],
                    DocumentVersion.is_active.is_(True),
                )
                .all()
            )
            conflicting_active_documents = [
                active_document
                for active_document in active_documents
                if document is None or active_document.id != document.id
            ]
            for active_document in conflicting_active_documents:
                active_document.is_active = False
            if conflicting_active_documents:
                db.flush()

        if document is None:
            db.add(DocumentVersion(**document_data))
        else:
            document.is_active = bool(document_data["is_active"])

    db.commit()
