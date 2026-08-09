from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["CLOUDPAYMENTS_API_SECRET"] = ""
os.environ["CLOUDPAYMENTS_PUBLIC_ID"] = "pk_test_provider"
os.environ["SKIP_LEGAL_SEED"] = "true"

api_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(api_root))

from fastapi.testclient import TestClient  # noqa: E402
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware  # noqa: E402

import app.domains.identity.password_reset as password_reset_router  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.integrations.cloudpayments import adapter as cloudpayments_adapter_module  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AuthSession,
    Bundle,
    BundleProduct,
    DocumentAcceptance,
    DocumentVersion,
    LegalEntity,
    MagicLinkToken,
    Order,
    OrderItem,
    Payment,
    PaymentProviderAccount,
    PaymentWebhookEvent,
    Plan,
    PasswordResetRateLimit,
    ProductAccessState,
    Product,
    Refund,
    User,
)
from app.legal_seed import RU_DOCUMENT_VERSIONS, seed_legal_documents  # noqa: E402
from app.integrations.cloudpayments.adapter import (  # noqa: E402
    _event_idempotency_key,
    verify_cloudpayments_signature,
)
from app.integrations.cloudpayments.payload import (  # noqa: E402
    get_first,
    normalized_recurrent_status,
    parse_bool,
    parse_int,
)
from app.settings import settings  # noqa: E402


client = TestClient(app)
_original_verify_cloudpayments_signature = verify_cloudpayments_signature


def _verified_webhook_for_test(raw_body: bytes, headers: dict[str, str]) -> bool:
    return True


def allow_unsigned_cloudpayments_webhooks_for_test() -> None:
    cloudpayments_adapter_module.verify_cloudpayments_signature = _verified_webhook_for_test


def require_signed_cloudpayments_webhooks_for_test() -> None:
    cloudpayments_adapter_module.verify_cloudpayments_signature = (
        _original_verify_cloudpayments_signature
    )


def teardown_function() -> None:
    require_signed_cloudpayments_webhooks_for_test()


def cloudpayments_signature(raw_body: bytes, secret: str = "test-secret") -> str:
    return base64.b64encode(
        hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()
    ).decode("ascii")


def signed_cloudpayments_post(endpoint: str, payload: bytes, *, secret: str = "test-secret"):
    return client.post(
        f"/api/cloudpayments/{endpoint}",
        headers={
            "Content-HMAC": cloudpayments_signature(payload, secret),
            "Content-Type": "application/json",
        },
        content=payload,
    )


def create_checkout_invoice(
    *,
    email: str,
    product: str = "document-summary",
    plan_code: str = "document-summary-pro",
    widget_mode: str = "charge",
) -> str:
    if widget_mode != "charge":
        seed_cloudpayments_provider_account(widget_mode=widget_mode)
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert register_response.status_code == 200, register_response.text
    token = register_response.json()["token"]
    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "product": product,
            "plan_code": plan_code,
            "auto_renew": False,
        },
    )
    assert checkout_response.status_code == 200, checkout_response.text
    return checkout_response.json()["product_state"]["invoice_id"]


def seed_cloudpayments_provider_account(
    *,
    widget_mode: str = "charge",
    enabled: bool = True,
) -> None:
    with SessionLocal() as db:
        account = (
            db.query(PaymentProviderAccount)
            .filter(
                PaymentProviderAccount.tenant_id == "anytoolai",
                PaymentProviderAccount.region == "ru",
                PaymentProviderAccount.provider == "cloudpayments",
            )
            .first()
        )
        if account is None:
            account = PaymentProviderAccount(
                tenant_id="anytoolai",
                region="ru",
                provider="cloudpayments",
                public_identifier="pk_test_provider",
                default_currency="RUB",
                enabled=enabled,
                test_mode=True,
                config={"widget_mode": widget_mode},
            )
        else:
            account.enabled = enabled
            account.config = {**account.config, "widget_mode": widget_mode}
        db.add(account)
        db.commit()


def setup_function() -> None:
    allow_unsigned_cloudpayments_webhooks_for_test()
    object.__setattr__(settings, "cloudpayments_enabled", False)
    object.__setattr__(settings, "cloudpayments_api_secret", "")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_catalog(db)


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
    title: str = "Публичная оферта",
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


def seed_catalog(db) -> dict[str, object]:
    existing_document_plan = (
        db.query(Plan)
        .filter(
            Plan.tenant_id == "anytoolai",
            Plan.region == "ru",
            Plan.code == "document-summary-pro",
        )
        .first()
    )
    existing_bundle_plan = (
        db.query(Plan)
        .filter(
            Plan.tenant_id == "anytoolai",
            Plan.region == "ru",
            Plan.code == "core-tools-bundle-pro-ru",
        )
        .first()
    )
    existing_prompt_plan = (
        db.query(Plan)
        .filter(
            Plan.tenant_id == "anytoolai",
            Plan.region == "ru",
            Plan.code == "prompt-optimizer-pro",
        )
        .first()
    )
    existing_all_access_plan = (
        db.query(Plan)
        .filter(
            Plan.tenant_id == "anytoolai",
            Plan.region == "ru",
            Plan.code == "all-access-pro-ru",
        )
        .first()
    )
    existing_document_summary = (
        db.query(Product)
        .filter(Product.tenant_id == "anytoolai", Product.code == "document-summary")
        .first()
    )
    existing_prompt_optimizer = (
        db.query(Product)
        .filter(Product.tenant_id == "anytoolai", Product.code == "prompt-optimizer")
        .first()
    )
    existing_bundle = (
        db.query(Bundle)
        .filter(Bundle.tenant_id == "anytoolai", Bundle.code == "core-tools-bundle")
        .first()
    )
    if (
        existing_document_plan is not None
        and existing_bundle_plan is not None
        and existing_prompt_plan is not None
        and existing_all_access_plan is not None
        and existing_document_summary is not None
        and existing_prompt_optimizer is not None
        and existing_bundle is not None
    ):
        return {
            "document_summary": existing_document_summary,
            "prompt_optimizer": existing_prompt_optimizer,
            "bundle": existing_bundle,
            "document_plan": existing_document_plan,
            "prompt_plan": existing_prompt_plan,
            "bundle_plan": existing_bundle_plan,
            "all_access_plan": existing_all_access_plan,
        }

    document_summary = Product(
        tenant_id="anytoolai",
        code="document-summary",
        platform_product_id="document-summary",
        name="Document Summary",
        status="active",
    )
    prompt_optimizer = Product(
        tenant_id="anytoolai",
        code="prompt-optimizer",
        platform_product_id="prompt-optimizer",
        name="Prompt Optimizer",
        status="active",
    )
    bundle = Bundle(
        tenant_id="anytoolai",
        code="core-tools-bundle",
        name="Core Tools Bundle",
        status="active",
    )
    db.add_all([document_summary, prompt_optimizer, bundle])
    db.flush()
    db.add_all(
        [
            BundleProduct(
                tenant_id="anytoolai",
                bundle_id=bundle.id,
                product_id=document_summary.id,
                status="active",
            ),
            BundleProduct(
                tenant_id="anytoolai",
                bundle_id=bundle.id,
                product_id=prompt_optimizer.id,
                status="active",
            ),
        ]
    )
    document_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="document-summary-pro",
        name="Document Summary Pro",
        scope_type="product",
        product_id=document_summary.id,
        price_amount_minor=99000,
        currency="RUB",
        billing_period="month",
        renewal_mode="manual",
        trial_days=7,
        status="active",
    )
    prompt_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="prompt-optimizer-pro",
        name="Prompt Optimizer Pro",
        scope_type="product",
        product_id=prompt_optimizer.id,
        price_amount_minor=99000,
        currency="RUB",
        billing_period="month",
        renewal_mode="manual",
        trial_days=7,
        status="active",
    )
    bundle_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="core-tools-bundle-pro-ru",
        name="Core Tools Bundle Pro RU",
        scope_type="bundle",
        bundle_id=bundle.id,
        price_amount_minor=198000,
        currency="RUB",
        billing_period="month",
        renewal_mode="manual",
        trial_days=7,
        status="active",
    )
    all_access_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="all-access-pro-ru",
        name="All Access Pro RU",
        scope_type="all_access",
        price_amount_minor=198000,
        currency="RUB",
        billing_period="month",
        renewal_mode="manual",
        trial_days=7,
        status="active",
        metadata_={"included_product_codes": ["document-summary", "prompt-optimizer"]},
    )
    db.add_all([document_plan, prompt_plan, bundle_plan, all_access_plan])
    db.commit()
    return {
        "document_summary": document_summary,
        "prompt_optimizer": prompt_optimizer,
        "bundle": bundle,
        "document_plan": document_plan,
        "prompt_plan": prompt_plan,
        "bundle_plan": bundle_plan,
        "all_access_plan": all_access_plan,
    }


def test_healthcheck() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_liveness_readiness_metrics_and_request_id() -> None:
    request_id = "agent-check-123"
    live_response = client.get("/health/live", headers={"X-Request-ID": request_id})
    ready_response = client.get("/health/ready")
    metrics_response = client.get("/metrics")

    assert live_response.status_code == 200
    assert live_response.headers["X-Request-ID"] == request_id
    assert live_response.json() == {"status": "ok"}
    assert ready_response.status_code == 200
    assert ready_response.json() == {"status": "ready"}
    assert ready_response.headers["X-Request-ID"]
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain")


