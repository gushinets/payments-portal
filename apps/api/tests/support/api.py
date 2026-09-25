from __future__ import annotations

import uuid
from datetime import datetime, timezone

from apps.api.tests.support.settings import configure_api_test_environment

configure_api_test_environment()

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.database import Base, SessionLocal, engine  # noqa: E402
from app.legal_seed import seed_legal_documents  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import (  # noqa: E402
    DocumentVersion,
    LegalEntity,
    LegalEntityStatus,
    LegalEntityType,
)


app = create_app()
client = TestClient(app)


def reset_api_database() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_legal_documents(db)


def create_legal_entity(
    db: Session,
    *,
    tenant_id: str = "anytoolai",
    region: str = "ru",
) -> LegalEntity:
    entity = LegalEntity(
        tenant_id=tenant_id,
        region=region,
        name=f"AnytoolAI {region.upper()}",
        entity_type=(LegalEntityType.INDIVIDUAL_ENTREPRENEUR if region == "ru" else LegalEntityType.MERCHANT_OF_RECORD),
        legal_address="Draft legal address",
        support_email="support@example.com",
        status=LegalEntityStatus.ACTIVE,
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


def create_document_version(
    db: Session,
    *,
    legal_entity: LegalEntity,
    doc_type: str = "offer",
    version: str = "2026-07-ru-v1",
    title: str = "Публичная оферта",
    is_active: bool = True,
    requires_acceptance: bool = True,
) -> DocumentVersion:
    now = datetime.now(timezone.utc)
    if is_active:
        active_documents = (
            db.query(DocumentVersion)
            .filter(
                DocumentVersion.tenant_id == legal_entity.tenant_id,
                DocumentVersion.region == legal_entity.region,
                DocumentVersion.doc_type == doc_type,
                DocumentVersion.is_active.is_(True),
            )
            .all()
        )
        for active_document in active_documents:
            active_document.is_active = False
        db.flush()
    document = DocumentVersion(
        id=uuid.uuid4(),
        tenant_id=legal_entity.tenant_id,
        region=legal_entity.region,
        legal_entity_id=legal_entity.id,
        doc_type=doc_type,
        version=version,
        title=title,
        url_path=f"/{legal_entity.region}/{doc_type}",
        content_hash=f"sha256:{version}",
        published_at=now,
        effective_from=now,
        is_active=is_active,
        requires_acceptance=requires_acceptance,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def register_test_user(
    *,
    email: str,
    tenant_id: str = "anytoolai",
    region: str = "ru",
) -> str:
    register_response = client.post(
        "/api/auth/register",
        json={
            "tenant_id": tenant_id,
            "region": region,
            "email": email,
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert register_response.status_code == 200, register_response.text
    return register_response.json()["token"]
