from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import DocumentVersion, LegalEntity

DEFAULT_TENANT_ID = "anytoolai"
RU_LEGAL_ENTITY_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
LEGAL_PUBLISHED_AT = datetime(2026, 7, 2, tzinfo=timezone.utc)

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
        "id": uuid.UUID("55555555-5555-4555-8555-555555555501"),
        "tenant_id": DEFAULT_TENANT_ID,
        "region": "ru",
        "legal_entity_id": RU_LEGAL_ENTITY_ID,
        "doc_type": "privacy",
        "version": "2026-07-02",
        "title": "Политика в отношении обработки персональных данных",
        "url_path": "/ru/privacy",
        "content_hash": (
            "sha256:3a859b6704b6e35e41eb97cab1daddc7cde9923540eceffbd7d3a08c0045672c"
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
        "version": "2026-07-02",
        "title": "Согласие на обработку персональных данных",
        "url_path": "/ru/consent-personal-data",
        "content_hash": (
            "sha256:645e250d313273dc1488aa1fb7fbf4fe9ae731bea25d33d0025770eef7efba07"
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
        "version": "2026-07-02",
        "title": "Публичная оферта на оказание услуг",
        "url_path": "/ru/offer",
        "content_hash": (
            "sha256:5926ed6905b47b941dade5418354fc89d2f6efc330771548bdde4c102572d5c2"
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
        "version": "2026-07-02",
        "title": "Условия отмены подписки и возврата денежных средств",
        "url_path": "/ru/cancellation",
        "content_hash": (
            "sha256:9790b7cc3a004698a1b0a3d5bea8329450fb78e41bf829fc7d15c40387648c8f"
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
        "version": "2026-07-02",
        "title": "Политика использования файлов cookie",
        "url_path": "/ru/cookies",
        "content_hash": (
            "sha256:2ab4fd889d543c33bbddaead22c1c54843a88db383444043b114de870ec851b4"
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
        "version": "2026-07-02",
        "title": "Политика информационной безопасности",
        "url_path": "/ru/security",
        "content_hash": (
            "sha256:c6730f20a045becb7ad282d453cc7291eec9435a00e6c463d5042f0ca5ec10eb"
        ),
        "published_at": LEGAL_PUBLISHED_AT,
        "effective_from": LEGAL_PUBLISHED_AT,
        "is_active": True,
        "requires_acceptance": False,
    },
]


def seed_legal_documents(db: Session) -> None:
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
        if document is None:
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