def test_invalid_request_id_is_replaced() -> None:
    response = client.get("/health/live", headers={"X-Request-ID": "invalid request id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "invalid request id"
    assert len(response.headers["X-Request-ID"]) == 32


def test_seeded_legal_documents_block_checkout_on_fresh_database() -> None:
    with SessionLocal() as db:
        seed_legal_documents(db)

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "seeded-legal@example.com",
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

    assert checkout_response.status_code == 409
    missing_documents = checkout_response.json()["detail"]["documents"]
    required_seeded_types = {
        document["doc_type"]
        for document in RU_DOCUMENT_VERSIONS
        if document["requires_acceptance"]
    }
    assert {document["doc_type"] for document in missing_documents} == required_seeded_types


def test_legal_seed_replaces_existing_active_document_type() -> None:
    with SessionLocal() as db:
        legal_entity = create_legal_entity(db, region="ru")
        existing_offer = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="offer",
            version="2026-07-custom",
        )
        existing_offer_id = existing_offer.id

        seed_legal_documents(db)

        offers = (
            db.query(DocumentVersion)
            .filter(
                DocumentVersion.tenant_id == "anytoolai",
                DocumentVersion.region == "ru",
                DocumentVersion.doc_type == "offer",
                DocumentVersion.is_active.is_(True),
            )
            .all()
        )
        seeded_documents_count = (
            db.query(DocumentVersion)
            .filter(DocumentVersion.version == "2026-07-11")
            .count()
        )
        db.refresh(existing_offer)

    assert existing_offer.is_active is False
    assert [offer.id for offer in offers] == [
        RU_DOCUMENT_VERSIONS[2]["id"],
    ]
    assert seeded_documents_count == len(RU_DOCUMENT_VERSIONS)


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
    checkout_payload = checkout_response.json()
    assert checkout_payload["product_state"]["status"] == "pending"
    assert checkout_payload["checkout"]["amount_minor"] == 99000
    assert checkout_payload["checkout"]["amount"] == 990.0
    assert checkout_payload["checkout"]["currency"] == "RUB"
    assert checkout_payload["checkout"]["action"] == {
        "provider": "cloudpayments",
        "experience": "widget",
        "mode": "charge",
        "public_identifier": "pk_test_provider",
        "amount_minor": 99000,
        "amount": 990.0,
        "currency": "RUB",
        "merchant_order_id": checkout_payload["product_state"]["invoice_id"],
        "provider_invoice_id": checkout_payload["product_state"]["invoice_id"],
        "account_id": "user@example.com",
        "description": "Document Summary Pro",
        "metadata": {
            "product_code": "document-summary",
            "plan_code": "document-summary-pro",
        },
    }
    invoice_id = checkout_payload["product_state"]["invoice_id"]
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


def test_checkout_rejects_missing_cloudpayments_public_terminal_id() -> None:
    from app.core.settings import settings

    previous_public_id = settings.cloudpayments_public_id
    object.__setattr__(settings, "cloudpayments_public_id", "")
    try:
        register_response = client.post(
            "/api/auth/register",
            json={
                "email": "missing-terminal@example.com",
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

        assert checkout_response.status_code == 409
        assert checkout_response.json()["detail"] == "cloudpayments_public_terminal_id_missing"
        with SessionLocal() as db:
            assert db.query(Order).count() == 0
            assert db.query(OrderItem).count() == 0
            assert db.query(ProductAccessState).count() == 0
    finally:
        object.__setattr__(settings, "cloudpayments_public_id", previous_public_id)


def test_checkout_supports_two_stage_cloudpayments_widget_mode() -> None:
    with SessionLocal() as db:
        db.add(
            PaymentProviderAccount(
                tenant_id="anytoolai",
                region="ru",
                provider="cloudpayments",
                public_identifier="pk_test_provider",
                default_currency="RUB",
                enabled=True,
                test_mode=True,
                config={"widget_mode": "auth"},
            )
        )
        db.commit()

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "auth-mode@example.com",
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

    assert checkout_response.status_code == 200
    assert checkout_response.json()["checkout"]["action"]["mode"] == "auth"
    with SessionLocal() as db:
        order = db.query(Order).one()
        assert order.metadata_["payment_mode"] == "auth"
        assert db.query(OrderItem).count() == 1
        assert db.query(ProductAccessState).count() == 1


def test_checkout_rejects_plan_provider_currency_mismatch() -> None:
    with SessionLocal() as db:
        plan = (
            db.query(Plan)
            .filter(
                Plan.tenant_id == "anytoolai",
                Plan.region == "ru",
                Plan.code == "document-summary-pro",
            )
            .one()
        )
        plan.currency = "EUR"
        db.add(
            PaymentProviderAccount(
                tenant_id="anytoolai",
                region="ru",
                provider="cloudpayments",
                default_currency="RUB",
                enabled=True,
                test_mode=True,
                config={},
            )
        )
        db.commit()

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "currency-mismatch@example.com",
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

    assert checkout_response.status_code == 409
    assert checkout_response.json()["detail"] == "provider_currency_mismatch"
    with SessionLocal() as db:
        assert db.query(Order).count() == 0
        assert db.query(OrderItem).count() == 0
        assert db.query(ProductAccessState).count() == 0


def test_bundle_checkout_snapshots_one_sellable_catalog_plan() -> None:
    with SessionLocal() as db:
        catalog = seed_catalog(db)
        bundle_plan_id = catalog["bundle_plan"].id
        bundle_id = catalog["bundle"].id

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "bundle-user@example.com",
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
            "product": "core-tools-bundle",
            "plan_code": "core-tools-bundle-pro-ru",
            "entrypoint_type": "bundle",
            "auto_renew": True,
        },
    )

    assert checkout_response.status_code == 200
    invoice_id = checkout_response.json()["product_state"]["invoice_id"]
    assert invoice_id.startswith("core-tools-bundle-")

    with SessionLocal() as db:
        order = db.query(Order).one()
        item = db.query(OrderItem).one()

    assert order.plan_id == bundle_plan_id
    assert order.amount_minor == 198000
    assert item.item_type == "bundle_plan"
    assert item.plan_id == bundle_plan_id
    assert item.bundle_id == bundle_id
    assert item.product_id is None
    assert item.product_code_snapshot is None
    assert item.plan_code_snapshot == "core-tools-bundle-pro-ru"
    assert item.amount_minor == 198000
    assert item.trial_days_snapshot == 7


def test_all_access_checkout_snapshots_one_sellable_catalog_plan() -> None:
    with SessionLocal() as db:
        catalog = seed_catalog(db)
        all_access_plan_id = catalog["all_access_plan"].id

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "all-access-user@example.com",
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
            "product": "all-access",
            "plan_code": "all-access-pro-ru",
            "entrypoint_type": "catalog",
            "auto_renew": True,
        },
    )

    assert checkout_response.status_code == 200
    product_state = checkout_response.json()["product_state"]
    assert product_state["invoice_id"].startswith("all-access-")
    assert product_state["plan_code"] == "all-access-pro-ru"

    with SessionLocal() as db:
        order = db.query(Order).one()
        item = db.query(OrderItem).one()

    assert order.plan_id == all_access_plan_id
    assert order.amount_minor == 198000
    assert item.item_type == "all_access_plan"
    assert item.plan_id == all_access_plan_id
    assert item.bundle_id is None
    assert item.product_id is None
    assert item.product_code_snapshot is None
    assert item.plan_code_snapshot == "all-access-pro-ru"
    assert item.amount_minor == 198000
    assert item.trial_days_snapshot == 7


def test_checkout_rejects_inactive_catalog_plan_without_legacy_fallback() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.status = "inactive"
        db.add(plan)
        db.commit()

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "inactive-plan-user@example.com",
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

    assert checkout_response.status_code == 400
    assert checkout_response.json()["detail"] == "unknown_product_plan"
    with SessionLocal() as db:
        assert db.query(Order).count() == 0


def test_checkout_rejects_catalog_plan_outside_validity_window() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        now = datetime.now(timezone.utc)
        plan.valid_from = now - timedelta(days=30)
        plan.valid_to = now - timedelta(seconds=1)
        db.add(plan)
        db.commit()

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "expired-plan-user@example.com",
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

    assert checkout_response.status_code == 400
    assert checkout_response.json()["detail"] == "unknown_product_plan"
    with SessionLocal() as db:
        assert db.query(Order).count() == 0


def test_checkout_rejects_active_plan_for_inactive_product() -> None:
    with SessionLocal() as db:
        product = db.query(Product).filter(Product.code == "document-summary").one()
        product.status = "inactive"
        db.add(product)
        db.commit()

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "inactive-product-user@example.com",
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

    assert checkout_response.status_code == 400
    assert checkout_response.json()["detail"] == "unknown_product_plan"
    with SessionLocal() as db:
        assert db.query(Order).count() == 0


def test_checkout_rejects_active_plan_for_inactive_bundle() -> None:
    with SessionLocal() as db:
        bundle = db.query(Bundle).filter(Bundle.code == "core-tools-bundle").one()
        bundle.status = "inactive"
        db.add(bundle)
        db.commit()

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "inactive-bundle-user@example.com",
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
            "product": "core-tools-bundle",
            "plan_code": "core-tools-bundle-pro-ru",
            "entrypoint_type": "bundle",
            "auto_renew": True,
        },
    )

    assert checkout_response.status_code == 400
    assert checkout_response.json()["detail"] == "unknown_product_plan"
    with SessionLocal() as db:
        assert db.query(Order).count() == 0


def test_pay_webhook_amount_mismatch_is_failed_without_order_update() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "mismatch-user@example.com",
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
            "TransactionId": "tx-amount-mismatch",
            "AccountId": "mismatch-user@example.com",
            "Amount": "9.90",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    assert webhook_response.status_code == 200
    assert webhook_response.json() == {"code": 0}
    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()
        order = db.query(Order).one()

    assert event.status == "failed"
    assert event.error_code == "amount_mismatch"
    assert order.status == "pending_payment"
    assert db.query(Payment).count() == 0


