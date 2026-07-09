from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["CLOUDPAYMENTS_API_SECRET"] = ""

api_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(api_root))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AuthSession,
    DocumentAcceptance,
    DocumentVersion,
    LegalEntity,
    PaymentWebhookEvent,
    ProductAccessState,
    User,
)


client = TestClient(app)


def setup_function() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def create_legal_entity(db, *, tenant_id: str = "anytoolai", region: str = "ru") -> LegalEntity:
    entity = LegalEntity(
        tenant_id=tenant_id,
        region=region,
        name=f"AnytoolAI {region.upper()}",
        entity_type="individual_entrepreneur" if region == "ru" else "merchant_of_record",
        legal_address="Draft legal address",
        support_email="support@example.com",
        status="active",
    )
    db.add(entity)
    db.commit()
    db.refresh(entity)
    return entity


def create_document_version(
    db,
    *,
    legal_entity: LegalEntity,
    doc_type: str = "offer",
    version: str = "2026-07-ru-v1",
    is_active: bool = True,
    requires_acceptance: bool = True,
) -> DocumentVersion:
    now = datetime.now(timezone.utc)
    document = DocumentVersion(
        id=uuid.uuid4(),
        tenant_id=legal_entity.tenant_id,
        region=legal_entity.region,
        legal_entity_id=legal_entity.id,
        doc_type=doc_type,
        version=version,
        title=f"{doc_type} {version}",
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


def test_healthcheck() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_register_session_and_checkout_intent_flow() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )

    assert register_response.status_code == 200
    register_payload = register_response.json()
    assert register_payload["status"] == "registered"
    assert register_payload["token"]
    assert register_payload["user"]["tenant_id"] == "anytoolai"
    assert register_payload["user"]["region"] == "ru"
    assert register_payload["user"]["user_id"]
    token = register_payload["token"]

    session_response = client.get(
        "/api/auth/session?product=document-summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert session_response.status_code == 200
    session_payload = session_response.json()
    assert session_payload["authenticated"] is True
    assert session_payload["user"]["email"] == "user@example.com"
    assert session_payload["user"]["tenant_id"] == "anytoolai"
    assert session_payload["user"]["region"] == "ru"
    assert session_payload["user"]["user_id"] == register_payload["user"]["user_id"]
    assert session_payload["product_state"]["status"] == "inactive"

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product": "document-summary",
            "plan_code": "document-summary-pro",
            "auto_renew": True,
        },
    )

    assert checkout_response.status_code == 200
    assert checkout_response.json()["product_state"]["status"] == "pending"
    invoice_id = checkout_response.json()["product_state"]["invoice_id"]
    assert invoice_id

    with SessionLocal() as db:
        user = db.query(User).one()
        state = db.query(ProductAccessState).one()

    assert user.email == "user@example.com"
    assert user.tenant_id == "anytoolai"
    assert user.region == "ru"
    assert user.email_normalized == "user@example.com"
    assert state.user_id == user.id
    assert state.product_code == "document-summary"
    assert state.plan_code == "document-summary-pro"
    assert state.status == "pending"
    assert state.last_invoice_id == invoice_id


def test_successful_pay_webhook_is_saved_without_activating_access() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product": "document-summary",
            "plan_code": "document-summary-pro",
            "auto_renew": False,
        },
    )
    invoice_id = checkout_response.json()["product_state"]["invoice_id"]

    webhook_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-success-1",
            "AccountId": "user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Data": {"product_code": "document-summary", "plan_code": "document-summary-pro"},
        },
    )

    assert webhook_response.status_code == 200

    status_response = client.get(
        f"/api/auth/payment-status?invoice_id={invoice_id}&email=user@example.com"
    )
    assert status_response.status_code == 200
    assert status_response.json()["product_state"]["status"] == "pending"
    assert status_response.json()["product_state"]["transaction_id"] is None

    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.endpoint == "pay"
    assert event.invoice_id == invoice_id
    assert event.transaction_id == "tx-success-1"


