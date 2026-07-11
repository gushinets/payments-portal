from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.generated.legal_manifest import LEGAL_MANIFEST
from app.models import DocumentVersion, LegalEntity

<<<<<<< HEAD

DEFAULT_TENANT_ID = LEGAL_MANIFEST["tenantId"]
RU_LEGAL_ENTITY_ID = uuid.UUID(LEGAL_MANIFEST["legalEntityId"])
LEGAL_PUBLISHED_AT = datetime.fromisoformat(
    LEGAL_MANIFEST["publishedAt"].replace("Z", "+00:00")
)
=======
DEFAULT_TENANT_ID = "anytoolai"
RU_LEGAL_ENTITY_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
LEGAL_PUBLISHED_AT = datetime(2026, 7, 11, tzinfo=timezone.utc)
>>>>>>> 8468fa5 (ANY-91 / Visual refinements and document edits)

RU_LEGAL_ENTITY = {
    "id": RU_LEGAL_ENTITY_ID,
    "tenant_id": DEFAULT_TENANT_ID,
    "region": "ru",
    "name": "ИП Говоров Роман Стальевич",
    "entity_type": "individual_entrepreneur",
    "tax_id": "143509640374",
    "registration_id": "314547633100101",
    "legal_address": "630091 , Новосибирская область, г. Новосибирск",
    "support_email": "support@any-tool-ai.ru",
    "status": "active",
}

RU_DOCUMENT_VERSIONS = [
    {
        "id": uuid.UUID(document["id"]),
        "tenant_id": LEGAL_MANIFEST["tenantId"],
        "region": LEGAL_MANIFEST["region"],
        "legal_entity_id": RU_LEGAL_ENTITY_ID,
<<<<<<< HEAD
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
=======
        "doc_type": "privacy",
        "version": "2026-07-11",
        "title": "Политика в отношении обработки персональных данных",
        "url_path": "/ru/privacy",
        "content_hash": (
            "sha256:9ebe8daf5d7a833e32f738f9d60e145f02f1bdaa817df744cf14f22dbba9c50c"
        ),
        "published_at": LEGAL_PUBLISHED_AT,
        "effective_from": LEGAL_PUBLISHED_AT,
        "is_active": True,
        "requires_acceptance": True,
    },
    {
        "id": uuid.UUID("55555555-5555-4555-8555-555555555502"),
        "tenant_id": DEFAULT_TENANT_ID,
        "region": "ru",
        "legal_entity_id": RU_LEGAL_ENTITY_ID,
        "doc_type": "pd_consent",
        "version": "2026-07-11",
        "title": "Согласие на обработку персональных данных",
        "url_path": "/ru/consent-personal-data",
        "content_hash": (
            "sha256:52081466de8af8108508710d48523bd873079cd91bfc2ca453ad6416a83a34c3"
        ),
        "published_at": LEGAL_PUBLISHED_AT,
        "effective_from": LEGAL_PUBLISHED_AT,
        "is_active": True,
        "requires_acceptance": True,
    },
    {
        "id": uuid.UUID("55555555-5555-4555-8555-555555555503"),
        "tenant_id": DEFAULT_TENANT_ID,
        "region": "ru",
        "legal_entity_id": RU_LEGAL_ENTITY_ID,
        "doc_type": "offer",
        "version": "2026-07-11",
        "title": "Публичная оферта на оказание услуг",
        "url_path": "/ru/offer",
        "content_hash": (
            "sha256:81966788e83843a11ab0c1803c8a8368a2db2e5dc2edd965ec1269abf802a64f"
        ),
        "published_at": LEGAL_PUBLISHED_AT,
        "effective_from": LEGAL_PUBLISHED_AT,
        "is_active": True,
        "requires_acceptance": True,
    },
    {
        "id": uuid.UUID("55555555-5555-4555-8555-555555555504"),
        "tenant_id": DEFAULT_TENANT_ID,
        "region": "ru",
        "legal_entity_id": RU_LEGAL_ENTITY_ID,
        "doc_type": "cancellation",
        "version": "2026-07-11",
        "title": "Условия отмены подписки и возврата денежных средств",
        "url_path": "/ru/cancellation",
        "content_hash": (
            "sha256:134233cb13bfb4470a1a26909355333eb85432ca230b4df4bb578f3722186504"
        ),
        "published_at": LEGAL_PUBLISHED_AT,
        "effective_from": LEGAL_PUBLISHED_AT,
        "is_active": True,
        "requires_acceptance": False,
    },
    {
        "id": uuid.UUID("55555555-5555-4555-8555-555555555505"),
        "tenant_id": DEFAULT_TENANT_ID,
        "region": "ru",
        "legal_entity_id": RU_LEGAL_ENTITY_ID,
        "doc_type": "cookies",
        "version": "2026-07-11",
        "title": "Политика использования файлов cookie",
        "url_path": "/ru/cookies",
        "content_hash": (
            "sha256:bdc9e4da60fe18fb9ec072a52c07d3d79103bb641aef903cda8db38a6b38b571"
        ),
        "published_at": LEGAL_PUBLISHED_AT,
        "effective_from": LEGAL_PUBLISHED_AT,
        "is_active": True,
        "requires_acceptance": False,
    },
    {
        "id": uuid.UUID("55555555-5555-4555-8555-555555555506"),
        "tenant_id": DEFAULT_TENANT_ID,
        "region": "ru",
        "legal_entity_id": RU_LEGAL_ENTITY_ID,
        "doc_type": "security",
        "version": "2026-07-11",
        "title": "Политика информационной безопасности",
        "url_path": "/ru/security",
        "content_hash": (
            "sha256:686c159832728cbe7b0b199e21a68f93e435402746eb667c3a4aee14f949d7ed"
        ),
        "published_at": LEGAL_PUBLISHED_AT,
        "effective_from": LEGAL_PUBLISHED_AT,
        "is_active": True,
        "requires_acceptance": False,
    },
>>>>>>> 8468fa5 (ANY-91 / Visual refinements and document edits)
]


def seed_legal_documents(db: Session) -> None:
    """Idempotently seed the current legal entity and document metadata."""

    entity = db.get(LegalEntity, RU_LEGAL_ENTITY_ID)
    if entity is None:
        db.add(LegalEntity(**RU_LEGAL_ENTITY))
        db.flush()
    else:
        for key, value in RU_LEGAL_ENTITY.items():
            if key != "id":
                setattr(entity, key, value)

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
<<<<<<< HEAD
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
=======
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
            for active_document in active_documents:
                if document is None or active_document.id != document.id:
                    active_document.is_active = False

        if document is None:
            db.add(DocumentVersion(**document_data))
        else:
            for key, value in document_data.items():
                if key != "id":
                    setattr(document, key, value)
>>>>>>> 8468fa5 (ANY-91 / Visual refinements and document edits)

    db.commit()