def test_signed_check_webhook_validates_order_before_acknowledging() -> None:
    from app.settings import settings  # noqa: E402

    require_signed_cloudpayments_webhooks_for_test()
    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", "test-secret")
    try:
        register_response = client.post(
            "/api/auth/register",
            json={
                "email": "check-user@example.com",
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
        valid_payload = (
            b'{"InvoiceId":"'
            + invoice_id.encode("utf-8")
            + b'","AccountId":"check-user@example.com","Amount":"990.00",'
            b'"Currency":"RUB","Status":"Completed"}'
        )
        amount_mismatch_payload = (
            b'{"InvoiceId":"'
            + invoice_id.encode("utf-8")
            + b'","AccountId":"check-user@example.com","Amount":"9.90",'
            b'"Currency":"RUB","Status":"Completed"}'
        )
        unknown_payload = (
            b'{"InvoiceId":"unknown-invoice","AccountId":"check-user@example.com",'
            b'"Amount":"990.00","Currency":"RUB","Status":"Completed"}'
        )

        valid_response = signed_cloudpayments_post("check", valid_payload)
        mismatch_response = signed_cloudpayments_post("check", amount_mismatch_payload)
        unknown_response = signed_cloudpayments_post("check", unknown_payload)

        assert valid_response.status_code == 200
        assert valid_response.json() == {"code": 0}
        assert mismatch_response.status_code == 200
        assert mismatch_response.json() == {"code": 12}
        assert unknown_response.status_code == 200
        assert unknown_response.json() == {"code": 10}
        with SessionLocal() as db:
            events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
            order = db.query(Order).one()

        assert [event.status for event in events] == ["processed", "failed", "failed"]
        assert events[1].error_code == "amount_mismatch"
        assert events[2].error_code == "order_not_found"
        assert order.status == "pending_payment"
    finally:
        allow_unsigned_cloudpayments_webhooks_for_test()
        object.__setattr__(settings, "cloudpayments_enabled", False)
        object.__setattr__(settings, "cloudpayments_api_secret", "")


def test_signed_check_webhook_rejects_account_and_currency_mismatch() -> None:
    from app.settings import settings  # noqa: E402

    require_signed_cloudpayments_webhooks_for_test()
    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", "test-secret")
    try:
        register_response = client.post(
            "/api/auth/register",
            json={
                "email": "check-account-user@example.com",
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
        account_mismatch_payload = (
            b'{"InvoiceId":"'
            + invoice_id.encode("utf-8")
            + b'","AccountId":"other@example.com","Amount":"990.00",'
            b'"Currency":"RUB","Status":"Completed"}'
        )
        currency_mismatch_payload = (
            b'{"InvoiceId":"'
            + invoice_id.encode("utf-8")
            + b'","AccountId":"check-account-user@example.com","Amount":"990.00",'
            b'"Currency":"USD","Status":"Completed"}'
        )

        account_response = signed_cloudpayments_post("check", account_mismatch_payload)
        currency_response = signed_cloudpayments_post("check", currency_mismatch_payload)

        assert account_response.status_code == 200
        assert account_response.json() == {"code": 11}
        assert currency_response.status_code == 200
        assert currency_response.json() == {"code": 12}
        with SessionLocal() as db:
            events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

        assert [event.error_code for event in events] == ["account_mismatch", "currency_mismatch"]
    finally:
        allow_unsigned_cloudpayments_webhooks_for_test()
        object.__setattr__(settings, "cloudpayments_enabled", False)
        object.__setattr__(settings, "cloudpayments_api_secret", "")


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
            "Status": "Completed",
            "Data": {"product_code": "document-summary", "plan_code": "document-summary-pro"},
        },
    )

    assert webhook_response.status_code == 200

    status_response = client.get(
        f"/api/auth/payment-status?invoice_id={invoice_id}&email=user@example.com"
    )
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["product_state"]["status"] == "pending"
    assert status_payload["product_state"]["transaction_id"] is None
    assert status_payload["order"]["status"] == "paid"
    assert status_payload["order"]["paid_at"]
    assert status_payload["payment"]["status"] == "succeeded"
    assert status_payload["payment"]["provider_payment_id"] == "tx-success-1"

    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()
        order = db.query(Order).one()
        payment = db.query(Payment).one()

    assert event.endpoint == "pay"
    assert event.invoice_id == invoice_id
    assert event.transaction_id == "tx-success-1"
    assert event.status == "processed"
    assert event.order_id == order.id
    assert event.payment_id == payment.id
    assert order.status == "paid"
    assert order.provider_invoice_id == invoice_id
    assert payment.status == "succeeded"
    assert payment.provider_payment_id == "tx-success-1"
    assert payment.amount_minor == 99000
    assert "CardFirstSix" not in payment.raw_summary


def test_charge_pay_rejects_missing_declined_and_unknown_statuses() -> None:
    scenarios = [
        ("missing", None),
        ("declined", "Declined"),
        ("unknown", "Unexpected"),
    ]

    for suffix, provider_status in scenarios:
        email = f"charge-pay-{suffix}@example.com"
        invoice_id = create_checkout_invoice(email=email)
        payload = {
            "InvoiceId": invoice_id,
            "TransactionId": f"tx-charge-pay-{suffix}",
            "AccountId": email,
            "Amount": "990.00",
            "Currency": "RUB",
        }
        if provider_status is not None:
            payload["Status"] = provider_status

        response = client.post("/api/cloudpayments/pay", json=payload)

        assert response.status_code == 200
        assert response.json() == {"code": 0}

    with SessionLocal() as db:
        orders = db.query(Order).order_by(Order.created_at).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        payment_count = db.query(Payment).count()

    assert [order.status for order in orders] == ["pending_payment"] * len(scenarios)
    assert payment_count == 0
    assert [event.status for event in events] == ["failed"] * len(scenarios)
    assert {event.error_code for event in events} == {"payment_schema_mismatch"}


def test_authorized_pay_requires_confirm_or_cancel_to_reach_terminal_state() -> None:
    invoice_id = create_checkout_invoice(
        email="dms-confirm-user@example.com",
        widget_mode="auth",
    )
    with SessionLocal() as db:
        provider_account = db.query(PaymentProviderAccount).one()
        provider_account.config = {**provider_account.config, "widget_mode": "charge"}
        db.commit()

    completed_pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-dms-completed-pay-1",
            "AccountId": "dms-confirm-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    assert completed_pay_response.status_code == 200
    assert completed_pay_response.json() == {"code": 0}
    with SessionLocal() as db:
        order_after_completed_pay = db.query(Order).one()
        failed_event = db.query(PaymentWebhookEvent).one()
        assert db.query(Payment).count() == 0

    assert order_after_completed_pay.status == "pending_payment"
    assert order_after_completed_pay.paid_at is None
    assert failed_event.status == "failed"
    assert failed_event.error_code == "payment_schema_mismatch"

    pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-dms-confirm-1",
            "AccountId": "dms-confirm-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Authorized",
        },
    )

    assert pay_response.status_code == 200
    assert pay_response.json() == {"code": 0}
    with SessionLocal() as db:
        authorized_order = db.query(Order).one()
        authorized_payment = db.query(Payment).one()
        authorized_event = (
            db.query(PaymentWebhookEvent)
            .filter(PaymentWebhookEvent.transaction_id == "tx-dms-confirm-1")
            .one()
        )

    assert authorized_order.status == "pending_payment"
    assert authorized_order.paid_at is None
    assert authorized_payment.status == "authorized"
    assert authorized_payment.authorized_at
    assert authorized_payment.captured_at is None
    assert authorized_event.event_type == "payment.authorized"

    confirm_response = client.post(
        "/api/cloudpayments/confirm",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-dms-confirm-1",
            "AccountId": "dms-confirm-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    assert confirm_response.status_code == 200
    assert confirm_response.json() == {"code": 0}
    with SessionLocal() as db:
        confirmed_order = db.query(Order).one()
        confirmed_payment = db.query(Payment).one()
        confirmed_event = (
            db.query(PaymentWebhookEvent)
            .filter(PaymentWebhookEvent.transaction_id == "tx-dms-confirm-1")
            .filter(PaymentWebhookEvent.endpoint == "confirm")
            .one()
        )

    assert confirmed_order.status == "paid"
    assert confirmed_order.paid_at
    assert confirmed_payment.status == "succeeded"
    assert confirmed_payment.captured_at
    assert confirmed_event.event_type == "payment.succeeded"


def test_check_webhook_validates_snapshotted_payment_schema() -> None:
    charge_invoice_id = create_checkout_invoice(email="check-charge-schema@example.com")
    auth_invoice_id = create_checkout_invoice(
        email="check-auth-schema@example.com",
        widget_mode="auth",
    )
    missing_status_invoice_id = create_checkout_invoice(
        email="check-missing-schema@example.com",
        widget_mode="auth",
    )
    valid_auth_invoice_id = create_checkout_invoice(
        email="check-valid-auth-schema@example.com",
        widget_mode="auth",
    )

    scenarios = [
        (
            charge_invoice_id,
            "check-charge-schema@example.com",
            "Authorized",
            {"code": 13},
            "payment_schema_mismatch",
        ),
        (
            auth_invoice_id,
            "check-auth-schema@example.com",
            "Completed",
            {"code": 13},
            "payment_schema_mismatch",
        ),
        (
            missing_status_invoice_id,
            "check-missing-schema@example.com",
            None,
            {"code": 13},
            "payment_schema_mismatch",
        ),
        (
            valid_auth_invoice_id,
            "check-valid-auth-schema@example.com",
            "Authorized",
            {"code": 0},
            None,
        ),
    ]

    responses = []
    for invoice_id, email, provider_status, expected_response, expected_error in scenarios:
        payload = {
            "InvoiceId": invoice_id,
            "TransactionId": f"tx-{email}",
            "AccountId": email,
            "Amount": "990.00",
            "Currency": "RUB",
        }
        if provider_status is not None:
            payload["Status"] = provider_status
        response = client.post("/api/cloudpayments/check", json=payload)
        responses.append((response, expected_response, expected_error))

    assert [response.status_code for response, _, _ in responses] == [200, 200, 200, 200]
    assert [response.json() for response, _, _ in responses] == [
        expected_response for _, expected_response, _ in responses
    ]
    with SessionLocal() as db:
        orders = db.query(Order).order_by(Order.created_at).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert [order.status for order in orders] == ["pending_payment"] * len(scenarios)
    assert [event.status for event in events] == ["failed", "failed", "failed", "processed"]
    assert [event.error_code for event in events] == [
        expected_error for _, _, expected_error in responses
    ]


def test_late_confirm_captures_existing_authorized_payment_after_order_is_paid() -> None:
    email = "second-auth-confirm-user@example.com"
    invoice_id = create_checkout_invoice(email=email, widget_mode="auth")

    authorized_responses = [
        client.post(
            "/api/cloudpayments/pay",
            json={
                "InvoiceId": invoice_id,
                "TransactionId": transaction_id,
                "AccountId": email,
                "Amount": "990.00",
                "Currency": "RUB",
                "Status": "Authorized",
            },
        )
        for transaction_id in ("tx-second-auth-confirm-1", "tx-second-auth-confirm-2")
    ]
    confirm_responses = [
        client.post(
            "/api/cloudpayments/confirm",
            json={
                "InvoiceId": invoice_id,
                "TransactionId": transaction_id,
                "AccountId": email,
                "Amount": "990.00",
                "Currency": "RUB",
                "Status": "Completed",
            },
        )
        for transaction_id in ("tx-second-auth-confirm-1", "tx-second-auth-confirm-2")
    ]

    assert [response.status_code for response in authorized_responses] == [200, 200]
    assert [response.json() for response in authorized_responses] == [{"code": 0}, {"code": 0}]
    assert [response.status_code for response in confirm_responses] == [200, 200]
    assert [response.json() for response in confirm_responses] == [{"code": 0}, {"code": 0}]
    with SessionLocal() as db:
        order = db.query(Order).one()
        payments = db.query(Payment).order_by(Payment.provider_payment_id).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status == "paid"
    assert order.paid_at
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-second-auth-confirm-1", "succeeded"),
        ("tx-second-auth-confirm-2", "succeeded"),
    ]
    assert all(payment.authorized_at for payment in payments)
    assert all(payment.captured_at for payment in payments)
    assert [event.endpoint for event in events] == ["pay", "pay", "confirm", "confirm"]
    assert [event.status for event in events] == ["processed"] * 4
    assert [event.payment_id for event in events[2:]] == [payment.id for payment in payments]


def test_authorized_pay_can_be_canceled_with_provider_cancel_payload() -> None:
    invoice_id = create_checkout_invoice(
        email="dms-cancel-user@example.com",
        widget_mode="auth",
    )
    pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-dms-cancel-1",
            "AccountId": "dms-cancel-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Authorized",
        },
    )

    cancel_response = client.post(
        "/api/cloudpayments/cancel",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-dms-cancel-1",
            "Amount": "990.00",
        },
    )

    assert pay_response.status_code == 200
    assert cancel_response.status_code == 200
    assert cancel_response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status == "canceled"
    assert order.canceled_at
    assert order.paid_at is None
    assert payment.status == "canceled"
    assert payment.currency == "RUB"
    assert [event.status for event in events] == ["processed", "processed"]


def test_two_stage_notifications_are_rejected_for_charge_orders() -> None:
    scenarios = [
        ("confirm", "charge-confirm@example.com", "tx-charge-confirm"),
        ("cancel", "charge-cancel@example.com", "tx-charge-cancel"),
    ]

    for endpoint, email, transaction_id in scenarios:
        invoice_id = create_checkout_invoice(email=email)
        response = client.post(
            f"/api/cloudpayments/{endpoint}",
            json={
                "InvoiceId": invoice_id,
                "TransactionId": transaction_id,
                "AccountId": email,
                "Amount": "990.00",
                "Currency": "RUB",
            },
        )

        assert response.status_code == 200
        assert response.json() == {"code": 0}

    with SessionLocal() as db:
        orders = db.query(Order).order_by(Order.created_at).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        payment_count = db.query(Payment).count()

    assert [order.status for order in orders] == ["pending_payment", "pending_payment"]
    assert payment_count == 0
    assert [event.status for event in events] == ["failed", "failed"]
    assert {event.error_code for event in events} == {"payment_schema_mismatch"}


def test_legacy_orders_without_payment_mode_snapshot_default_to_charge_schema() -> None:
    email = "legacy-charge-schema@example.com"
    invoice_id = create_checkout_invoice(email=email)
    with SessionLocal() as db:
        order = db.query(Order).filter(Order.provider_invoice_id == invoice_id).one()
        order.metadata_ = {
            key: value for key, value in order.metadata_.items() if key != "payment_mode"
        }
        provider_account = db.get(PaymentProviderAccount, order.provider_account_id)
        provider_account.config = {**provider_account.config, "widget_mode": "auth"}
        db.commit()

    scenarios = [
        ("check", "tx-legacy-check", "Authorized"),
        ("confirm", "tx-legacy-confirm", "Completed"),
        ("cancel", "tx-legacy-cancel", None),
        ("pay", "tx-legacy-authorized", "Authorized"),
    ]
    responses = []
    for endpoint, transaction_id, provider_status in scenarios:
        payload = {
            "InvoiceId": invoice_id,
            "TransactionId": transaction_id,
            "AccountId": email,
            "Amount": "990.00",
            "Currency": "RUB",
        }
        if provider_status is not None:
            payload["Status"] = provider_status
        responses.append(client.post(f"/api/cloudpayments/{endpoint}", json=payload))

    assert [response.status_code for response in responses] == [200, 200, 200, 200]
    assert [response.json() for response in responses] == [
        {"code": 13},
        {"code": 0},
        {"code": 0},
        {"code": 0},
    ]
    with SessionLocal() as db:
        order = db.query(Order).one()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        payment_count = db.query(Payment).count()

    assert order.status == "pending_payment"
    assert payment_count == 0
    assert [event.status for event in events] == ["failed", "failed", "failed", "failed"]
    assert {event.error_code for event in events} == {"payment_schema_mismatch"}