def test_same_email_can_register_independent_ru_and_eu_accounts() -> None:
    ru_response = client.post(
        "/api/auth/register",
        json={
            "region": "ru",
            "email": "shared@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    eu_response = client.post(
        "/api/auth/register",
        json={
            "region": "eu",
            "email": "shared@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )

    assert ru_response.status_code == 200
    assert eu_response.status_code == 200
    ru_user = ru_response.json()["user"]
    eu_user = eu_response.json()["user"]
    assert ru_user["region"] == "ru"
    assert eu_user["region"] == "eu"
    assert ru_user["email"] == eu_user["email"] == "shared@example.com"
    assert ru_user["user_id"] != eu_user["user_id"]

    with SessionLocal() as db:
        users = (
            db.query(User)
            .filter(User.email_normalized == "shared@example.com")
            .order_by(User.region)
            .all()
        )

    assert len(users) == 2
    assert {user.region for user in users} == {"eu", "ru"}


def test_same_email_cannot_register_twice_in_same_region() -> None:
    payload = {
        "region": "ru",
        "email": "shared@example.com",
        "password": "very-secret-password",
        "personal_consent": True,
        "offer_consent": True,
    }

    first_response = client.post("/api/auth/register", json=payload)
    second_response = client.post("/api/auth/register", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 409


def test_auth_sessions_store_only_token_hash() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]

    with SessionLocal() as db:
        session = db.query(AuthSession).one()

    assert session.token_hash
    assert session.token_hash != token
    assert len(session.token_hash) == 64
    assert not hasattr(session, "token")


def test_login_and_logout_flow() -> None:
    client.post(
        "/api/auth/register",
        json={
            "email": "user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )

    login_response = client.post(
        "/api/auth/login",
        json={
            "email": "user@example.com",
            "password": "very-secret-password",
        },
    )

    assert login_response.status_code == 200
    token = login_response.json()["token"]

    logout_response = client.post(
        "/api/auth/logout",
        headers={"Authorization": f"Bearer {token}"},
        json={},
    )
    assert logout_response.status_code == 200
    assert logout_response.json()["status"] == "logged_out"

    session_response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert session_response.status_code == 401


def test_cloudpayments_webhook_is_saved_without_secret_hmac() -> None:
    response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": "invoice-1",
            "TransactionId": "tx-1",
            "AccountId": "user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}

    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.provider == "cloudpayments"
    assert event.endpoint == "pay"
    assert event.invoice_id == "invoice-1"
    assert event.transaction_id == "tx-1"
    assert event.account_id == "user@example.com"
    assert str(event.amount) == "990.00"
    assert event.currency == "RUB"
    assert event.status == "received"


def test_checkout_requires_acceptance_again_when_active_document_version_changes() -> None:
    with SessionLocal() as db:
        legal_entity = create_legal_entity(db, region="ru")
        first_document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="offer",
            version="2026-07-ru-v1",
        )
        legal_entity_id = legal_entity.id
        first_document_id = first_document.id

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "legal-user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]

    with SessionLocal() as db:
        assert db.query(DocumentAcceptance).count() == 0

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product": "document-summary",
            "plan_code": "document-summary-pro",
            "auto_renew": False,
        },
    )

    assert checkout_response.status_code == 409
    missing_document = checkout_response.json()["detail"]["documents"][0]
    assert checkout_response.json()["detail"]["code"] == "missing_required_documents"
    assert missing_document["document_version_id"] == str(first_document_id)
    assert missing_document["version"] == "2026-07-ru-v1"
    assert missing_document["acceptance_text"]
    assert missing_document["acceptance_text_hash"]

    invalid_accept_response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "document_version_id": str(first_document_id),
            "acceptance_text_hash": "a" * 64,
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
        },
    )

    assert invalid_accept_response.status_code == 400
    assert invalid_accept_response.json()["detail"] == "invalid_acceptance_text_hash"

    accept_first_response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "document_version_id": str(first_document_id),
            "acceptance_text_hash": missing_document["acceptance_text_hash"],
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
        },
    )

    assert accept_first_response.status_code == 200

    retry_first_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product": "document-summary",
            "plan_code": "document-summary-pro",
            "auto_renew": False,
        },
    )

    assert retry_first_response.status_code == 200

    with SessionLocal() as db:
        first_document = db.get(DocumentVersion, first_document_id)
        first_document.is_active = False
        legal_entity = db.get(LegalEntity, legal_entity_id)
        second_document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="offer",
            version="2026-07-ru-v2",
        )
        second_document_id = second_document.id

    checkout_second_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product": "document-summary",
            "plan_code": "document-summary-pro",
            "auto_renew": False,
        },
    )

    assert checkout_second_response.status_code == 409
    second_missing_document = checkout_second_response.json()["detail"]["documents"][0]
    assert checkout_second_response.json()["detail"]["code"] == "missing_required_documents"
    assert second_missing_document["document_version_id"] == str(second_document_id)
    assert second_missing_document["version"] == "2026-07-ru-v2"

    accept_response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "document_version_id": str(second_document_id),
            "acceptance_text_hash": second_missing_document["acceptance_text_hash"],
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
        },
    )

    assert accept_response.status_code == 200

    retry_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product": "document-summary",
            "plan_code": "document-summary-pro",
            "auto_renew": False,
        },
    )

    assert retry_response.status_code == 200
    with SessionLocal() as db:
        acceptances = db.query(DocumentAcceptance).order_by(DocumentAcceptance.accepted_at).all()

    assert len(acceptances) == 2
    assert {acceptance.version for acceptance in acceptances} == {
        "2026-07-ru-v1",
        "2026-07-ru-v2",
    }
    assert not hasattr(acceptances[0], "updated_at")