def test_verified_late_pay_and_confirm_after_checkout_expiry_remain_authoritative() -> None:
    from app.settings import settings  # noqa: E402

    require_signed_cloudpayments_webhooks_for_test()
    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", "test-secret")
    try:
        scenarios = [
            {
                "email": "expired-pay-user@example.com",
                "endpoint": "pay",
                "transaction_id": "tx-expired-pay-1",
            },
            {
                "email": "expired-confirm-user@example.com",
                "endpoint": "confirm",
                "transaction_id": "tx-expired-confirm-1",
            },
        ]

        for scenario in scenarios:
            invoice_id = create_checkout_invoice(
                email=scenario["email"],
                widget_mode="auth" if scenario["endpoint"] == "confirm" else "charge",
            )
            with SessionLocal() as db:
                order = db.query(Order).filter(Order.provider_invoice_id == invoice_id).one()
                order.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
                db.commit()
            raw_payload = (
                b'{"InvoiceId":"'
                + invoice_id.encode("utf-8")
                + b'","TransactionId":"'
                + scenario["transaction_id"].encode("utf-8")
                + b'","AccountId":"'
                + scenario["email"].encode("utf-8")
                + b'","Amount":"990.00","Currency":"RUB","Status":"Completed"}'
            )

            response = signed_cloudpayments_post(scenario["endpoint"], raw_payload)

            assert response.status_code == 200
            assert response.json() == {"code": 0}
            with SessionLocal() as db:
                order = db.query(Order).filter(Order.provider_invoice_id == invoice_id).one()
                payment = (
                    db.query(Payment)
                    .filter(Payment.provider_payment_id == scenario["transaction_id"])
                    .one()
                )

            assert order.status == "paid"
            assert order.paid_at
            assert payment.status == "succeeded"
    finally:
        allow_unsigned_cloudpayments_webhooks_for_test()
        object.__setattr__(settings, "cloudpayments_enabled", False)
        object.__setattr__(settings, "cloudpayments_api_secret", "")


def test_signed_pay_webhook_processes_valid_signature() -> None:
    from app.settings import settings  # noqa: E402

    require_signed_cloudpayments_webhooks_for_test()
    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", "test-secret")
    try:
        register_response = client.post(
            "/api/auth/register",
            json={
                "email": "signed-pay-user@example.com",
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
        raw_payload = (
            b'{"InvoiceId":"'
            + invoice_id.encode("utf-8")
            + b'","TransactionId":"tx-signed-pay-1","AccountId":"signed-pay-user@example.com",'
            b'"Amount":"990.00","Currency":"RUB","Status":"Completed",'
            b'"CardFirstSix":"411111","Token":"tok_secret"}'
        )

        response = signed_cloudpayments_post("pay", raw_payload)

        assert response.status_code == 200
        assert response.json() == {"code": 0}
        with SessionLocal() as db:
            event = db.query(PaymentWebhookEvent).one()
            payment = db.query(Payment).one()

        assert event.status == "processed"
        assert event.raw_payload["CardFirstSix"] == "[redacted]"
        assert event.raw_payload["Token"] == "[redacted]"  # noqa: S105
        assert payment.status == "succeeded"
    finally:
        allow_unsigned_cloudpayments_webhooks_for_test()
        object.__setattr__(settings, "cloudpayments_enabled", False)
        object.__setattr__(settings, "cloudpayments_api_secret", "")


def test_fail_webhook_updates_payment_and_order_without_access_activation() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "fail-user@example.com",
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

    response = client.post(
        "/api/cloudpayments/fail",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-fail-1",
            "AccountId": "fail-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "ReasonCode": "5",
            "Reason": "Insufficient funds",
        },
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        state = db.query(ProductAccessState).one()

    assert order.status == "payment_failed"
    assert payment.status == "failed"
    assert payment.failure_code == "5"
    assert payment.failure_message_safe == "Insufficient funds"
    assert state.status == "pending"
    assert state.last_transaction_id is None


def test_signed_check_after_failed_attempt_allows_retry() -> None:
    require_signed_cloudpayments_webhooks_for_test()
    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", "test-secret")
    try:
        invoice_id = create_checkout_invoice(email="retry-after-fail@example.com")
        fail_payload = (
            b'{"InvoiceId":"'
            + invoice_id.encode("utf-8")
            + b'","TransactionId":"tx-retry-fail-1",'
            b'"AccountId":"retry-after-fail@example.com",'
            b'"Amount":"990.00","Currency":"RUB",'
            b'"ReasonCode":"5","Reason":"Insufficient funds"}'
        )
        check_payload = (
            b'{"InvoiceId":"'
            + invoice_id.encode("utf-8")
            + b'","TransactionId":"tx-retry-check-1",'
            b'"AccountId":"retry-after-fail@example.com",'
            b'"Amount":"990.00","Currency":"RUB","Status":"Completed"}'
        )

        fail_response = signed_cloudpayments_post("fail", fail_payload)
        check_response = signed_cloudpayments_post("check", check_payload)

        assert fail_response.status_code == 200
        assert fail_response.json() == {"code": 0}
        assert check_response.status_code == 200
        assert check_response.json() == {"code": 0}
        with SessionLocal() as db:
            order = db.query(Order).one()
            events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

        assert order.status == "payment_failed"
        assert [event.endpoint for event in events] == ["fail", "check"]
        assert [event.status for event in events] == ["processed", "processed"]
        assert events[1].error_code is None
    finally:
        allow_unsigned_cloudpayments_webhooks_for_test()
        object.__setattr__(settings, "cloudpayments_enabled", False)
        object.__setattr__(settings, "cloudpayments_api_secret", "")


def test_confirm_and_cancel_notifications_update_two_stage_payment_state() -> None:
    seed_cloudpayments_provider_account(widget_mode="auth")
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "confirm-cancel-user@example.com",
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

    confirm_response = client.post(
        "/api/cloudpayments/confirm",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-confirm-1",
            "AccountId": "confirm-cancel-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    assert confirm_response.status_code == 200
    assert confirm_response.json() == {"code": 0}
    with SessionLocal() as db:
        confirmed_order = db.query(Order).one()
        confirmed_payment = db.query(Payment).one()

    assert confirmed_order.status == "paid"
    assert confirmed_payment.status == "succeeded"

    register_cancel_response = client.post(
        "/api/auth/register",
        json={
            "email": "cancel-user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    cancel_token = register_cancel_response.json()["token"]
    cancel_checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {cancel_token}"},
        json={
            "product": "prompt-optimizer",
            "plan_code": "prompt-optimizer-pro",
            "auto_renew": False,
        },
    )
    cancel_invoice_id = cancel_checkout_response.json()["product_state"]["invoice_id"]

    cancel_response = client.post(
        "/api/cloudpayments/cancel",
        json={
            "InvoiceId": cancel_invoice_id,
            "TransactionId": "tx-cancel-1",
            "AccountId": "cancel-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
        },
    )

    assert cancel_response.status_code == 200
    assert cancel_response.json() == {"code": 0}
    with SessionLocal() as db:
        canceled_order = db.query(Order).filter(Order.provider_invoice_id == cancel_invoice_id).one()
        canceled_payment = db.query(Payment).filter(Payment.provider_payment_id == "tx-cancel-1").one()

    assert canceled_order.status == "canceled"
    assert canceled_order.canceled_at
    assert canceled_payment.status == "canceled"


def test_confirm_notification_accepts_missing_account_id() -> None:
    seed_cloudpayments_provider_account(widget_mode="auth")
    invoice_id = create_checkout_invoice(
        email="confirm-optional-account@example.com",
        widget_mode="auth",
    )

    response = client.post(
        "/api/cloudpayments/confirm",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-confirm-no-account-1",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        event = db.query(PaymentWebhookEvent).one()

    assert order.status == "paid"
    assert payment.status == "succeeded"
    assert event.status == "processed"
    assert event.error_code is None


def test_confirm_notification_rejects_partial_capture_amount() -> None:
    invoice_id = create_checkout_invoice(
        email="partial-confirm-user@example.com",
        widget_mode="auth",
    )
    pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-partial-confirm-1",
            "AccountId": "partial-confirm-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Authorized",
        },
    )
    confirm_response = client.post(
        "/api/cloudpayments/confirm",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-partial-confirm-1",
            "AccountId": "partial-confirm-user@example.com",
            "Amount": "450.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    assert pay_response.status_code == 200
    assert confirm_response.status_code == 200
    assert confirm_response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        confirm_event = (
            db.query(PaymentWebhookEvent)
            .filter(PaymentWebhookEvent.endpoint == "confirm")
            .one()
        )

    assert order.status == "pending_payment"
    assert payment.status == "authorized"
    assert payment.amount_minor == 99000
    assert payment.captured_at is None
    assert confirm_event.status == "failed"
    assert confirm_event.amount_minor == 45000
    assert confirm_event.error_code == "amount_mismatch"


def test_confirm_notification_rejects_amount_above_authorization() -> None:
    invoice_id = create_checkout_invoice(
        email="excessive-confirm-user@example.com",
        widget_mode="auth",
    )
    pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-excessive-confirm-1",
            "AccountId": "excessive-confirm-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Authorized",
        },
    )
    confirm_response = client.post(
        "/api/cloudpayments/confirm",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-excessive-confirm-1",
            "AccountId": "excessive-confirm-user@example.com",
            "Amount": "1200.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    assert pay_response.status_code == 200
    assert confirm_response.status_code == 200
    assert confirm_response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        confirm_event = (
            db.query(PaymentWebhookEvent)
            .filter(PaymentWebhookEvent.endpoint == "confirm")
            .one()
        )

    assert order.status == "pending_payment"
    assert payment.status == "authorized"
    assert payment.amount_minor == 99000
    assert payment.captured_at is None
    assert confirm_event.status == "failed"
    assert confirm_event.error_code == "amount_mismatch"


def test_cancel_webhook_accepts_provider_payload_without_currency_or_account() -> None:
    invoice_id = create_checkout_invoice(
        email="provider-cancel-user@example.com",
        widget_mode="auth",
    )

    cancel_response = client.post(
        "/api/cloudpayments/cancel",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-provider-cancel-1",
            "Amount": "990.00",
        },
    )

    assert cancel_response.status_code == 200
    assert cancel_response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        event = db.query(PaymentWebhookEvent).one()

    assert order.status == "canceled"
    assert payment.status == "canceled"
    assert payment.currency == "RUB"
    assert event.status == "processed"


def test_state_changing_notifications_require_transaction_id() -> None:
    seed_cloudpayments_provider_account(widget_mode="auth")
    scenarios = [
        ("pay", "missing-transaction-pay@example.com", {"Status": "Completed"}),
        ("fail", "missing-transaction-fail@example.com", {"ReasonCode": "5"}),
        ("confirm", "missing-transaction-confirm@example.com", {"Status": "Completed"}),
        ("cancel", "missing-transaction-cancel@example.com", {}),
    ]

    for endpoint, email, extra_payload in scenarios:
        invoice_id = create_checkout_invoice(email=email, widget_mode="auth")
        response = client.post(
            f"/api/cloudpayments/{endpoint}",
            json={
                "InvoiceId": invoice_id,
                "AccountId": email,
                "Amount": "990.00",
                "Currency": "RUB",
                **extra_payload,
            },
        )

        assert response.status_code == 200
        assert response.json() == {"code": 0}
        with SessionLocal() as db:
            order = db.query(Order).filter(Order.provider_invoice_id == invoice_id).one()
            event = (
                db.query(PaymentWebhookEvent)
                .filter(PaymentWebhookEvent.invoice_id == invoice_id)
                .one()
            )
            payment_count = db.query(Payment).filter(Payment.order_id == order.id).count()

        assert order.status == "pending_payment"
        assert event.status == "failed"
        assert event.error_code == "missing_transaction_id"
        assert payment_count == 0


def test_late_pay_or_confirm_does_not_reopen_canceled_order() -> None:
    seed_cloudpayments_provider_account(widget_mode="auth")
    scenarios = [
        {
            "email": "late-pay-after-cancel@example.com",
            "product": "document-summary",
            "plan_code": "document-summary-pro",
            "endpoint": "pay",
            "transaction_id": "tx-late-pay-after-cancel",
        },
        {
            "email": "late-confirm-after-cancel@example.com",
            "product": "prompt-optimizer",
            "plan_code": "prompt-optimizer-pro",
            "endpoint": "confirm",
            "transaction_id": "tx-late-confirm-after-cancel",
        },
    ]

    for scenario in scenarios:
        register_response = client.post(
            "/api/auth/register",
            json={
                "email": scenario["email"],
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
                "product": scenario["product"],
                "plan_code": scenario["plan_code"],
                "auto_renew": False,
            },
        )
        invoice_id = checkout_response.json()["product_state"]["invoice_id"]
        base_payload = {
            "InvoiceId": invoice_id,
            "TransactionId": scenario["transaction_id"],
            "AccountId": scenario["email"],
            "Amount": "990.00",
            "Currency": "RUB",
        }

        cancel_response = client.post("/api/cloudpayments/cancel", json=base_payload)
        late_response = client.post(
            f"/api/cloudpayments/{scenario['endpoint']}",
            json={
                **base_payload,
                "Status": "Authorized"
                if scenario["endpoint"] == "pay"
                else "Completed",
            },
        )

        assert cancel_response.status_code == 200
        assert cancel_response.json() == {"code": 0}
        assert late_response.status_code == 200
        assert late_response.json() == {"code": 0}
        with SessionLocal() as db:
            order = db.query(Order).filter(Order.provider_invoice_id == invoice_id).one()
            payment = (
                db.query(Payment)
                .filter(Payment.provider_payment_id == scenario["transaction_id"])
                .one()
            )
            events = (
                db.query(PaymentWebhookEvent)
                .filter(PaymentWebhookEvent.invoice_id == invoice_id)
                .order_by(PaymentWebhookEvent.received_at)
                .all()
            )

        assert order.status == "canceled"
        assert order.paid_at is None
        assert order.canceled_at
        assert payment.status == "canceled"
        assert [event.endpoint for event in events] == ["cancel", scenario["endpoint"]]
        assert [event.status for event in events] == ["processed", "ignored"]
        assert events[1].error_code == "order_already_canceled"


def test_late_fail_webhook_does_not_downgrade_paid_order() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "late-fail-user@example.com",
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

    pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-late-fail-success",
            "AccountId": "late-fail-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )
    fail_response = client.post(
        "/api/cloudpayments/fail",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-late-fail-declined",
            "AccountId": "late-fail-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "ReasonCode": "5",
            "Reason": "Insufficient funds",
        },
    )

    assert pay_response.status_code == 200
    assert fail_response.status_code == 200
    with SessionLocal() as db:
        order = db.query(Order).one()
        payments = db.query(Payment).order_by(Payment.created_at).all()

    assert order.status == "paid"
    assert order.paid_at
    assert order.failed_at is None
    assert [payment.status for payment in payments] == ["succeeded", "failed"]


def test_late_fail_webhook_does_not_downgrade_canceled_order() -> None:
    invoice_id = create_checkout_invoice(
        email="late-fail-canceled-user@example.com",
        widget_mode="auth",
    )
    authorized_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-late-fail-canceled",
            "AccountId": "late-fail-canceled-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Authorized",
        },
    )
    cancel_response = client.post(
        "/api/cloudpayments/cancel",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-late-fail-canceled",
            "Amount": "990.00",
        },
    )
    late_fail_response = client.post(
        "/api/cloudpayments/fail",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-late-fail-canceled",
            "AccountId": "late-fail-canceled-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "ReasonCode": "5",
            "Reason": "Insufficient funds",
        },
    )

    assert authorized_response.status_code == 200
    assert cancel_response.status_code == 200
    assert late_fail_response.status_code == 200
    assert late_fail_response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status == "canceled"
    assert order.canceled_at
    assert order.failed_at is None
    assert payment.status == "canceled"
    assert payment.failed_at is None
    assert [event.status for event in events] == ["processed", "processed", "processed"]


def test_late_distinct_pay_is_persisted_without_reopening_paid_order() -> None:
    invoice_id = create_checkout_invoice(email="second-charge-user@example.com")
    first_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-first-success-1",
            "AccountId": "second-charge-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )
    check_response = client.post(
        "/api/cloudpayments/check",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-second-check-1",
            "AccountId": "second-charge-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )
    late_pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-second-success-1",
            "AccountId": "second-charge-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    assert first_response.status_code == 200
    assert check_response.status_code == 200
    assert check_response.json() == {"code": 13}
    assert late_pay_response.status_code == 200
    assert late_pay_response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payments = db.query(Payment).order_by(Payment.created_at).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status == "paid"
    assert order.paid_at
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-first-success-1", "succeeded"),
        ("tx-second-success-1", "succeeded"),
    ]
    assert [event.endpoint for event in events] == ["pay", "check", "pay"]
    assert [event.status for event in events] == ["processed", "failed", "processed"]
    assert events[1].error_code == "order_not_payable"
    assert events[2].payment_id == payments[1].id
    assert events[2].error_code is None


def test_completed_pay_after_auth_cancel_is_rejected_and_cannot_be_refunded() -> None:
    invoice_id = create_checkout_invoice(
        email="late-charge-refund@example.com",
        widget_mode="auth",
    )
    cancel_response = client.post(
        "/api/cloudpayments/cancel",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-canceled-attempt",
            "Amount": "990.00",
        },
    )
    late_pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-late-distinct-charge",
            "AccountId": "late-charge-refund@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )
    refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-late-distinct-refund",
            "PaymentTransactionId": "tx-late-distinct-charge",
            "Amount": "990.00",
        },
    )

    assert cancel_response.json() == {"code": 0}
    assert late_pay_response.json() == {"code": 0}
    assert refund_response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payments = db.query(Payment).order_by(Payment.provider_payment_id).all()
        refund_count = db.query(Refund).count()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status == "canceled"
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-canceled-attempt", "canceled"),
    ]
    assert refund_count == 0
    assert [event.status for event in events] == ["processed", "failed", "failed"]
    assert [event.error_code for event in events] == [
        None,
        "payment_schema_mismatch",
        "payment_not_found",
    ]


def test_refund_one_of_multiple_successful_payments_keeps_order_partially_refunded() -> None:
    invoice_id = create_checkout_invoice(email="multi-success-refund-user@example.com")
    first_pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-multi-success-refund-1",
            "AccountId": "multi-success-refund-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )
    second_pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-multi-success-refund-2",
            "AccountId": "multi-success-refund-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )
    refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-multi-success-refund-1",
            "RefundId": "refund-multi-success-1",
            "Amount": "990.00",
            "Currency": "RUB",
        },
    )

    assert first_pay_response.status_code == 200
    assert second_pay_response.status_code == 200
    assert refund_response.status_code == 200
    assert refund_response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payments = db.query(Payment).order_by(Payment.provider_payment_id).all()
        refund = db.query(Refund).one()

    assert order.status == "partially_refunded"
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-multi-success-refund-1", "refunded"),
        ("tx-multi-success-refund-2", "succeeded"),
    ]
    assert [payment.refunded_amount_minor for payment in payments] == [99000, 0]
    assert refund.provider_refund_id == "refund-multi-success-1"


def test_duplicate_success_webhook_does_not_duplicate_payment_or_order_updates() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "duplicate-user@example.com",
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
    payload = {
        "InvoiceId": invoice_id,
        "TransactionId": "tx-duplicate-1",
        "AccountId": "duplicate-user@example.com",
        "Amount": "990.00",
        "Currency": "RUB",
        "Status": "Completed",
    }

    first_response = client.post("/api/cloudpayments/pay", json=payload)
    second_response = client.post("/api/cloudpayments/pay", json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    with SessionLocal() as db:
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        order_count = db.query(Order).count()
        payments = db.query(Payment).all()

    assert order_count == 1
    assert len(payments) == 1
    assert [event.status for event in events] == ["processed", "duplicate"]
    assert events[1].payment_id == payments[0].id


def test_refund_webhook_records_refund_skeleton_and_updates_payment() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "refund-user@example.com",
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
    client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-refund-1",
            "AccountId": "refund-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-refund-1",
            "RefundId": "refund-1",
            "Amount": "990.00",
            "Currency": "RUB",
            "Reason": "customer_request",
        },
    )

    assert refund_response.status_code == 200

    status_response = client.get(
        f"/api/auth/payment-status?invoice_id={invoice_id}&email=refund-user@example.com"
    )
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["product_state"]["status"] == "pending"
    assert status_payload["order"]["status"] == "refunded"
    assert status_payload["payment"]["status"] == "refunded"
    assert status_payload["payment"]["refunded_amount_minor"] == 99000

    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        refund = db.query(Refund).one()
        events = db.query(PaymentWebhookEvent).all()

    assert order.status == "refunded"
    assert payment.status == "refunded"
    assert payment.refunded_amount_minor == 99000
    assert refund.status == "succeeded"
    assert refund.provider_refund_id == "refund-1"
    assert len(events) == 2


def test_refund_webhook_accepts_provider_payload_without_currency_or_refund_id() -> None:
    invoice_id = create_checkout_invoice(email="provider-refund-user@example.com")
    client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-provider-refund-original",
            "AccountId": "provider-refund-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-provider-refund-id",
            "PaymentTransactionId": "tx-provider-refund-original",
            "Amount": "400.00",
            "OperationType": "Refund",
        },
    )

    assert refund_response.status_code == 200
    assert refund_response.json() == {"code": 0}
    with SessionLocal() as db:
        payment = db.query(Payment).one()
        refund = db.query(Refund).one()
        refund_event = (
            db.query(PaymentWebhookEvent)
            .filter(PaymentWebhookEvent.endpoint == "refund")
            .one()
        )

    assert payment.status == "partially_refunded"
    assert payment.refunded_amount_minor == 40000
    assert refund.provider_refund_id == "tx-provider-refund-id"
    assert refund.currency == "RUB"
    assert refund_event.status == "processed"
    assert refund_event.transaction_id == "tx-provider-refund-original"