def test_legal_required_documents_are_scoped_by_tenant_and_region() -> None:
    with SessionLocal() as db:
        ru_entity = create_legal_entity(db, region="ru")
        eu_entity = create_legal_entity(db, region="eu")
        ru_document = create_document_version(
            db,
            legal_entity=ru_entity,
            doc_type="offer",
            version="2026-07-ru-v1",
        )
        eu_document = create_document_version(
            db,
            legal_entity=eu_entity,
            doc_type="offer",
            version="2026-07-eu-v1",
        )
        ru_document_id = ru_document.id
        eu_document_id = eu_document.id

    ru_documents_response = client.get("/api/legal/required-documents?region=ru")
    eu_documents_response = client.get("/api/legal/required-documents?region=eu")

    assert ru_documents_response.status_code == 200
    assert eu_documents_response.status_code == 200
    assert ru_documents_response.json()["documents"][0]["document_version_id"] == str(
        ru_document_id
    )
    assert eu_documents_response.json()["documents"][0]["document_version_id"] == str(
        eu_document_id
    )
    assert ru_documents_response.json()["documents"][0]["acceptance_text_hash"]
    assert eu_documents_response.json()["documents"][0]["acceptance_text_hash"]

    ru_response = client.post(
        "/api/auth/register",
        json={
            "region": "ru",
            "email": "scoped@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    eu_response = client.post(
        "/api/auth/register",
        json={
            "region": "eu",
            "email": "scoped@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )

    assert ru_response.status_code == 200
    assert eu_response.status_code == 200
    ru_token = ru_response.json()["token"]
    eu_token = eu_response.json()["token"]

    with SessionLocal() as db:
        assert db.query(DocumentAcceptance).count() == 0

    ru_accept_response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {ru_token}"},
        json={
            "document_version_id": str(ru_document_id),
            "acceptance_text_hash": ru_documents_response.json()["documents"][0][
                "acceptance_text_hash"
            ],
        },
    )
    eu_accept_response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {eu_token}"},
        json={
            "document_version_id": str(eu_document_id),
            "acceptance_text_hash": eu_documents_response.json()["documents"][0][
                "acceptance_text_hash"
            ],
        },
    )

    assert ru_accept_response.status_code == 200
    assert eu_accept_response.status_code == 200

    with SessionLocal() as db:
        acceptances = db.query(DocumentAcceptance).all()

    assert len(acceptances) == 2
    assert {
        (acceptance.region, acceptance.document_version_id)
        for acceptance in acceptances
    } == {
        ("ru", ru_document_id),
        ("eu", eu_document_id),
    }


def test_cloudpayments_webhook_rejects_invalid_signature_when_secret_is_set() -> None:
    os.environ["CLOUDPAYMENTS_API_SECRET"] = "test-secret"
    app.dependency_overrides.clear()

    from app.settings import settings  # noqa: E402

    object.__setattr__(settings, "cloudpayments_api_secret", "test-secret")

    response = client.post(
        "/api/cloudpayments/pay",
        headers={"Content-HMAC": "invalid-signature"},
        json={
            "InvoiceId": "invoice-2",
            "TransactionId": "tx-2",
            "AccountId": "user@example.com",
            "Amount": "1490.00",
            "Currency": "RUB",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_cloudpayments_signature"

    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.status == "error"
    assert event.error_message == "invalid_cloudpayments_signature"

    object.__setattr__(settings, "cloudpayments_api_secret", "")
    os.environ["CLOUDPAYMENTS_API_SECRET"] = ""