def test_distinct_refund_ids_for_same_transaction_are_not_deduplicated() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "multi-refund-user@example.com",
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
    client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-multi-refund-1",
            "AccountId": "multi-refund-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    first_refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-multi-refund-1",
            "RefundId": "refund-part-1",
            "Amount": "400.00",
            "Currency": "RUB",
            "Reason": "customer_request",
        },
    )
    assert first_refund_response.status_code == 200

    partial_status_response = client.get(
        f"/api/auth/payment-status?invoice_id={invoice_id}&email=multi-refund-user@example.com"
    )
    assert partial_status_response.status_code == 200
    partial_status_payload = partial_status_response.json()
    assert partial_status_payload["product_state"]["status"] == "pending"
    assert partial_status_payload["order"]["status"] == "partially_refunded"
    assert partial_status_payload["payment"]["status"] == "partially_refunded"
    assert partial_status_payload["payment"]["amount_minor"] == 99000
    assert partial_status_payload["payment"]["refunded_amount_minor"] == 40000

    second_refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-multi-refund-1",
            "RefundId": "refund-part-2",
            "Amount": "590.00",
            "Currency": "RUB",
            "Reason": "customer_request",
        },
    )

    assert second_refund_response.status_code == 200
    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        refunds = db.query(Refund).order_by(Refund.provider_refund_id).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status == "refunded"
    assert payment.status == "refunded"
    assert payment.refunded_amount_minor == 99000
    assert [refund.provider_refund_id for refund in refunds] == ["refund-part-1", "refund-part-2"]
    assert [event.status for event in events] == ["processed", "processed", "processed"]


def test_duplicate_refund_id_with_distinct_event_id_does_not_double_count_refund() -> None:
    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "duplicate-refund-user@example.com",
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
    client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-duplicate-refund-1",
            "AccountId": "duplicate-refund-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )
    refund_payload = {
        "InvoiceId": invoice_id,
        "TransactionId": "tx-duplicate-refund-1",
        "RefundId": "refund-duplicate-1",
        "Amount": "400.00",
        "Currency": "RUB",
        "Reason": "customer_request",
    }

    first_refund_response = client.post(
        "/api/cloudpayments/refund",
        json={**refund_payload, "EventId": "refund-event-1"},
    )
    second_refund_response = client.post(
        "/api/cloudpayments/refund",
        json={**refund_payload, "EventId": "refund-event-2"},
    )

    assert first_refund_response.status_code == 200
    assert second_refund_response.status_code == 200
    with SessionLocal() as db:
        payment = db.query(Payment).one()
        refunds = db.query(Refund).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert payment.status == "partially_refunded"
    assert payment.refunded_amount_minor == 40000
    assert len(refunds) == 1
    assert [event.status for event in events] == ["processed", "processed", "processed"]


def test_partial_refunds_cannot_exceed_original_payment_amount() -> None:
    invoice_id = create_checkout_invoice(email="refund-bound-user@example.com")
    client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-refund-bound-original",
            "AccountId": "refund-bound-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    first_refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-refund-bound-original",
            "RefundId": "refund-bound-1",
            "Amount": "700.00",
            "Currency": "RUB",
        },
    )
    excessive_refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-refund-bound-original",
            "RefundId": "refund-bound-2",
            "Amount": "400.00",
            "Currency": "RUB",
        },
    )

    assert first_refund_response.status_code == 200
    assert excessive_refund_response.status_code == 200
    assert excessive_refund_response.json() == {"code": 0}
    with SessionLocal() as db:
        payment = db.query(Payment).one()
        refunds = db.query(Refund).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert payment.status == "partially_refunded"
    assert payment.refunded_amount_minor == 70000
    assert len(refunds) == 1
    assert [event.status for event in events] == ["processed", "processed", "failed"]
    assert events[-1].error_code == "refund_amount_exceeds_payment"


def test_recurrent_webhook_is_persisted_for_downstream_subscription_handling() -> None:
    seed_cloudpayments_provider_account()
    response = client.post(
        "/api/cloudpayments/recurrent",
        json={
            "Id": "sub_1",
            "AccountId": "recurrent-user@example.com",
            "Description": "Document Summary Pro",
            "Email": "recurrent-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "RequireConfirmation": False,
            "StartDate": "2026-08-07 00:00:00",
            "Interval": "Month",
            "Period": 1,
            "Status": "Active",
            "SuccessfulTransactionsNumber": 0,
            "FailedTransactionsNumber": 0,
            "CardLastFour": "4242",
            "Token": "tok_secret",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}
    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.endpoint == "recurrent"
    assert event.event_type == "subscription.updated"
    assert event.provider_event_id == "sub_1"
    assert event.status == "processed"
    assert event.raw_payload["CardLastFour"] == "[redacted]"
    assert event.raw_payload["Token"] == "[redacted]"  # noqa: S105
    assert event.raw_payload["_normalized"] == {
        "subscription_id": "sub_1",
        "account_id": "recurrent-user@example.com",
        "email": "recurrent-user@example.com",
        "description": "Document Summary Pro",
        "status": "active",
        "amount_minor": 99000,
        "currency": "RUB",
        "require_confirmation": False,
        "start_at": "2026-08-07 00:00:00",
        "interval": "month",
        "period": 1,
        "successful_payments_count": 0,
        "failed_payments_count": 0,
    }


def test_recurrent_webhook_requires_an_enabled_provider_account() -> None:
    response = client.post(
        "/api/cloudpayments/recurrent",
        json={
            "Id": "sub_without_account",
            "AccountId": "missing-account@example.com",
            "Email": "missing-account@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Active",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}
    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.status == "failed"
    assert event.provider_account_id is None
    assert event.error_code == "provider_account_not_found"


def test_cloudpayments_payload_helpers_keep_normalization_contract() -> None:
    assert get_first({"primary": "", "fallback": "value"}, "primary", "fallback") == "value"
    assert get_first({"primary": "   ", "fallback": "value"}, "primary", "fallback") == "value"
    assert get_first({"flag": False}, "flag") is False
    assert get_first({"count": 0}, "count") == 0
    assert get_first({"blank": " \t\n"}, "blank") is None

    assert all(parse_bool(value) is True for value in ("true", "1", "yes", "y", True))
    assert all(
        parse_bool(value) is False for value in ("false", "0", "no", "n", False)
    )
    assert parse_bool("maybe") is None

    assert parse_int(7) == 7
    assert parse_int(" 007 ") == 7
    assert parse_int("-3") == -3
    assert parse_int(True) is None
    assert parse_int("") is None
    assert parse_int("1.5") is None
    assert parse_int(1.5) is None
    assert parse_int(float("inf")) is None

    assert {
        value: normalized_recurrent_status(value)
        for value in (
            "Active",
            "PastDue",
            "Past_Due",
            "past-due",
            "Cancelled",
            "Canceled",
            "Rejected",
            "Expired",
            "Paused",
        )
    } == {
        "Active": "active",
        "PastDue": "past_due",
        "Past_Due": "past_due",
        "past-due": "past_due",
        "Cancelled": "canceled",
        "Canceled": "canceled",
        "Rejected": "rejected",
        "Expired": "expired",
        "Paused": "unknown",
    }


def test_recurrent_webhook_validates_required_provider_fields() -> None:
    seed_cloudpayments_provider_account()
    base_payload = {
        "Id": "sub_required_fields",
        "AccountId": "required-recurrent@example.com",
        "Description": "Document Summary Pro",
        "Email": "required-recurrent@example.com",
        "Amount": "990.00",
        "Currency": "RUB",
        "RequireConfirmation": False,
        "StartDate": "2026-08-07 00:00:00",
        "Interval": "Month",
        "Period": 1,
        "Status": "Active",
        "SuccessfulTransactionsNumber": 1,
        "FailedTransactionsNumber": 0,
    }
    scenarios = [
        (
            "missing_subscription_id",
            "missing_subscription_id",
            0,
            {key: value for key, value in base_payload.items() if key != "Id"},
        ),
        (
            "blank_subscription_id",
            "missing_subscription_id",
            0,
            {**base_payload, "Id": "   "},
        ),
        (
            "missing_account_id",
            "missing_account_id",
            0,
            {key: value for key, value in base_payload.items() if key != "AccountId"},
        ),
        (
            "missing_subscription_description",
            "missing_subscription_description",
            0,
            {key: value for key, value in base_payload.items() if key != "Description"},
        ),
        (
            "blank_subscription_description",
            "missing_subscription_description",
            0,
            {**base_payload, "Description": "   "},
        ),
        (
            "missing_subscription_email",
            "missing_subscription_email",
            0,
            {key: value for key, value in base_payload.items() if key != "Email"},
        ),
        (
            "blank_subscription_email",
            "missing_subscription_email",
            0,
            {**base_payload, "Email": "\t"},
        ),
        (
            "missing_amount",
            "missing_amount",
            0,
            {key: value for key, value in base_payload.items() if key != "Amount"},
        ),
        (
            "zero_amount",
            "invalid_amount",
            0,
            {**base_payload, "Amount": "0"},
        ),
        (
            "negative_amount",
            "invalid_amount",
            0,
            {**base_payload, "Amount": "-990.00"},
        ),
        (
            "missing_currency",
            "missing_currency",
            0,
            {key: value for key, value in base_payload.items() if key != "Currency"},
        ),
        (
            "missing_subscription_require_confirmation",
            "missing_subscription_require_confirmation",
            0,
            {
                key: value
                for key, value in base_payload.items()
                if key != "RequireConfirmation"
            },
        ),
        (
            "invalid_subscription_require_confirmation",
            "invalid_subscription_require_confirmation",
            0,
            {**base_payload, "RequireConfirmation": "not-a-bool"},
        ),
        (
            "missing_subscription_start_date",
            "missing_subscription_start_date",
            0,
            {key: value for key, value in base_payload.items() if key != "StartDate"},
        ),
        (
            "blank_subscription_start_date",
            "missing_subscription_start_date",
            0,
            {**base_payload, "StartDate": "  "},
        ),
        (
            "missing_subscription_interval",
            "missing_subscription_interval",
            0,
            {key: value for key, value in base_payload.items() if key != "Interval"},
        ),
        (
            "blank_subscription_interval",
            "missing_subscription_interval",
            0,
            {**base_payload, "Interval": "\t"},
        ),
        (
            "missing_subscription_period",
            "missing_subscription_period",
            0,
            {key: value for key, value in base_payload.items() if key != "Period"},
        ),
        (
            "invalid_subscription_period",
            "invalid_subscription_period",
            0,
            {**base_payload, "Period": "monthly"},
        ),
        (
            "fractional_subscription_period",
            "invalid_subscription_period",
            0,
            {**base_payload, "Period": "1.5"},
        ),
        (
            "zero_subscription_period",
            "invalid_subscription_period",
            0,
            {**base_payload, "Period": 0},
        ),
        (
            "negative_subscription_period",
            "invalid_subscription_period",
            0,
            {**base_payload, "Period": "-3"},
        ),
        (
            "missing_subscription_status",
            "missing_subscription_status",
            0,
            {key: value for key, value in base_payload.items() if key != "Status"},
        ),
        (
            "invalid_subscription_status",
            "invalid_subscription_status",
            0,
            {**base_payload, "Status": "Paused"},
        ),
        (
            "missing_subscription_successful_transactions_number",
            "missing_subscription_successful_transactions_number",
            0,
            {
                key: value
                for key, value in base_payload.items()
                if key != "SuccessfulTransactionsNumber"
            },
        ),
        (
            "invalid_subscription_successful_transactions_number",
            "invalid_subscription_successful_transactions_number",
            0,
            {**base_payload, "SuccessfulTransactionsNumber": "many"},
        ),
        (
            "negative_subscription_successful_transactions_number",
            "invalid_subscription_successful_transactions_number",
            0,
            {**base_payload, "SuccessfulTransactionsNumber": -1},
        ),
        (
            "missing_subscription_failed_transactions_number",
            "missing_subscription_failed_transactions_number",
            0,
            {
                key: value
                for key, value in base_payload.items()
                if key != "FailedTransactionsNumber"
            },
        ),
        (
            "invalid_subscription_failed_transactions_number",
            "invalid_subscription_failed_transactions_number",
            0,
            {**base_payload, "FailedTransactionsNumber": "none"},
        ),
        (
            "negative_subscription_failed_transactions_number",
            "invalid_subscription_failed_transactions_number",
            0,
            {**base_payload, "FailedTransactionsNumber": "-1"},
        ),
        (
            "invalid_subscription_max_periods",
            "invalid_subscription_max_periods",
            0,
            {**base_payload, "MaxPeriods": "forever"},
        ),
        (
            "zero_subscription_max_periods",
            "invalid_subscription_max_periods",
            0,
            {**base_payload, "MaxPeriods": 0},
        ),
        (
            "negative_subscription_max_periods",
            "invalid_subscription_max_periods",
            0,
            {**base_payload, "MaxPeriods": "-12"},
        ),
    ]
    scenario_payloads = []
    for index, (name, error_code, expected_code, payload) in enumerate(scenarios):
        scenario_payload = dict(payload)
        if get_first(scenario_payload, "Id", "id") is not None:
            scenario_payload["Id"] = f"sub_required_fields_{index}"
        scenario_payloads.append((name, error_code, expected_code, scenario_payload))

    responses = [
        client.post("/api/cloudpayments/recurrent", json=payload)
        for _, _, _, payload in scenario_payloads
    ]

    assert [response.json()["code"] for response in responses] == [
        expected_code for _, _, expected_code, _ in scenario_payloads
    ]
    with SessionLocal() as db:
        events = db.query(PaymentWebhookEvent).all()

    assert [event.status for event in events] == ["failed"] * len(scenarios)
    events_by_provider_event_id = {
        event.provider_event_id: event
        for event in events
        if event.provider_event_id is not None
    }
    expected_by_provider_event_id = {
        payload["Id"]: error_code
        for _, error_code, _, payload in scenario_payloads
        if get_first(payload, "Id", "id") is not None
    }
    assert {
        provider_event_id: event.error_code
        for provider_event_id, event in events_by_provider_event_id.items()
    } == expected_by_provider_event_id
    missing_id_events = [
        event for event in events if event.provider_event_id is None
    ]
    assert len(missing_id_events) == 2
    assert {event.error_code for event in missing_id_events} == {
        "missing_subscription_id"
    }


def test_recurrent_terminal_statuses_and_schedule_are_normalized() -> None:
    seed_cloudpayments_provider_account()
    base_payload = {
        "Id": "sub_terminal_status",
        "AccountId": "terminal-recurrent@example.com",
        "Description": "Document Summary Pro",
        "Email": "terminal-recurrent@example.com",
        "Amount": "990.00",
        "Currency": "RUB",
        "RequireConfirmation": False,
        "StartDate": "2026-08-07 00:00:00",
        "Interval": "Month",
        "Period": 1,
        "SuccessfulTransactionsNumber": 2,
        "FailedTransactionsNumber": 3,
        "MaxPeriods": 12,
        "LastTransactionDate": "2026-08-06 00:00:00",
        "NextTransactionDate": "2026-09-07 00:00:00",
    }

    rejected_response = client.post(
        "/api/cloudpayments/recurrent",
        json={**base_payload, "Status": "Rejected"},
    )
    expired_response = client.post(
        "/api/cloudpayments/recurrent",
        json={**base_payload, "Status": "Expired"},
    )

    assert rejected_response.json() == {"code": 0}
    assert expired_response.json() == {"code": 0}
    with SessionLocal() as db:
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert [event.raw_payload["_normalized"]["status"] for event in events] == [
        "rejected",
        "expired",
    ]
    assert events[0].raw_payload["_normalized"] == {
        "subscription_id": "sub_terminal_status",
        "account_id": "terminal-recurrent@example.com",
        "email": "terminal-recurrent@example.com",
        "description": "Document Summary Pro",
        "status": "rejected",
        "amount_minor": 99000,
        "currency": "RUB",
        "require_confirmation": False,
        "start_at": "2026-08-07 00:00:00",
        "interval": "month",
        "period": 1,
        "successful_payments_count": 2,
        "failed_payments_count": 3,
        "max_periods": 12,
        "last_transaction_at": "2026-08-06 00:00:00",
        "next_transaction_at": "2026-09-07 00:00:00",
    }


def test_recurrent_duplicate_delivery_uses_payload_idempotency_not_subscription_id() -> None:
    with SessionLocal() as db:
        db.add(
            PaymentProviderAccount(
                tenant_id="anytoolai",
                region="ru",
                provider="cloudpayments",
                public_identifier="pk_test_provider",
                default_currency="RUB",
                enabled=True,
                test_mode=True,
                config={},
            )
        )
        db.commit()
    active_payload = {
        "Id": "sub_duplicate_1",
        "AccountId": "recurrent-duplicate@example.com",
        "Description": "Document Summary Pro",
        "Email": "recurrent-duplicate@example.com",
        "Amount": "990.00",
        "Currency": "RUB",
        "RequireConfirmation": False,
        "StartDate": "2026-08-07 00:00:00",
        "Interval": "Month",
        "Period": 1,
        "Status": "Active",
        "SuccessfulTransactionsNumber": 1,
        "FailedTransactionsNumber": 0,
    }
    cancelled_payload = {**active_payload, "Status": "Cancelled"}

    first_response = client.post("/api/cloudpayments/recurrent", json=active_payload)
    duplicate_response = client.post("/api/cloudpayments/recurrent", json=active_payload)
    status_change_response = client.post("/api/cloudpayments/recurrent", json=cancelled_payload)

    assert first_response.status_code == 200
    assert duplicate_response.status_code == 200
    assert status_change_response.status_code == 200
    with SessionLocal() as db:
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        provider_account = db.query(PaymentProviderAccount).one()

    assert [event.status for event in events] == ["processed", "duplicate", "processed"]
    assert [event.provider_account_id for event in events] == [
        provider_account.id,
        provider_account.id,
        provider_account.id,
    ]
    assert events[0].idempotency_key == events[1].idempotency_key
    assert events[2].idempotency_key != events[0].idempotency_key


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


def test_password_reset_email_token_and_session_revocation(monkeypatch) -> None:
    sent_messages: list[tuple[str, str]] = []
    reset_token = "known-reset-token-value-with-enough-entropy"

    def fake_make_password_reset_token():
        token_hash = password_reset_router.hashlib.sha256(reset_token.encode("utf-8")).hexdigest()
        return reset_token, token_hash, datetime.now(timezone.utc) + timedelta(minutes=30)

    monkeypatch.setattr(
        password_reset_router,
        "make_password_reset_token",
        fake_make_password_reset_token,
    )
    monkeypatch.setattr(
        password_reset_router,
        "send_password_reset_email",
        lambda email, url: sent_messages.append((email, url)) or True,
    )

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "reset-user@example.com",
            "password": "old-password-123",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert register_response.status_code == 200
    old_session_token = register_response.json()["token"]

    request_response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "reset-user@example.com"},
    )
    assert request_response.status_code == 200
    assert request_response.json() == {"status": "accepted"}
    assert sent_messages == [
        (
            "reset-user@example.com",
            password_reset_router.build_password_reset_url(reset_token),
        )
    ]

    with SessionLocal() as db:
        stored_token = db.query(MagicLinkToken).one()
        assert stored_token.purpose == "password_reset"
        assert stored_token.token_hash
        assert stored_token.token_hash != reset_token
        assert len(stored_token.token_hash) == 64

    confirm_response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "password": "new-password-123"},
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json() == {"status": "password_reset"}

    old_session_response = client.get(
        "/api/auth/session",
        headers={"Authorization": f"Bearer {old_session_token}"},
    )
    assert old_session_response.status_code == 401

    old_login_response = client.post(
        "/api/auth/login",
        json={"email": "reset-user@example.com", "password": "old-password-123"},
    )
    assert old_login_response.status_code == 401

    new_login_response = client.post(
        "/api/auth/login",
        json={"email": "reset-user@example.com", "password": "new-password-123"},
    )
    assert new_login_response.status_code == 200

    reuse_response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": reset_token, "password": "another-password-123"},
    )
    assert reuse_response.status_code == 400
    assert reuse_response.json()["detail"] == "invalid_or_expired_reset_token"


def test_password_reset_request_does_not_reveal_unknown_email(monkeypatch) -> None:
    sent_messages: list[tuple[str, str]] = []
    monkeypatch.setattr(
        password_reset_router,
        "send_password_reset_email",
        lambda email, url: sent_messages.append((email, url)) or True,
    )

    response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "missing@example.com"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "accepted"}
    assert sent_messages == []

    with SessionLocal() as db:
        stored_token = db.query(MagicLinkToken).one()
        assert stored_token.purpose == "password_reset"
        assert stored_token.email_normalized.startswith("password-reset-decoy:")


def test_password_reset_request_uses_forwarded_client_ip_from_trusted_proxy() -> None:
    proxy_client = TestClient(
        ProxyHeadersMiddleware(app, trusted_hosts=["testclient"]),
    )

    response = proxy_client.post(
        "/api/auth/password-reset/request",
        json={"email": "forwarded@example.com"},
        headers={"x-forwarded-for": "203.0.113.10"},
    )

    assert response.status_code == 200
    with SessionLocal() as db:
        stored_limit = (
            db.query(PasswordResetRateLimit)
            .filter_by(rate_limit_key="ip:anytoolai:ru:203.0.113.10")
            .one()
        )
        assert stored_limit.count == 1


def test_password_reset_request_derives_scope_server_side_for_rate_limits() -> None:
    for index in range(password_reset_router.PASSWORD_RESET_IP_RATE_LIMIT_MAX):
        response = client.post(
            "/api/auth/password-reset/request",
            json={
                "tenant_id": f"attacker-{index}",
                "region": "not-a-region",
                "email": f"scope-probe-{index}@example.com",
            },
        )
        assert response.status_code == 200

    limited_response = client.post(
        "/api/auth/password-reset/request",
        json={
            "tenant_id": "attacker-final",
            "region": "still-not-a-region",
            "email": "scope-probe-final@example.com",
        },
    )
    assert limited_response.status_code == 429
    assert limited_response.json()["detail"] == "password_reset_rate_limited"

    with SessionLocal() as db:
        assert db.query(MagicLinkToken).count() == password_reset_router.PASSWORD_RESET_IP_RATE_LIMIT_MAX
        stored_token = db.query(MagicLinkToken).first()
        assert stored_token is not None
        assert stored_token.tenant_id == "anytoolai"
        assert stored_token.region == "ru"
        ip_limit = (
            db.query(PasswordResetRateLimit)
            .filter_by(rate_limit_key="ip:anytoolai:ru:testclient")
            .one()
        )
        assert ip_limit.count == password_reset_router.PASSWORD_RESET_IP_RATE_LIMIT_MAX


def test_password_reset_request_is_rate_limited_per_account() -> None:
    for _ in range(password_reset_router.PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX):
        response = client.post(
            "/api/auth/password-reset/request",
            json={"email": "probe@example.com"},
        )
        assert response.status_code == 200

    limited_response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "probe@example.com"},
    )
    assert limited_response.status_code == 429
    assert limited_response.json()["detail"] == "password_reset_rate_limited"


def test_password_reset_account_limit_does_not_rollback_ip_counter() -> None:
    for _ in range(password_reset_router.PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX):
        response = client.post(
            "/api/auth/password-reset/request",
            json={"email": "rollback-probe@example.com"},
        )
        assert response.status_code == 200

    limited_response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "rollback-probe@example.com"},
    )
    assert limited_response.status_code == 429

    with SessionLocal() as db:
        stored_limit = (
            db.query(PasswordResetRateLimit)
            .filter_by(rate_limit_key="ip:anytoolai:ru:testclient")
            .one()
        )
        assert stored_limit.count == password_reset_router.PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX + 1


def test_password_reset_confirm_invalidates_other_outstanding_reset_tokens(monkeypatch) -> None:
    first_token = "first-reset-token-with-enough-length-123"
    second_token = "second-reset-token-with-enough-length-456"
    tokens = iter([first_token, second_token])

    def make_token() -> tuple[str, str, datetime]:
        token = next(tokens)
        return (
            token,
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
            datetime.now(timezone.utc) + timedelta(minutes=30),
        )

    monkeypatch.setattr(password_reset_router, "make_password_reset_token", make_token)
    monkeypatch.setattr(password_reset_router, "send_password_reset_email", lambda email, url: True)

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "multi-reset@example.com",
            "password": "old-password-123",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert register_response.status_code == 200

    first_request = client.post(
        "/api/auth/password-reset/request",
        json={"email": "multi-reset@example.com"},
    )
    second_request = client.post(
        "/api/auth/password-reset/request",
        json={"email": "multi-reset@example.com"},
    )
    assert first_request.status_code == 200
    assert second_request.status_code == 200

    confirm_response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": first_token, "password": "new-password-123"},
    )
    assert confirm_response.status_code == 200

    second_confirm_response = client.post(
        "/api/auth/password-reset/confirm",
        json={"token": second_token, "password": "another-password-123"},
    )
    assert second_confirm_response.status_code == 400
    assert second_confirm_response.json()["detail"] == "invalid_or_expired_reset_token"


def test_password_reset_request_is_rate_limited_per_ip_across_emails() -> None:
    for index in range(password_reset_router.PASSWORD_RESET_IP_RATE_LIMIT_MAX):
        response = client.post(
            "/api/auth/password-reset/request",
            json={"email": f"probe-{index}@example.com"},
        )
        assert response.status_code == 200

    limited_response = client.post(
        "/api/auth/password-reset/request",
        json={"email": "another-probe@example.com"},
    )
    assert limited_response.status_code == 429
    assert limited_response.json()["detail"] == "password_reset_rate_limited"


def test_password_reset_rate_limit_window_resets_after_expiry() -> None:
    key = "account:anytoolai:ru:window-reset@example.com"
    first_attempt_at = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)
    next_window_at = first_attempt_at + timedelta(
        minutes=password_reset_router.PASSWORD_RESET_RATE_LIMIT_WINDOW_MINUTES + 1
    )

    with SessionLocal() as db:
        password_reset_router.enforce_password_reset_rate_limit(
            db=db,
            key=key,
            limit=1,
            now=first_attempt_at,
        )
        db.commit()

        password_reset_router.enforce_password_reset_rate_limit(
            db=db,
            key=key,
            limit=1,
            now=next_window_at,
        )
        db.commit()

        stored_limit = db.query(PasswordResetRateLimit).filter_by(rate_limit_key=key).one()
        assert stored_limit.count == 1
        assert stored_limit.window_start == next_window_at


def test_password_reset_rate_limit_prunes_expired_keys() -> None:
    now = datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)
    expired_at = now - timedelta(minutes=1)

    with SessionLocal() as db:
        db.add(
            PasswordResetRateLimit(
                rate_limit_key="account:anytoolai:ru:expired@example.com",
                count=1,
                window_start=expired_at - timedelta(minutes=15),
                expires_at=expired_at,
            )
        )
        db.commit()

        password_reset_router.prune_expired_password_reset_rate_limits(db=db, now=now)
        db.commit()

        assert db.query(PasswordResetRateLimit).count() == 0


def test_password_reset_request_prunes_expired_reset_tokens() -> None:
    now = datetime(2026, 7, 29, 9, 30, tzinfo=timezone.utc)

    with SessionLocal() as db:
        db.add(
            MagicLinkToken(
                tenant_id="anytoolai",
                region="ru",
                email_normalized="password-reset-decoy:expired",
                token_hash=hashlib.sha256(b"expired-reset-token").hexdigest(),
                purpose="password_reset",
                expires_at=now - timedelta(minutes=1),
            )
        )
        db.commit()

        password_reset_router.prune_expired_password_reset_tokens(db=db, now=now)
        db.commit()

        assert db.query(MagicLinkToken).count() == 0


def test_password_reset_email_delivery_disabled_is_observable(monkeypatch, caplog) -> None:
    monkeypatch.setattr(password_reset_router, "send_password_reset_email", lambda email, url: False)

    with caplog.at_level("WARNING", logger="payment_portal.identity.password_reset"):
        password_reset_router.send_password_reset_email_safely(
            "reset-user@example.com",
            "http://localhost/reset",
        )

    assert "password_reset_email_delivery_disabled" in caplog.text


def test_password_reset_email_delivery_failure_is_observable(monkeypatch, caplog) -> None:
    def fail_delivery(email: str, url: str) -> bool:
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(password_reset_router, "send_password_reset_email", fail_delivery)

    with caplog.at_level("WARNING", logger="payment_portal.identity.password_reset"):
        password_reset_router.send_password_reset_email_safely(
            "reset-user@example.com",
            "http://localhost/reset",
        )

    assert "password_reset_email_delivery_failed" in caplog.text
    assert caplog.records[-1].structured["reason"] == "TimeoutError"


def test_cloudpayments_webhook_is_saved_without_secret_hmac() -> None:
    response = client.post(
        "/api/cloudpayments/pay",
        headers={"Content-HMAC": "demo-signature"},
        json={
            "InvoiceId": "invoice-1",
            "TransactionId": "tx-1",
            "AccountId": "user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "CardFirstSix": "411111",
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
    assert event.amount_minor == 99000
    assert str(event.amount) == "990.00"
    assert event.currency == "RUB"
    assert event.raw_payload["CardFirstSix"] == "[redacted]"
    assert event.headers["content-hmac"] == "[redacted]"
    assert event.status == "failed"
    assert event.error_code == "order_not_found"


def test_malformed_cloudpayments_payload_omits_raw_body() -> None:
    response = client.post(
        "/api/cloudpayments/pay",
        headers={"Content-HMAC": "demo-signature", "Content-Type": "application/json"},
        content='{"InvoiceId":"invoice-raw","CardFirstSix":"411111","Token":"secret-token"',
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}

    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.status == "failed"
    assert event.error_code == "payload_parse_error"
    assert event.raw_payload == {"_raw": "[omitted: payload_parse_error]"}
    assert "411111" not in str(event.raw_payload)
    assert "secret-token" not in str(event.raw_payload)


def test_cloudpayments_webhook_rejects_non_object_json_payload() -> None:
    response = client.post(
        "/api/cloudpayments/pay",
        headers={"Content-HMAC": "demo-signature", "Content-Type": "application/json"},
        content='["not-a-provider-object"]',
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}

    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.status == "failed"
    assert event.error_code == "payload_parse_error"
    assert event.raw_payload == {"_raw": "[omitted: payload_parse_error]"}


def test_cloudpayments_payload_redaction_recurses_through_lists() -> None:
    response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": "invoice-list-redaction",
            "TransactionId": "tx-list-redaction",
            "AccountId": "user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Nested": [{"CardFirstSix": "411111", "safe": "kept"}],
        },
    )

    assert response.status_code == 200

    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.raw_payload["Nested"] == [{"CardFirstSix": "[redacted]", "safe": "kept"}]


def test_cloudpayments_idempotency_key_fallbacks_are_stable() -> None:
    assert (
        _event_idempotency_key("pay", "event-1", "invoice-1", "tx-1", None, "hash-1")
        == "cloudpayments:event:event-1"
    )
    assert (
        _event_idempotency_key("refund", None, "invoice-1", "tx-1", "refund-1", "hash-1")
        == "cloudpayments:refund:refund-1"
    )
    assert (
        _event_idempotency_key("pay", None, "invoice-1", "tx-1", None, "hash-1")
        == "cloudpayments:pay:transaction:tx-1"
    )
    assert (
        _event_idempotency_key("pay", None, "invoice-1", None, None, "hash-1")
        == "cloudpayments:pay:invoice:invoice-1:hash-1"
    )
    assert (
        _event_idempotency_key("pay", None, None, None, None, "hash-1")
        == "cloudpayments:pay:payload:hash-1"
    )


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
    assert missing_document["acceptance_text"] == "Я принимаю документ «Публичная оферта»."
    assert "offer" not in missing_document["acceptance_text"]
    assert "2026-07-ru-v1" not in missing_document["acceptance_text"]
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
    require_signed_cloudpayments_webhooks_for_test()
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

    assert event.status == "failed"
    assert event.error_message == "invalid_cloudpayments_signature"
    assert event.processed_at

    object.__setattr__(settings, "cloudpayments_api_secret", "")
    os.environ["CLOUDPAYMENTS_API_SECRET"] = ""


def test_cloudpayments_webhook_rejects_missing_secret_when_provider_is_enabled() -> None:
    require_signed_cloudpayments_webhooks_for_test()
    from app.settings import settings  # noqa: E402

    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", "")

    response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": "invoice-enabled-missing-secret",
            "TransactionId": "tx-enabled-missing-secret",
            "AccountId": "user@example.com",
            "Amount": "1490.00",
            "Currency": "RUB",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_cloudpayments_signature"

    object.__setattr__(settings, "cloudpayments_enabled", False)


def test_new_cloudpayments_webhook_types_reject_unsigned_disabled_mode() -> None:
    require_signed_cloudpayments_webhooks_for_test()

    scenarios = [
        (
            "confirm",
            {
                "InvoiceId": "invoice-disabled-confirm",
                "TransactionId": "tx-disabled-confirm",
                "AccountId": "disabled-confirm@example.com",
                "Amount": "990.00",
                "Currency": "RUB",
            },
        ),
        (
            "cancel",
            {
                "InvoiceId": "invoice-disabled-cancel",
                "TransactionId": "tx-disabled-cancel",
                "AccountId": "disabled-cancel@example.com",
                "Amount": "990.00",
                "Currency": "RUB",
            },
        ),
        (
            "recurrent",
            {
                "Id": "sub-disabled",
                "AccountId": "disabled-recurrent@example.com",
                "Amount": "990.00",
                "Currency": "RUB",
                "Status": "Active",
            },
        ),
    ]

    responses = [
        client.post(f"/api/cloudpayments/{endpoint}", json=payload)
        for endpoint, payload in scenarios
    ]

    assert [response.status_code for response in responses] == [400, 400, 400]
    assert [response.json()["detail"] for response in responses] == [
        "invalid_cloudpayments_signature",
        "invalid_cloudpayments_signature",
        "invalid_cloudpayments_signature",
    ]
    with SessionLocal() as db:
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert [event.endpoint for event in events] == ["confirm", "cancel", "recurrent"]
    assert [event.status for event in events] == ["failed", "failed", "failed"]
    assert {event.error_code for event in events} == {"invalid_cloudpayments_signature"}


def test_cloudpayments_webhook_rejects_non_ascii_signature_without_500() -> None:
    secret = "test-secret"
    from app.settings import settings  # noqa: E402

    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", secret)
    payload = b'{"InvoiceId":"invoice-non-ascii","Amount":"1490.00","Currency":"RUB"}'
    valid_signature = base64.b64encode(
        hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    ).decode("ascii")

    assert (
        verify_cloudpayments_signature(
            payload,
            {"Content-HMAC": f"{valid_signature}å"},
        )
        is False
    )

    object.__setattr__(settings, "cloudpayments_enabled", False)
    object.__setattr__(settings, "cloudpayments_api_secret", "")
