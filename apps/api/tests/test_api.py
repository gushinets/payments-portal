from __future__ import annotations

import base64
import hashlib
import hmac
import uuid
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from apps.api.tests.support.settings import configure_api_test_environment
from apps.api.tests.support.settings import override_settings

configure_api_test_environment()

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event, inspect  # noqa: E402
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware  # noqa: E402

from app.domains.billing.router import get_subscription as get_account_subscription_route  # noqa: E402
from app.domains.billing.router import list_subscriptions as list_account_subscriptions_route  # noqa: E402
import app.domains.identity.password_reset as password_reset_router  # noqa: E402
from app.database import Base, SessionLocal, engine  # noqa: E402
from app.integrations.cloudpayments import adapter as cloudpayments_adapter_module  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AcceptanceKind,
    AuthSession,
    BillingPeriod,
    Bundle,
    BundleProduct,
    BundleProductStatus,
    BundleStatus,
    CheckoutSession,
    Entitlement,
    EntitlementSource,
    EntitlementStatus,
    DocumentAcceptance,
    DocumentVersion,
    LegalEntity,
    LegalEntityStatus,
    LegalEntityType,
    MagicLinkPurpose,
    MagicLinkToken,
    Order,
    OrderItem,
    OrderItemType,
    OrderStatus,
    Payment,
    PaymentProviderAccount,
    PaymentStatus,
    PaymentWebhookEvent,
    PaymentWebhookEventStatus,
    Plan,
    PlanStatus,
    PasswordResetRateLimit,
    Product,
    ProductStatus,
    Refund,
    RefundStatus,
    Subscription,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    SubscriptionStatus,
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
    cloudpayments_adapter_module.verify_cloudpayments_signature = _original_verify_cloudpayments_signature


def teardown_function() -> None:
    require_signed_cloudpayments_webhooks_for_test()


def cloudpayments_signature(raw_body: bytes, secret: str = "test-secret") -> str:
    return base64.b64encode(hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).digest()).decode("ascii")


def signed_cloudpayments_post(endpoint: str, payload: bytes, *, secret: str = "test-secret"):
    return client.post(
        f"/api/cloudpayments/{endpoint}",
        headers={
            "Content-HMAC": cloudpayments_signature(payload, secret),
            "Content-Type": "application/json",
        },
        content=payload,
    )


def assert_opaque_invoice_id(invoice_id: str) -> None:
    assert uuid.UUID(invoice_id).hex == invoice_id


def plan_id_for_code(plan_code: str, *, tenant_id: str = "anytoolai", region: str = "ru") -> str:
    with SessionLocal() as db:
        plan = (
            db.query(Plan)
            .filter(
                Plan.tenant_id == tenant_id,
                Plan.region == region,
                Plan.code == plan_code,
            )
            .one()
        )
        return str(plan.id)


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
            "plan_id": plan_id_for_code(plan_code),
            "auto_renew": False,
            "entrypoint_type": "product",
            "entrypoint_value": product,
        },
    )
    assert checkout_response.status_code == 200, checkout_response.text
    return checkout_response.json()["purchase"]["invoice_id"]


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


def accept_document_for_token(
    token: str,
    *,
    document: DocumentVersion,
    entrypoint_type: str | None = "product",
    entrypoint_value: str | None = "document-summary",
    plan_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    from app.domains.legal.service import expected_acceptance_text_hash

    document_identity = inspect(document).identity
    assert document_identity is not None
    document_id = document_identity[0]
    with SessionLocal() as db:
        current_document = db.get(DocumentVersion, document_id)
        assert current_document is not None
        acceptance_text_hash = expected_acceptance_text_hash(current_document)
        document_type = current_document.doc_type
        document_tenant_id = current_document.tenant_id
        document_region = current_document.region

    acceptance_payload = {
        "document_version_id": str(document_id),
        "acceptance_text_hash": acceptance_text_hash,
        "entrypoint_type": entrypoint_type,
        "entrypoint_value": entrypoint_value,
        "metadata": metadata if metadata is not None else {},
    }
    if plan_id is not None:
        acceptance_payload["plan_id"] = plan_id
    elif document_type == "recurring_consent":
        acceptance_payload["plan_id"] = plan_id_for_code(
            "document-summary-pro",
            tenant_id=document_tenant_id,
            region=document_region,
        )

    response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json=acceptance_payload,
    )
    assert response.status_code == 200, response.text
    return response.json()["acceptance_id"]


def create_document_acceptance_row(
    db,
    *,
    document: DocumentVersion,
    user: User,
    acceptance_text_hash: str,
    tenant_id: str | None = None,
    region: str | None = None,
    accepted_at: datetime | None = None,
    entrypoint_value: str | None = None,
) -> DocumentAcceptance:
    from app.domains.legal.service import ACCEPTANCE_KIND_BY_DOC_TYPE

    acceptance = DocumentAcceptance(
        tenant_id=tenant_id or document.tenant_id,
        region=region or document.region,
        user_id=user.id,
        document_version_id=document.id,
        doc_type=document.doc_type,
        version=document.version,
        acceptance_kind=ACCEPTANCE_KIND_BY_DOC_TYPE.get(document.doc_type, AcceptanceKind.TERMS_ACCEPTANCE),
        accepted_at=accepted_at or datetime.now(timezone.utc),
        acceptance_text_hash=acceptance_text_hash,
        entrypoint_type="product" if entrypoint_value is not None else None,
        entrypoint_value=entrypoint_value,
        metadata_={"plan_id": plan_id_for_code("document-summary-pro")} if entrypoint_value is not None else {},
    )
    db.add(acceptance)
    db.commit()
    db.refresh(acceptance)
    return acceptance


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
        db.query(Product).filter(Product.tenant_id == "anytoolai", Product.code == "document-summary").first()
    )
    existing_prompt_optimizer = (
        db.query(Product).filter(Product.tenant_id == "anytoolai", Product.code == "prompt-optimizer").first()
    )
    existing_bundle = (
        db.query(Bundle).filter(Bundle.tenant_id == "anytoolai", Bundle.code == "core-tools-bundle").first()
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
        status=ProductStatus.ACTIVE,
    )
    prompt_optimizer = Product(
        tenant_id="anytoolai",
        code="prompt-optimizer",
        platform_product_id="prompt-optimizer",
        name="Prompt Optimizer",
        status=ProductStatus.ACTIVE,
    )
    bundle = Bundle(
        tenant_id="anytoolai",
        code="core-tools-bundle",
        name="Core Tools Bundle",
        status=BundleStatus.ACTIVE,
    )
    db.add_all([document_summary, prompt_optimizer, bundle])
    db.flush()
    db.add_all(
        [
            BundleProduct(
                tenant_id="anytoolai",
                bundle_id=bundle.id,
                product_id=document_summary.id,
                status=BundleProductStatus.ACTIVE,
            ),
            BundleProduct(
                tenant_id="anytoolai",
                bundle_id=bundle.id,
                product_id=prompt_optimizer.id,
                status=BundleProductStatus.ACTIVE,
            ),
        ]
    )
    document_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="document-summary-pro",
        name="Document Summary Pro",
        scope_type=SubscriptionScopeType.PRODUCT,
        product_id=document_summary.id,
        price_amount_minor=99000,
        currency="RUB",
        billing_period=BillingPeriod.MONTH,
        renewal_mode=SubscriptionRenewalMode.MANUAL,
        trial_days=7,
        status=PlanStatus.ACTIVE,
    )
    prompt_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="prompt-optimizer-pro",
        name="Prompt Optimizer Pro",
        scope_type=SubscriptionScopeType.PRODUCT,
        product_id=prompt_optimizer.id,
        price_amount_minor=99000,
        currency="RUB",
        billing_period=BillingPeriod.MONTH,
        renewal_mode=SubscriptionRenewalMode.MANUAL,
        trial_days=7,
        status=PlanStatus.ACTIVE,
    )
    bundle_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="core-tools-bundle-pro-ru",
        name="Core Tools Bundle Pro RU",
        scope_type=SubscriptionScopeType.BUNDLE,
        bundle_id=bundle.id,
        price_amount_minor=198000,
        currency="RUB",
        billing_period=BillingPeriod.MONTH,
        renewal_mode=SubscriptionRenewalMode.MANUAL,
        trial_days=7,
        status=PlanStatus.ACTIVE,
    )
    all_access_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="all-access-pro-ru",
        name="All Access Pro RU",
        scope_type=SubscriptionScopeType.ALL_ACCESS,
        price_amount_minor=198000,
        currency="RUB",
        billing_period=BillingPeriod.MONTH,
        renewal_mode=SubscriptionRenewalMode.MANUAL,
        trial_days=7,
        status=PlanStatus.ACTIVE,
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


def register_test_user(*, email: str, tenant_id: str = "anytoolai", region: str = "ru") -> str:
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


def add_active_entitlement_for_plan(db, *, user: User, plan: Plan) -> Entitlement:
    now = datetime.now(timezone.utc)
    subscription = Subscription(
        tenant_id=plan.tenant_id,
        region=plan.region,
        user_id=user.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=SubscriptionStatus.ACTIVE,
        renewal_mode=plan.renewal_mode,
        current_period_start=now - timedelta(days=1),
        current_period_end=now + timedelta(days=30),
    )
    db.add(subscription)
    db.flush()
    entitlement = Entitlement(
        tenant_id=plan.tenant_id,
        region=plan.region,
        user_id=user.id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=EntitlementStatus.ACTIVE,
        valid_from=now - timedelta(days=1),
        valid_until=now + timedelta(days=30),
        source=EntitlementSource.TRIAL,
    )
    db.add(entitlement)
    return entitlement


def test_liveness_readiness_metrics_and_request_id() -> None:
    request_id = "agent-check-123"
    canonical_live_response = client.get(
        "/api/health/live",
        headers={"X-Request-ID": request_id},
    )
    canonical_ready_response = client.get("/api/health/ready")
    metrics_response = client.get("/metrics")

    assert canonical_live_response.status_code == 200
    assert canonical_live_response.headers["X-Request-ID"] == request_id
    assert canonical_live_response.json() == {"status": "alive"}
    assert canonical_ready_response.status_code == 200
    assert canonical_ready_response.json() == {"status": "ready"}
    assert canonical_ready_response.headers["X-Request-ID"]
    assert metrics_response.status_code == 200
    assert metrics_response.headers["content-type"].startswith("text/plain")


def test_catalog_products_returns_persisted_sellable_offers_without_authentication() -> None:
    with SessionLocal() as db:
        document_summary = db.query(Product).filter(Product.code == "document-summary").one()
        document_plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        document_summary.name = "Persisted Document Summary"
        document_summary.description = "Persisted catalog description"
        document_plan.name = "Persisted Document Summary Pro"
        db.commit()

    response = client.get("/api/catalog/products")

    assert response.status_code == 200
    products = response.json()["products"]
    assert [product["code"] for product in products] == ["document-summary", "prompt-optimizer"]
    document_product = products[0]
    assert document_product["name"] == "Persisted Document Summary"
    assert document_product["description"] == "Persisted catalog description"
    assert document_product["plan"] == {
        "plan_id": document_product["plan"]["plan_id"],
        "code": "document-summary-pro",
        "name": "Persisted Document Summary Pro",
        "price_amount_minor": 99000,
        "currency": "RUB",
        "billing_period": "month",
        "renewal_mode": "manual",
        "trial_days": 7,
    }
    assert products[1]["plan"]["price_amount_minor"] == 99000
    assert products[1]["plan"]["currency"] == "RUB"


def test_catalog_products_rejects_ambiguous_product_offers() -> None:
    with SessionLocal() as db:
        document_summary = db.query(Product).filter(Product.code == "document-summary").one()
        db.add(
            Plan(
                tenant_id="anytoolai",
                region="ru",
                code="document-summary-premium",
                name="Document Summary Premium",
                scope_type=SubscriptionScopeType.PRODUCT,
                product_id=document_summary.id,
                price_amount_minor=149000,
                currency="RUB",
                billing_period=BillingPeriod.MONTH,
                renewal_mode=SubscriptionRenewalMode.MANUAL,
                trial_days=7,
                status=PlanStatus.ACTIVE,
                valid_from=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
        db.commit()

    response = client.get("/api/catalog/products")

    assert response.status_code == 500
    assert response.json()["detail"] == {
        "code": "ambiguous_catalog_product_offer",
        "product_code": "document-summary",
    }


def test_catalog_products_excludes_ineligible_offers() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        db.query(Product).filter(Product.code == "document-summary").one().status = ProductStatus.INACTIVE
        db.query(Plan).filter(Plan.code == "prompt-optimizer-pro").one().status = PlanStatus.INACTIVE

        future_product = Product(
            tenant_id="anytoolai",
            code="future-product",
            platform_product_id="future-product",
            name="Future Product",
            status=ProductStatus.ACTIVE,
        )
        expired_product = Product(
            tenant_id="anytoolai",
            code="expired-product",
            platform_product_id="expired-product",
            name="Expired Product",
            status=ProductStatus.ACTIVE,
        )
        no_plan_product = Product(
            tenant_id="anytoolai",
            code="no-plan-product",
            platform_product_id="no-plan-product",
            name="No Plan Product",
            status=ProductStatus.ACTIVE,
        )
        db.add_all([future_product, expired_product, no_plan_product])
        db.flush()
        db.add_all(
            [
                Plan(
                    tenant_id="anytoolai",
                    region="ru",
                    code="future-product-pro",
                    name="Future Product Pro",
                    scope_type=SubscriptionScopeType.PRODUCT,
                    product_id=future_product.id,
                    price_amount_minor=100,
                    currency="RUB",
                    billing_period=BillingPeriod.MONTH,
                    renewal_mode=SubscriptionRenewalMode.MANUAL,
                    trial_days=0,
                    status=PlanStatus.ACTIVE,
                    valid_from=now + timedelta(days=1),
                ),
                Plan(
                    tenant_id="anytoolai",
                    region="ru",
                    code="expired-product-pro",
                    name="Expired Product Pro",
                    scope_type=SubscriptionScopeType.PRODUCT,
                    product_id=expired_product.id,
                    price_amount_minor=100,
                    currency="RUB",
                    billing_period=BillingPeriod.MONTH,
                    renewal_mode=SubscriptionRenewalMode.MANUAL,
                    trial_days=0,
                    status=PlanStatus.ACTIVE,
                    valid_from=now - timedelta(days=2),
                    valid_to=now - timedelta(days=1),
                ),
            ]
        )
        db.commit()

    response = client.get("/api/catalog/products")

    assert response.status_code == 200
    assert response.json() == {"products": []}


def test_catalog_products_openapi_uses_named_response_schema() -> None:
    openapi = app.openapi()

    response_schema = openapi["paths"]["/api/catalog/products"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]

    assert response_schema == {"$ref": "#/components/schemas/CatalogProductsResponse"}


def test_invalid_request_id_is_replaced() -> None:
    response = client.get(
        "/api/health/live",
        headers={"X-Request-ID": "invalid request id"},
    )

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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )

    assert checkout_response.status_code == 409
    missing_documents = checkout_response.json()["detail"]["documents"]
    required_seeded_types = {
        document["doc_type"] for document in RU_DOCUMENT_VERSIONS if document["requires_acceptance"]
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
        seeded_documents_count = db.query(DocumentVersion).filter(DocumentVersion.version == "2026-07-11").count()
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )

    assert checkout_response.status_code == 200
    checkout_payload = checkout_response.json()
    assert checkout_payload["status"] == "pending"
    assert "product_state" not in checkout_payload
    assert checkout_payload["purchase"]["plan_id"] == plan_id_for_code("document-summary-pro")
    assert checkout_payload["purchase"]["scope_type"] == "product"
    assert checkout_payload["checkout"]["amount_minor"] == 99000
    assert isinstance(checkout_payload["checkout"]["amount"], (int, float))
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
        "merchant_order_id": checkout_payload["purchase"]["invoice_id"],
        "provider_invoice_id": checkout_payload["purchase"]["invoice_id"],
        "account_id": "user@example.com",
        "description": "Document Summary Pro",
        "metadata": {
            "plan_id": plan_id_for_code("document-summary-pro"),
            "product_code": "document-summary",
            "plan_code": "document-summary-pro",
            "scope_type": "product",
        },
    }
    invoice_id = checkout_payload["purchase"]["invoice_id"]
    assert invoice_id

    with SessionLocal() as db:
        user = db.query(User).one()
        order = db.query(Order).one()
        item = db.query(OrderItem).one()

    assert user.email == "user@example.com"
    assert user.tenant_id == "anytoolai"
    assert user.region == "ru"
    assert user.email_normalized == "user@example.com"
    assert order.user_id == user.id
    assert order.plan_id is not None
    assert order.status == OrderStatus.PENDING_PAYMENT
    assert order.provider_invoice_id == invoice_id
    assert item.product_code_snapshot == "document-summary"


@pytest.mark.parametrize(
    ("legacy_selector", "value"),
    (
        ("product", "document-summary"),
        ("plan_code", "document-summary-pro"),
        ("scope_type", "product"),
        ("all_access", True),
    ),
)
def test_checkout_rejects_non_plan_purchase_selectors(legacy_selector: str, value: object) -> None:
    token = register_test_user(email=f"checkout-selector-{legacy_selector}@example.com")
    payload = {
        "plan_id": plan_id_for_code("document-summary-pro"),
        "entrypoint_type": "product",
        "entrypoint_value": "document-summary",
        "auto_renew": False,
        legacy_selector: value,
    }

    response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )

    assert response.status_code == 422


def test_checkout_rejects_unknown_or_foreign_plan_id() -> None:
    token = register_test_user(email="checkout-foreign-plan@example.com")
    with SessionLocal() as db:
        product = db.query(Product).filter(Product.code == "document-summary").one()
        foreign_plan = Plan(
            tenant_id="foreign-tenant",
            region="ru",
            code="foreign-plan",
            name="Foreign Plan",
            scope_type=SubscriptionScopeType.PRODUCT,
            product_id=product.id,
            price_amount_minor=99000,
            currency="RUB",
            billing_period=BillingPeriod.MONTH,
            renewal_mode=SubscriptionRenewalMode.MANUAL,
            trial_days=0,
            status=PlanStatus.ACTIVE,
            valid_from=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(foreign_plan)
        db.commit()
        foreign_plan_id = str(foreign_plan.id)

    for plan_id in (str(uuid.uuid4()), foreign_plan_id):
        response = client.post(
            "/api/auth/checkout-intent",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "plan_id": plan_id,
                "entrypoint_type": "product",
                "entrypoint_value": "document-summary",
                "auto_renew": False,
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "unknown_product_plan"


def test_session_product_state_uses_user_tenant_product_when_codes_overlap() -> None:
    token = register_test_user(email="tenant-product-state@example.com")

    with SessionLocal() as db:
        tenant_b_product = Product(
            tenant_id="tenant-b",
            code="shared-product",
            platform_product_id="tenant-b-shared-product",
            name="Tenant B Shared Product",
            status=ProductStatus.ACTIVE,
        )
        tenant_a_product = Product(
            tenant_id="anytoolai",
            code="shared-product",
            platform_product_id="tenant-a-shared-product",
            name="Tenant A Shared Product",
            status=ProductStatus.ACTIVE,
        )
        db.add_all([tenant_b_product, tenant_a_product])
        db.flush()
        tenant_a_plan = Plan(
            tenant_id="anytoolai",
            region="ru",
            code="shared-product-pro",
            name="Shared Product Pro",
            scope_type=SubscriptionScopeType.PRODUCT,
            product_id=tenant_a_product.id,
            price_amount_minor=99000,
            currency="RUB",
            billing_period=BillingPeriod.MONTH,
            renewal_mode=SubscriptionRenewalMode.MANUAL,
            trial_days=7,
            status=PlanStatus.ACTIVE,
        )
        db.add(tenant_a_plan)
        db.flush()
        user = db.query(User).filter(User.email_normalized == "tenant-product-state@example.com").one()
        add_active_entitlement_for_plan(db, user=user, plan=tenant_a_plan)
        tenant_a_product_id = tenant_a_product.id
        tenant_b_product_id = tenant_b_product.id
        db.commit()

    response = client.get(
        "/api/auth/session?product=shared-product",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert tenant_a_product_id != tenant_b_product_id
    assert response.status_code == 200
    assert response.json()["product_state"]["status"] == "active"


def test_session_product_state_uses_user_tenant_bundle_when_codes_overlap() -> None:
    token = register_test_user(email="tenant-bundle-state@example.com")

    with SessionLocal() as db:
        tenant_b_bundle = Bundle(
            tenant_id="tenant-b",
            code="shared-bundle",
            name="Tenant B Shared Bundle",
            status=BundleStatus.ACTIVE,
        )
        tenant_a_bundle = Bundle(
            tenant_id="anytoolai",
            code="shared-bundle",
            name="Tenant A Shared Bundle",
            status=BundleStatus.ACTIVE,
        )
        db.add_all([tenant_b_bundle, tenant_a_bundle])
        db.flush()
        tenant_a_plan = Plan(
            tenant_id="anytoolai",
            region="ru",
            code="shared-bundle-pro",
            name="Shared Bundle Pro",
            scope_type=SubscriptionScopeType.BUNDLE,
            bundle_id=tenant_a_bundle.id,
            price_amount_minor=198000,
            currency="RUB",
            billing_period=BillingPeriod.MONTH,
            renewal_mode=SubscriptionRenewalMode.MANUAL,
            trial_days=7,
            status=PlanStatus.ACTIVE,
        )
        db.add(tenant_a_plan)
        db.flush()
        user = db.query(User).filter(User.email_normalized == "tenant-bundle-state@example.com").one()
        add_active_entitlement_for_plan(db, user=user, plan=tenant_a_plan)
        tenant_a_bundle_id = tenant_a_bundle.id
        tenant_b_bundle_id = tenant_b_bundle.id
        db.commit()

    response = client.get(
        "/api/auth/session?product=shared-bundle",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert tenant_a_bundle_id != tenant_b_bundle_id
    assert response.status_code == 200
    assert response.json()["product_state"]["status"] == "active"


def test_session_unknown_product_does_not_use_active_all_access_entitlement() -> None:
    token = register_test_user(email="unknown-product-all-access@example.com")

    with SessionLocal() as db:
        all_access_plan = db.query(Plan).filter(Plan.code == "all-access-pro-ru").one()
        user = db.query(User).filter(User.email_normalized == "unknown-product-all-access@example.com").one()
        add_active_entitlement_for_plan(db, user=user, plan=all_access_plan)
        db.commit()

    unknown_response = client.get(
        "/api/auth/session?product=unknown-code",
        headers={"Authorization": f"Bearer {token}"},
    )
    all_access_response = client.get(
        "/api/auth/session?product=all-access",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert unknown_response.status_code == 200
    assert unknown_response.json()["product_state"]["status"] == "inactive"
    assert all_access_response.status_code == 200
    assert all_access_response.json()["product_state"]["status"] == "active"


def test_session_valid_product_entitlement_is_active() -> None:
    token = register_test_user(email="valid-product-entitlement@example.com")

    with SessionLocal() as db:
        document_plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        user = db.query(User).filter(User.email_normalized == "valid-product-entitlement@example.com").one()
        add_active_entitlement_for_plan(db, user=user, plan=document_plan)
        db.commit()

    response = client.get(
        "/api/auth/session?product=document-summary",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["product_state"]["status"] == "active"


def test_session_valid_bundle_entitlement_is_active() -> None:
    token = register_test_user(email="valid-bundle-entitlement@example.com")

    with SessionLocal() as db:
        bundle_plan = db.query(Plan).filter(Plan.code == "core-tools-bundle-pro-ru").one()
        user = db.query(User).filter(User.email_normalized == "valid-bundle-entitlement@example.com").one()
        add_active_entitlement_for_plan(db, user=user, plan=bundle_plan)
        db.commit()

    response = client.get(
        "/api/auth/session?product=core-tools-bundle",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["product_state"]["status"] == "active"


def test_session_wrong_tenant_order_does_not_make_product_state_pending() -> None:
    token = register_test_user(email="wrong-tenant-order@example.com")

    with SessionLocal() as db:
        user = db.query(User).filter(User.email_normalized == "wrong-tenant-order@example.com").one()
        tenant_b_product = Product(
            tenant_id="tenant-b",
            code="document-summary",
            platform_product_id="tenant-b-document-summary",
            name="Tenant B Document Summary",
            status=ProductStatus.ACTIVE,
        )
        provider_account = PaymentProviderAccount(
            tenant_id="tenant-b",
            region="ru",
            provider="tenant-b-cloudpayments",
            public_identifier="pk_tenant_b",
            default_currency="RUB",
            enabled=True,
            test_mode=True,
            config={},
        )
        db.add_all([tenant_b_product, provider_account])
        db.flush()
        tenant_b_plan = Plan(
            tenant_id="tenant-b",
            region="ru",
            code="tenant-b-document-summary-pro",
            name="Tenant B Document Summary Pro",
            scope_type=SubscriptionScopeType.PRODUCT,
            product_id=tenant_b_product.id,
            price_amount_minor=99000,
            currency="RUB",
            billing_period=BillingPeriod.MONTH,
            renewal_mode=SubscriptionRenewalMode.MANUAL,
            trial_days=7,
            status=PlanStatus.ACTIVE,
        )
        db.add(tenant_b_plan)
        db.flush()
        add_active_entitlement_for_plan(db, user=user, plan=tenant_b_plan)
        order = Order(
            tenant_id="tenant-b",
            region="ru",
            order_number="RU-WRONG-TENANT-ORDER",
            user_id=user.id,
            status=OrderStatus.PENDING_PAYMENT,
            amount_minor=99000,
            currency="RUB",
            provider=provider_account.provider,
            provider_account_id=provider_account.id,
            merchant_order_id="wrong-tenant-order",
            provider_invoice_id="wrong-tenant-invoice",
        )
        db.add(order)
        db.flush()
        db.add(
            OrderItem(
                order_id=order.id,
                item_type=OrderItemType.PRODUCT_PLAN,
                product_id=tenant_b_product.id,
                product_code_snapshot="document-summary",
                title_snapshot="Tenant B Document Summary Pro",
                quantity=1,
                list_amount_minor=99000,
                discount_amount_minor=0,
                unit_amount_minor=99000,
                amount_minor=99000,
                currency="RUB",
                trial_days_snapshot=7,
                pricing_snapshot={"scope_type": "product"},
            )
        )
        db.commit()

    response = client.get(
        "/api/auth/session?product=document-summary",
        headers={"Authorization": f"Bearer {token}"},
    )
    product_state = response.json()["product_state"]

    assert response.status_code == 200
    assert product_state["status"] == "inactive"
    assert product_state["invoice_id"] is None


def test_manual_checkout_does_not_require_recurring_consent() -> None:
    with SessionLocal() as db:
        legal_entity = create_legal_entity(db)
        create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "manual-without-recurring@example.com",
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )

    assert checkout_response.status_code == 200, checkout_response.text
    with SessionLocal() as db:
        checkout = db.query(CheckoutSession).one()
        order = db.query(Order).one()

    assert checkout.metadata_["auto_renew"] is False
    assert checkout.metadata_["recurring_consent_acceptance_id"] is None
    assert order.metadata_["auto_renew"] is False
    assert order.metadata_["recurring_consent_acceptance_id"] is None


def test_checkout_rejects_automatic_renewal_for_manual_only_plan() -> None:
    with SessionLocal() as db:
        legal_entity = create_legal_entity(db)
        create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "automatic-manual-only@example.com",
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
        },
    )

    assert checkout_response.status_code == 409
    assert checkout_response.json()["detail"]["code"] == "automatic_renewal_not_permitted"


def test_automatic_checkout_without_acceptance_returns_document_flow() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )
        document_id = document.id

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "automatic-without-consent@example.com",
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
        },
    )

    assert checkout_response.status_code == 409
    detail = checkout_response.json()["detail"]
    assert detail["code"] == "missing_required_documents"
    assert detail["documents"] == [
        {
            "document_version_id": str(document_id),
            "doc_type": "recurring_consent",
            "version": "2026-08-recurring-v1",
            "title": "Согласие на рекуррентные платежи",
            "url_path": "/ru/recurring_consent",
            "acceptance_text": "Я принимаю документ «Согласие на рекуррентные платежи».",
            "acceptance_text_hash": detail["documents"][0]["acceptance_text_hash"],
        }
    ]


def test_automatic_checkout_requires_exact_acceptance_id_after_document_acceptance() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "automatic-missing-exact-id@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]
    accept_document_for_token(
        token,
        document=document,
        entrypoint_value="document-summary",
    )

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
        },
    )

    assert checkout_response.status_code == 409
    assert checkout_response.json()["detail"]["code"] == "missing_required_documents"
    assert checkout_response.json()["detail"]["documents"][0]["doc_type"] == "recurring_consent"


def test_checkout_persists_exact_recurring_consent_reference() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        db.commit()
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "automatic-with-consent@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]
    acceptance_id = accept_document_for_token(
        token,
        document=document,
        entrypoint_type="product",
        entrypoint_value="document-summary",
        metadata={"plan_code": "document-summary-pro"},
    )

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": acceptance_id,
        },
    )

    assert checkout_response.status_code == 200, checkout_response.text
    with SessionLocal() as db:
        checkout = db.query(CheckoutSession).one()
        order = db.query(Order).one()
        acceptance = db.query(DocumentAcceptance).one()

    assert acceptance.metadata_["plan_id"] == plan_id_for_code("document-summary-pro")
    assert checkout.metadata_["recurring_consent_acceptance_id"] == acceptance_id
    assert order.metadata_["recurring_consent_acceptance_id"] == acceptance_id


def test_non_recurring_acceptance_drops_client_plan_id_metadata() -> None:
    with SessionLocal() as db:
        legal_entity = create_legal_entity(db)
        document = create_document_version(db, legal_entity=legal_entity, doc_type="offer")

    token = register_test_user(email="non-recurring-metadata-spoof@example.com")
    from app.domains.legal.service import expected_acceptance_text_hash

    response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "document_version_id": str(document.id),
            "acceptance_text_hash": expected_acceptance_text_hash(document),
            "metadata": {"plan_id": "client-spoof", "client_field": "preserved"},
        },
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        acceptance = db.query(DocumentAcceptance).one()

    assert "plan_id" not in acceptance.metadata_
    assert acceptance.metadata_["client_field"] == "preserved"


def test_automatic_checkout_rejects_recurring_consent_for_wrong_plan_id() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        other_plan = db.query(Plan).filter(Plan.code == "prompt-optimizer-pro").one()
        other_plan_id = str(other_plan.id)
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "recurring-scope@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]
    acceptance_id = accept_document_for_token(
        token,
        document=document,
        plan_id=other_plan_id,
    )

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": acceptance_id,
        },
    )

    assert checkout_response.status_code == 409
    assert checkout_response.json()["detail"]["code"] == "missing_required_documents"
    assert checkout_response.json()["detail"]["documents"][0]["doc_type"] == "recurring_consent"


def test_recurring_consent_requires_typed_plan_and_entrypoint_context() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan_id = str(plan.id)
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    token = register_test_user(email="recurring-context-required@example.com")
    from app.domains.legal.service import expected_acceptance_text_hash

    for missing_field in ("plan_id", "entrypoint_type", "entrypoint_value"):
        payload = {
            "document_version_id": str(document.id),
            "acceptance_text_hash": expected_acceptance_text_hash(document),
            "plan_id": plan_id,
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
        }
        payload.pop(missing_field)
        response = client.post(
            "/api/legal/acceptances",
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
        )
        assert response.status_code == 400
        assert response.json()["detail"]["code"] == "recurring_consent_context_required"


def test_recurring_consent_metadata_cannot_spoof_typed_plan_id() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan_id = str(plan.id)
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        other_plan = db.query(Plan).filter(Plan.code == "prompt-optimizer-pro").one()
        other_plan_id = str(other_plan.id)
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    token = register_test_user(email="recurring-metadata-spoof@example.com")
    acceptance_id = accept_document_for_token(
        token,
        document=document,
        plan_id=plan_id,
        metadata={"plan_id": other_plan_id},
    )
    response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id,
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": acceptance_id,
        },
    )

    assert response.status_code == 200, response.text
    with SessionLocal() as db:
        acceptance = db.query(DocumentAcceptance).one()
    assert acceptance.metadata_["plan_id"] == plan_id


def test_versioned_plans_require_plan_bound_recurring_consent() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        product = db.query(Product).filter(Product.code == "document-summary").one()
        plan_a = Plan(
            tenant_id="anytoolai",
            region="ru",
            code="versioned-consent-pro",
            name="Versioned Consent A",
            scope_type=SubscriptionScopeType.PRODUCT,
            product_id=product.id,
            price_amount_minor=99000,
            currency="RUB",
            billing_period=BillingPeriod.MONTH,
            renewal_mode=SubscriptionRenewalMode.AUTOMATIC,
            trial_days=7,
            status=PlanStatus.ACTIVE,
            valid_from=now - timedelta(days=2),
            valid_to=now + timedelta(days=1),
            metadata_={},
        )
        plan_b = Plan(
            tenant_id="anytoolai",
            region="ru",
            code="versioned-consent-pro",
            name="Versioned Consent B",
            scope_type=SubscriptionScopeType.PRODUCT,
            product_id=product.id,
            price_amount_minor=109000,
            currency="RUB",
            billing_period=BillingPeriod.MONTH,
            renewal_mode=SubscriptionRenewalMode.AUTOMATIC,
            trial_days=0,
            status=PlanStatus.INACTIVE,
            valid_from=now - timedelta(days=1),
            valid_to=None,
            metadata_={},
        )
        db.add_all([plan_a, plan_b])
        db.flush()
        plan_a_id = plan_a.id
        plan_b_id = plan_b.id
        assert plan_a.code == plan_b.code
        assert plan_a_id != plan_b_id
        db.commit()
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-versioned-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    token = register_test_user(email="versioned-consent@example.com")
    acceptance_a_id = accept_document_for_token(
        token,
        document=document,
        plan_id=str(plan_a_id),
    )

    with SessionLocal() as db:
        plan_a = db.get(Plan, plan_a_id)
        plan_b = db.get(Plan, plan_b_id)
        assert plan_a is not None
        assert plan_b is not None
        plan_a.status = PlanStatus.INACTIVE
        db.commit()
        plan_b.status = PlanStatus.ACTIVE
        db.commit()

    checkout_payload = {
        "plan_id": str(plan_b_id),
        "entrypoint_type": "product",
        "entrypoint_value": "document-summary",
        "auto_renew": True,
        "recurring_consent_acceptance_id": acceptance_a_id,
    }
    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json=checkout_payload,
    )

    assert checkout_response.status_code == 409
    detail = checkout_response.json()["detail"]
    assert detail["code"] == "missing_required_documents"
    assert [document["document_version_id"] for document in detail["documents"]] == [str(document.id)]
    acceptance_b_id = accept_document_for_token(
        token,
        document=document,
        plan_id=str(plan_b_id),
    )
    checkout_payload["recurring_consent_acceptance_id"] = acceptance_b_id
    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json=checkout_payload,
    )

    assert checkout_response.status_code == 200, checkout_response.text
    assert checkout_response.json()["purchase"]["plan_id"] == str(plan_b_id)
    with SessionLocal() as db:
        acceptances = db.query(DocumentAcceptance).all()
    assert {acceptance.metadata_["plan_id"] for acceptance in acceptances} == {
        str(plan_a_id),
        str(plan_b_id),
    }


def test_automatic_checkout_paid_subscription_remains_manual_until_provider_attach() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "automatic-manual-until-provider@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]
    acceptance_id = accept_document_for_token(
        token,
        document=document,
        entrypoint_value="document-summary",
    )

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": acceptance_id,
        },
    )
    assert checkout_response.status_code == 200, checkout_response.text
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]

    webhook_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-auto-renew-initial-payment",
            "AccountId": "automatic-manual-until-provider@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    assert webhook_response.status_code == 200
    with SessionLocal() as db:
        order = db.query(Order).one()
        subscription = db.query(Subscription).one()

    assert order.metadata_["auto_renew"] is True
    assert order.metadata_["recurring_consent_acceptance_id"] == acceptance_id
    assert subscription.renewal_mode == "manual"
    assert subscription.provider_subscription_id is None
    assert subscription.recurring_consent_acceptance_id is None


def test_checkout_rejects_recurring_acceptance_from_another_user() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    owner_response = client.post(
        "/api/auth/register",
        json={
            "email": "recurring-owner@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    owner_token = owner_response.json()["token"]
    owner_acceptance_id = accept_document_for_token(
        owner_token,
        document=document,
        entrypoint_value="document-summary",
    )

    buyer_response = client.post(
        "/api/auth/register",
        json={
            "email": "recurring-buyer@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    buyer_token = buyer_response.json()["token"]
    accept_document_for_token(
        buyer_token,
        document=document,
        entrypoint_value="document-summary",
    )

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": owner_acceptance_id,
        },
    )

    assert checkout_response.status_code == 409
    assert checkout_response.json()["detail"]["code"] == "missing_required_documents"
    assert checkout_response.json()["detail"]["documents"][0]["doc_type"] == "recurring_consent"


def test_checkout_rejects_recurring_acceptance_from_another_tenant_or_region() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )
        foreign_entity = create_legal_entity(db, region="eu")
        foreign_document = create_document_version(
            db,
            legal_entity=foreign_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Recurring consent",
        )
        product = db.query(Product).filter(Product.code == "document-summary").one()
        foreign_plan = Plan(
            tenant_id="anytoolai",
            region="eu",
            code="document-summary-pro",
            name="Document Summary Pro EU",
            scope_type=SubscriptionScopeType.PRODUCT,
            product_id=product.id,
            price_amount_minor=99000,
            currency="EUR",
            billing_period=BillingPeriod.MONTH,
            renewal_mode=SubscriptionRenewalMode.AUTOMATIC,
            trial_days=7,
            status=PlanStatus.ACTIVE,
            valid_from=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(foreign_plan)
        db.commit()

    buyer_response = client.post(
        "/api/auth/register",
        json={
            "email": "recurring-tenant-buyer@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    buyer_token = buyer_response.json()["token"]
    accept_document_for_token(
        buyer_token,
        document=document,
        entrypoint_value="document-summary",
    )

    foreign_response = client.post(
        "/api/auth/register",
        json={
            "tenant_id": "anytoolai",
            "region": "eu",
            "email": "recurring-foreign@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    foreign_token = foreign_response.json()["token"]
    foreign_acceptance_id = accept_document_for_token(
        foreign_token,
        document=foreign_document,
        entrypoint_value="document-summary",
    )

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {buyer_token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": foreign_acceptance_id,
        },
    )

    assert checkout_response.status_code == 409
    assert checkout_response.json()["detail"]["code"] == "missing_required_documents"
    assert checkout_response.json()["detail"]["documents"][0]["doc_type"] == "recurring_consent"


def test_checkout_rejects_acceptance_with_wrong_kind() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        recurring_document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )
        offer_document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="offer",
            version="2026-08-offer-v1",
            title="Публичная оферта",
        )

    buyer_response = client.post(
        "/api/auth/register",
        json={
            "email": "recurring-wrong-kind@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = buyer_response.json()["token"]
    accept_document_for_token(
        token,
        document=recurring_document,
        entrypoint_value="document-summary",
    )
    wrong_acceptance_id = accept_document_for_token(
        token,
        document=offer_document,
        entrypoint_value="document-summary",
    )

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": wrong_acceptance_id,
        },
    )

    assert checkout_response.status_code == 409
    assert checkout_response.json()["detail"]["code"] == "missing_required_documents"
    assert checkout_response.json()["detail"]["documents"][0]["doc_type"] == "recurring_consent"


def test_checkout_rejects_recurring_acceptance_for_another_entrypoint() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    buyer_response = client.post(
        "/api/auth/register",
        json={
            "email": "recurring-entrypoint@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = buyer_response.json()["token"]
    wrong_entrypoint_acceptance_id = accept_document_for_token(
        token,
        document=document,
        entrypoint_value="prompt-optimizer",
    )

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": wrong_entrypoint_acceptance_id,
        },
    )

    assert checkout_response.status_code == 409
    assert checkout_response.json()["detail"]["code"] == "missing_required_documents"
    assert checkout_response.json()["detail"]["documents"][0]["doc_type"] == "recurring_consent"


def test_checkout_rejects_recurring_acceptance_from_the_future() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )

    buyer_response = client.post(
        "/api/auth/register",
        json={
            "email": "recurring-future@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = buyer_response.json()["token"]
    future_acceptance_id = accept_document_for_token(
        token,
        document=document,
        entrypoint_value="document-summary",
    )
    accept_document_for_token(
        token,
        document=document,
        entrypoint_value="document-summary",
    )

    with SessionLocal() as db:
        future_acceptance = db.get(DocumentAcceptance, uuid.UUID(future_acceptance_id))
        future_acceptance.accepted_at = datetime.now(timezone.utc) + timedelta(days=1)
        db.commit()

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": future_acceptance_id,
        },
    )

    assert checkout_response.status_code == 409
    assert checkout_response.json()["detail"]["code"] == "missing_required_documents"
    assert checkout_response.json()["detail"]["documents"][0]["doc_type"] == "recurring_consent"


def test_checkout_requires_new_recurring_acceptance_when_document_version_changes() -> None:
    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        first_document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )
        legal_entity_id = legal_entity.id
        first_document_id = first_document.id

    buyer_response = client.post(
        "/api/auth/register",
        json={
            "email": "recurring-stale@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = buyer_response.json()["token"]
    stale_acceptance_id = accept_document_for_token(
        token,
        document=first_document,
        entrypoint_value="document-summary",
    )

    with SessionLocal() as db:
        first_document = db.get(DocumentVersion, first_document_id)
        first_document.is_active = False
        legal_entity = db.get(LegalEntity, legal_entity_id)
        second_document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v2",
            title="Согласие на рекуррентные платежи",
        )
        second_document_id = second_document.id

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": stale_acceptance_id,
        },
    )

    assert checkout_response.status_code == 409
    detail = checkout_response.json()["detail"]
    assert detail["code"] == "missing_required_documents"
    assert [document["document_version_id"] for document in detail["documents"]] == [str(second_document_id)]


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
                "plan_id": plan_id_for_code("document-summary-pro"),
                "entrypoint_type": "product",
                "entrypoint_value": "document-summary",
                "auto_renew": False,
            },
        )

        assert checkout_response.status_code == 409
        assert checkout_response.json()["detail"] == "cloudpayments_public_terminal_id_missing"
        with SessionLocal() as db:
            assert db.query(Order).count() == 0
            assert db.query(OrderItem).count() == 0
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )

    assert checkout_response.status_code == 200
    assert checkout_response.json()["checkout"]["action"]["mode"] == "auth"
    with SessionLocal() as db:
        order = db.query(Order).one()
        assert order.metadata_["payment_mode"] == "auth"
        assert db.query(OrderItem).count() == 1


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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )

    assert checkout_response.status_code == 409
    assert checkout_response.json()["detail"] == "provider_currency_mismatch"
    with SessionLocal() as db:
        assert db.query(Order).count() == 0
        assert db.query(OrderItem).count() == 0


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
            "plan_id": plan_id_for_code("core-tools-bundle-pro-ru"),
            "entrypoint_value": "core-tools-bundle",
            "entrypoint_type": "bundle",
            "auto_renew": False,
        },
    )

    assert checkout_response.status_code == 200
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]
    assert_opaque_invoice_id(invoice_id)

    with SessionLocal() as db:
        order = db.query(Order).one()
        item = db.query(OrderItem).one()

    assert order.plan_id == bundle_plan_id
    assert order.amount_minor == 198000
    assert item.item_type == OrderItemType.BUNDLE_PLAN
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
            "plan_id": str(all_access_plan_id),
            "entrypoint_type": "catalog",
            "entrypoint_value": "campaign",
            "auto_renew": False,
        },
    )

    assert checkout_response.status_code == 200
    purchase = checkout_response.json()["purchase"]
    assert_opaque_invoice_id(purchase["invoice_id"])
    assert purchase["plan_code"] == "all-access-pro-ru"
    assert purchase["scope_type"] == "all_access"

    with SessionLocal() as db:
        order = db.query(Order).one()
        item = db.query(OrderItem).one()

    assert order.plan_id == all_access_plan_id
    assert order.amount_minor == 198000
    assert item.item_type == OrderItemType.ALL_ACCESS_PLAN
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
        plan.status = PlanStatus.INACTIVE
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
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
        product.status = ProductStatus.INACTIVE
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
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
        bundle.status = BundleStatus.INACTIVE
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
            "plan_id": plan_id_for_code("core-tools-bundle-pro-ru"),
            "entrypoint_value": "core-tools-bundle",
            "entrypoint_type": "bundle",
            "auto_renew": False,
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]

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

    assert event.status is PaymentWebhookEventStatus.FAILED
    assert event.error_code == "amount_mismatch"
    assert order.status is OrderStatus.PENDING_PAYMENT
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
                "plan_id": plan_id_for_code("document-summary-pro"),
                "entrypoint_type": "product",
                "entrypoint_value": "document-summary",
                "auto_renew": False,
            },
        )
        invoice_id = checkout_response.json()["purchase"]["invoice_id"]
        valid_payload = (
            b'{"InvoiceId":"' + invoice_id.encode("utf-8") + b'","TransactionId":"tx-check-valid-1",'
            b'"AccountId":"check-user@example.com","Amount":"990.00",'
            b'"Currency":"RUB","Status":"Completed"}'
        )
        amount_mismatch_payload = (
            b'{"InvoiceId":"' + invoice_id.encode("utf-8") + b'","TransactionId":"tx-check-amount-mismatch-1",'
            b'"AccountId":"check-user@example.com","Amount":"9.90",'
            b'"Currency":"RUB","Status":"Completed"}'
        )
        unknown_payload = (
            b'{"InvoiceId":"unknown-invoice","TransactionId":"tx-check-unknown-1",'
            b'"AccountId":"check-user@example.com",'
            b'"Amount":"990.00","Currency":"RUB","Status":"Completed"}'
        )
        missing_transaction_payload = (
            b'{"InvoiceId":"' + invoice_id.encode("utf-8") + b'","AccountId":"check-user@example.com",'
            b'"Amount":"990.00","Currency":"RUB","Status":"Completed"}'
        )

        valid_response = signed_cloudpayments_post("check", valid_payload)
        mismatch_response = signed_cloudpayments_post("check", amount_mismatch_payload)
        unknown_response = signed_cloudpayments_post("check", unknown_payload)
        missing_transaction_response = signed_cloudpayments_post("check", missing_transaction_payload)

        assert valid_response.status_code == 200
        assert valid_response.json() == {"code": 0}
        assert mismatch_response.status_code == 200
        assert mismatch_response.json() == {"code": 12}
        assert unknown_response.status_code == 200
        assert unknown_response.json() == {"code": 10}
        assert missing_transaction_response.status_code == 200
        assert missing_transaction_response.json() == {"code": 13}
        with SessionLocal() as db:
            events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
            order = db.query(Order).one()

        assert [event.status for event in events] == [
            PaymentWebhookEventStatus.PROCESSED,
            PaymentWebhookEventStatus.FAILED,
            PaymentWebhookEventStatus.FAILED,
            PaymentWebhookEventStatus.FAILED,
        ]
        assert events[1].error_code == "amount_mismatch"
        assert events[2].error_code == "order_not_found"
        assert events[3].error_code == "missing_transaction_id"
        assert order.status is OrderStatus.PENDING_PAYMENT
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
                "plan_id": plan_id_for_code("document-summary-pro"),
                "entrypoint_type": "product",
                "entrypoint_value": "document-summary",
                "auto_renew": False,
            },
        )
        invoice_id = checkout_response.json()["purchase"]["invoice_id"]
        account_mismatch_payload = (
            b'{"InvoiceId":"' + invoice_id.encode("utf-8") + b'","TransactionId":"tx-check-account-mismatch-1",'
            b'"AccountId":"other@example.com","Amount":"990.00",'
            b'"Currency":"RUB","Status":"Completed"}'
        )
        currency_mismatch_payload = (
            b'{"InvoiceId":"' + invoice_id.encode("utf-8") + b'","TransactionId":"tx-check-currency-mismatch-1",'
            b'"AccountId":"check-account-user@example.com","Amount":"990.00",'
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

        assert [event.error_code for event in events] == [
            "account_mismatch",
            "currency_mismatch",
        ]
    finally:
        allow_unsigned_cloudpayments_webhooks_for_test()
        object.__setattr__(settings, "cloudpayments_enabled", False)
        object.__setattr__(settings, "cloudpayments_api_secret", "")


def test_successful_pay_webhook_is_saved_and_activates_access() -> None:
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]

    webhook_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-success-1",
            "AccountId": "user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
            "Data": {
                "product_code": "document-summary",
                "plan_code": "document-summary-pro",
            },
        },
    )

    assert webhook_response.status_code == 200

    status_response = client.get(f"/api/auth/payment-status?invoice_id={invoice_id}&email=user@example.com")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["product_state"]["status"] == "active"
    assert status_payload["product_state"]["transaction_id"] == "tx-success-1"
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
    assert event.status is PaymentWebhookEventStatus.PROCESSED
    assert event.order_id == order.id
    assert event.payment_id == payment.id
    assert order.status is OrderStatus.PAID
    assert order.provider_invoice_id == invoice_id
    assert payment.status is PaymentStatus.SUCCEEDED
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

    assert [order.status for order in orders] == [OrderStatus.PENDING_PAYMENT] * len(scenarios)
    assert payment_count == 0
    assert [event.status for event in events] == [PaymentWebhookEventStatus.FAILED] * len(scenarios)
    assert {event.error_code for event in events} == {"payment_schema_mismatch"}


def test_auth_mode_completed_pay_marks_order_paid() -> None:
    invoice_id = create_checkout_invoice(
        email="dms-completed-pay-user@example.com",
        widget_mode="auth",
    )

    completed_pay_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-dms-completed-pay-1",
            "AccountId": "dms-completed-pay-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )

    assert completed_pay_response.status_code == 200
    assert completed_pay_response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        event = db.query(PaymentWebhookEvent).one()

    assert order.status is OrderStatus.PAID
    assert order.paid_at
    assert payment.status is PaymentStatus.SUCCEEDED
    assert payment.captured_at
    assert event.status is PaymentWebhookEventStatus.PROCESSED
    assert event.event_type == "payment.succeeded"


def test_authorized_pay_requires_confirm_or_cancel_to_reach_terminal_state() -> None:
    invoice_id = create_checkout_invoice(
        email="dms-confirm-user@example.com",
        widget_mode="auth",
    )

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
            db.query(PaymentWebhookEvent).filter(PaymentWebhookEvent.transaction_id == "tx-dms-confirm-1").one()
        )

    assert authorized_order.status is OrderStatus.PENDING_PAYMENT
    assert authorized_order.paid_at is None
    assert authorized_payment.status is PaymentStatus.AUTHORIZED
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

    assert confirmed_order.status is OrderStatus.PAID
    assert confirmed_order.paid_at
    assert confirmed_payment.status is PaymentStatus.SUCCEEDED
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
    for (
        invoice_id,
        email,
        provider_status,
        expected_response,
        expected_error,
    ) in scenarios:
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

    assert [response.status_code for response, _, _ in responses] == [
        200,
        200,
        200,
        200,
    ]
    assert [response.json() for response, _, _ in responses] == [
        expected_response for _, expected_response, _ in responses
    ]
    with SessionLocal() as db:
        orders = db.query(Order).order_by(Order.created_at).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert [order.status for order in orders] == [OrderStatus.PENDING_PAYMENT] * len(scenarios)
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.FAILED,
        PaymentWebhookEventStatus.FAILED,
        PaymentWebhookEventStatus.FAILED,
        PaymentWebhookEventStatus.PROCESSED,
    ]
    assert [event.error_code for event in events] == [expected_error for _, _, expected_error in responses]


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
    assert [response.json() for response in authorized_responses] == [
        {"code": 0},
        {"code": 0},
    ]
    assert [response.status_code for response in confirm_responses] == [200, 200]
    assert [response.json() for response in confirm_responses] == [
        {"code": 0},
        {"code": 0},
    ]
    with SessionLocal() as db:
        order = db.query(Order).one()
        payments = db.query(Payment).order_by(Payment.provider_payment_id).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status is OrderStatus.PAID
    assert order.paid_at
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-second-auth-confirm-1", PaymentStatus.SUCCEEDED),
        ("tx-second-auth-confirm-2", PaymentStatus.SUCCEEDED),
    ]
    assert all(payment.authorized_at for payment in payments)
    assert all(payment.captured_at for payment in payments)
    assert [event.endpoint for event in events] == ["pay", "pay", "confirm", "confirm"]
    assert [event.status for event in events] == [PaymentWebhookEventStatus.PROCESSED] * 4
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

    assert order.status is OrderStatus.CANCELED
    assert order.canceled_at
    assert order.paid_at is None
    assert payment.status is PaymentStatus.CANCELED
    assert payment.currency == "RUB"
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.PROCESSED,
    ]


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

    assert [order.status for order in orders] == [OrderStatus.PENDING_PAYMENT, OrderStatus.PENDING_PAYMENT]
    assert payment_count == 0
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.FAILED,
        PaymentWebhookEventStatus.FAILED,
    ]
    assert {event.error_code for event in events} == {"payment_schema_mismatch"}


def test_legacy_orders_without_payment_mode_snapshot_default_to_charge_schema() -> None:
    email = "legacy-charge-schema@example.com"
    invoice_id = create_checkout_invoice(email=email)
    with SessionLocal() as db:
        order = db.query(Order).filter(Order.provider_invoice_id == invoice_id).one()
        order.metadata_ = {key: value for key, value in order.metadata_.items() if key != "payment_mode"}
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

    assert order.status is OrderStatus.PENDING_PAYMENT
    assert payment_count == 0
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.FAILED,
        PaymentWebhookEventStatus.FAILED,
        PaymentWebhookEventStatus.FAILED,
        PaymentWebhookEventStatus.FAILED,
    ]
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
                payment = db.query(Payment).filter(Payment.provider_payment_id == scenario["transaction_id"]).one()

            assert order.status is OrderStatus.PAID
            assert order.paid_at
            assert payment.status is PaymentStatus.SUCCEEDED
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
                "plan_id": plan_id_for_code("document-summary-pro"),
                "entrypoint_type": "product",
                "entrypoint_value": "document-summary",
                "auto_renew": False,
            },
        )
        invoice_id = checkout_response.json()["purchase"]["invoice_id"]
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

        assert event.status is PaymentWebhookEventStatus.PROCESSED
        assert event.raw_payload["CardFirstSix"] == "[redacted]"
        assert event.raw_payload["Token"] == "[redacted]"  # noqa: S105
        assert payment.status is PaymentStatus.SUCCEEDED
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]

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
        entitlement_count = db.query(Entitlement).count()

    assert order.status is OrderStatus.PAYMENT_FAILED
    assert payment.status is PaymentStatus.FAILED
    assert payment.failure_code == "5"
    assert payment.failure_message_safe == "Insufficient funds"
    assert entitlement_count == 0


def test_payment_status_projects_product_state_from_final_and_pending_orders() -> None:
    pending_email = "projection-pending@example.com"
    pending_invoice_id = create_checkout_invoice(email=pending_email)

    pending_response = client.get(f"/api/auth/payment-status?invoice_id={pending_invoice_id}&email={pending_email}")
    assert pending_response.status_code == 200
    pending_payload = pending_response.json()
    assert pending_payload["product_state"]["status"] == "pending"
    assert pending_payload["order"]["status"] == "pending_payment"

    with SessionLocal() as db:
        pending_order = db.query(Order).filter(Order.provider_invoice_id == pending_invoice_id).one()
        pending_order.status = OrderStatus.CREATED
        db.commit()

    created_response = client.get(f"/api/auth/payment-status?invoice_id={pending_invoice_id}&email={pending_email}")
    assert created_response.status_code == 200
    created_payload = created_response.json()
    assert created_payload["product_state"]["status"] == "pending"
    assert created_payload["order"]["status"] == "created"

    failed_email = "projection-failed@example.com"
    failed_invoice_id = create_checkout_invoice(email=failed_email)
    failed_webhook_response = client.post(
        "/api/cloudpayments/fail",
        json={
            "InvoiceId": failed_invoice_id,
            "TransactionId": "tx-projection-failed",
            "AccountId": failed_email,
            "Amount": "990.00",
            "Currency": "RUB",
            "ReasonCode": "5",
            "Reason": "Insufficient funds",
        },
    )
    assert failed_webhook_response.status_code == 200

    failed_response = client.get(f"/api/auth/payment-status?invoice_id={failed_invoice_id}&email={failed_email}")
    assert failed_response.status_code == 200
    failed_payload = failed_response.json()
    assert failed_payload["product_state"]["status"] == "inactive"
    assert failed_payload["order"]["status"] == "payment_failed"
    assert failed_payload["payment"]["status"] == "failed"

    active_email = "projection-active@example.com"
    active_invoice_id = create_checkout_invoice(email=active_email)
    active_webhook_response = client.post(
        "/api/cloudpayments/pay",
        json={
            "InvoiceId": active_invoice_id,
            "TransactionId": "tx-projection-active",
            "AccountId": active_email,
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )
    assert active_webhook_response.status_code == 200

    active_response = client.get(f"/api/auth/payment-status?invoice_id={active_invoice_id}&email={active_email}")
    assert active_response.status_code == 200
    active_payload = active_response.json()
    assert active_payload["product_state"]["status"] == "active"
    assert active_payload["order"]["status"] == "paid"
    assert active_payload["payment"]["status"] == "succeeded"

    seed_cloudpayments_provider_account(widget_mode="auth")
    canceled_email = "projection-canceled@example.com"
    canceled_invoice_id = create_checkout_invoice(email=canceled_email, widget_mode="auth")
    canceled_webhook_response = client.post(
        "/api/cloudpayments/cancel",
        json={
            "InvoiceId": canceled_invoice_id,
            "TransactionId": "tx-projection-canceled",
            "AccountId": canceled_email,
            "Amount": "990.00",
            "Currency": "RUB",
        },
    )
    assert canceled_webhook_response.status_code == 200

    canceled_response = client.get(f"/api/auth/payment-status?invoice_id={canceled_invoice_id}&email={canceled_email}")
    assert canceled_response.status_code == 200
    canceled_payload = canceled_response.json()
    assert canceled_payload["product_state"]["status"] == "inactive"
    assert canceled_payload["order"]["status"] == "canceled"
    assert canceled_payload["payment"]["status"] == "canceled"

    refunded_email = "projection-refunded@example.com"
    refunded_invoice_id = create_checkout_invoice(email=refunded_email, widget_mode="auth")
    confirm_webhook_response = client.post(
        "/api/cloudpayments/confirm",
        json={
            "InvoiceId": refunded_invoice_id,
            "TransactionId": "tx-projection-refunded",
            "AccountId": refunded_email,
            "Amount": "990.00",
            "Currency": "RUB",
            "Status": "Completed",
        },
    )
    assert confirm_webhook_response.status_code == 200
    refund_webhook_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": refunded_invoice_id,
            "TransactionId": "tx-projection-refunded",
            "RefundId": "refund-projection-refunded",
            "Amount": "990.00",
            "Currency": "RUB",
            "Reason": "customer_request",
        },
    )
    assert refund_webhook_response.status_code == 200

    refunded_response = client.get(f"/api/auth/payment-status?invoice_id={refunded_invoice_id}&email={refunded_email}")
    assert refunded_response.status_code == 200
    refunded_payload = refunded_response.json()
    assert refunded_payload["product_state"]["status"] == "inactive"
    assert refunded_payload["order"]["status"] == "refunded"
    assert refunded_payload["payment"]["status"] == "refunded"


def test_signed_check_after_failed_attempt_allows_retry() -> None:
    require_signed_cloudpayments_webhooks_for_test()
    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", "test-secret")
    try:
        invoice_id = create_checkout_invoice(email="retry-after-fail@example.com")
        fail_payload = (
            b'{"InvoiceId":"' + invoice_id.encode("utf-8") + b'","TransactionId":"tx-retry-fail-1",'
            b'"AccountId":"retry-after-fail@example.com",'
            b'"Amount":"990.00","Currency":"RUB",'
            b'"ReasonCode":"5","Reason":"Insufficient funds"}'
        )
        check_payload = (
            b'{"InvoiceId":"' + invoice_id.encode("utf-8") + b'","TransactionId":"tx-retry-check-1",'
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

        assert order.status is OrderStatus.PAYMENT_FAILED
        assert [event.endpoint for event in events] == ["fail", "check"]
        assert [event.status for event in events] == [
            PaymentWebhookEventStatus.PROCESSED,
            PaymentWebhookEventStatus.PROCESSED,
        ]
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]

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

    assert confirmed_order.status is OrderStatus.PAID
    assert confirmed_payment.status is PaymentStatus.SUCCEEDED

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
            "plan_id": plan_id_for_code("prompt-optimizer-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "prompt-optimizer",
            "auto_renew": False,
        },
    )
    cancel_invoice_id = cancel_checkout_response.json()["purchase"]["invoice_id"]

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

    assert canceled_order.status is OrderStatus.CANCELED
    assert canceled_order.canceled_at
    assert canceled_payment.status is PaymentStatus.CANCELED


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

    assert order.status is OrderStatus.PAID
    assert payment.status is PaymentStatus.SUCCEEDED
    assert event.status is PaymentWebhookEventStatus.PROCESSED
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
        confirm_event = db.query(PaymentWebhookEvent).filter(PaymentWebhookEvent.endpoint == "confirm").one()

    assert order.status is OrderStatus.PENDING_PAYMENT
    assert payment.status is PaymentStatus.AUTHORIZED
    assert payment.amount_minor == 99000
    assert payment.captured_at is None
    assert confirm_event.status is PaymentWebhookEventStatus.FAILED
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
        confirm_event = db.query(PaymentWebhookEvent).filter(PaymentWebhookEvent.endpoint == "confirm").one()

    assert order.status is OrderStatus.PENDING_PAYMENT
    assert payment.status is PaymentStatus.AUTHORIZED
    assert payment.amount_minor == 99000
    assert payment.captured_at is None
    assert confirm_event.status is PaymentWebhookEventStatus.FAILED
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

    assert order.status is OrderStatus.CANCELED
    assert payment.status is PaymentStatus.CANCELED
    assert payment.currency == "RUB"
    assert event.status is PaymentWebhookEventStatus.PROCESSED


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
            event = db.query(PaymentWebhookEvent).filter(PaymentWebhookEvent.invoice_id == invoice_id).one()
            payment_count = db.query(Payment).filter(Payment.order_id == order.id).count()

        assert order.status is OrderStatus.PENDING_PAYMENT
        assert event.status is PaymentWebhookEventStatus.FAILED
        assert event.error_code == "missing_transaction_id"
        assert payment_count == 0


def test_late_pay_or_confirm_does_not_reopen_canceled_order() -> None:
    seed_cloudpayments_provider_account(widget_mode="auth")
    scenarios = [
        {
            "email": "late-pay-after-cancel@example.com",
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "endpoint": "pay",
            "transaction_id": "tx-late-pay-after-cancel",
        },
        {
            "email": "late-confirm-after-cancel@example.com",
            "plan_id": plan_id_for_code("prompt-optimizer-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "prompt-optimizer",
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
                "plan_id": scenario["plan_id"],
                "entrypoint_type": scenario["entrypoint_type"],
                "entrypoint_value": scenario["entrypoint_value"],
                "auto_renew": False,
            },
        )
        invoice_id = checkout_response.json()["purchase"]["invoice_id"]
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
                "Status": "Authorized" if scenario["endpoint"] == "pay" else "Completed",
            },
        )

        assert cancel_response.status_code == 200
        assert cancel_response.json() == {"code": 0}
        assert late_response.status_code == 200
        assert late_response.json() == {"code": 0}
        with SessionLocal() as db:
            order = db.query(Order).filter(Order.provider_invoice_id == invoice_id).one()
            payment = db.query(Payment).filter(Payment.provider_payment_id == scenario["transaction_id"]).one()
            events = (
                db.query(PaymentWebhookEvent)
                .filter(PaymentWebhookEvent.invoice_id == invoice_id)
                .order_by(PaymentWebhookEvent.received_at)
                .all()
            )

        assert order.status is OrderStatus.CANCELED
        assert order.paid_at is None
        assert order.canceled_at
        assert payment.status is PaymentStatus.CANCELED
        assert [event.endpoint for event in events] == ["cancel", scenario["endpoint"]]
        assert [event.status for event in events] == [
            PaymentWebhookEventStatus.PROCESSED,
            PaymentWebhookEventStatus.IGNORED,
        ]
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]

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

    assert order.status is OrderStatus.PAID
    assert order.paid_at
    assert order.failed_at is None
    assert [payment.status for payment in payments] == [PaymentStatus.SUCCEEDED, PaymentStatus.FAILED]


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

    assert order.status is OrderStatus.CANCELED
    assert order.canceled_at
    assert order.failed_at is None
    assert payment.status is PaymentStatus.CANCELED
    assert payment.failed_at is None
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.PROCESSED,
    ]


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

    assert order.status is OrderStatus.PAID
    assert order.paid_at
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-first-success-1", PaymentStatus.SUCCEEDED),
        ("tx-second-success-1", PaymentStatus.SUCCEEDED),
    ]
    assert [event.endpoint for event in events] == ["pay", "check", "pay"]
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.FAILED,
        PaymentWebhookEventStatus.PROCESSED,
    ]
    assert events[1].error_code == "order_not_payable"
    assert events[2].payment_id == payments[1].id
    assert events[2].error_code is None


def test_payment_status_surfaces_late_charge_on_canceled_order_after_later_fail() -> None:
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
    late_fail_response = client.post(
        "/api/cloudpayments/fail",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-late-distinct-fail",
            "AccountId": "late-charge-refund@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "ReasonCode": "5",
            "Reason": "Insufficient funds",
        },
    )
    status_response = client.get(
        f"/api/auth/payment-status?invoice_id={invoice_id}&email=late-charge-refund@example.com"
    )

    assert cancel_response.json() == {"code": 0}
    assert late_pay_response.json() == {"code": 0}
    assert late_fail_response.json() == {"code": 0}
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["order"]["status"] == "canceled"
    assert status_payload["payment"]["status"] == "succeeded"
    assert status_payload["payment"]["provider_payment_id"] == "tx-late-distinct-charge"
    with SessionLocal() as db:
        order = db.query(Order).one()
        payments = db.query(Payment).order_by(Payment.provider_payment_id).all()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert order.status is OrderStatus.CANCELED
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-canceled-attempt", PaymentStatus.CANCELED),
        ("tx-late-distinct-charge", PaymentStatus.SUCCEEDED),
        ("tx-late-distinct-fail", PaymentStatus.FAILED),
    ]
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.PROCESSED,
    ]
    assert [event.error_code for event in events] == [
        None,
        None,
        None,
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

    assert order.status is OrderStatus.PARTIALLY_REFUNDED
    assert [(payment.provider_payment_id, payment.status) for payment in payments] == [
        ("tx-multi-success-refund-1", PaymentStatus.REFUNDED),
        ("tx-multi-success-refund-2", PaymentStatus.SUCCEEDED),
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]
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
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.DUPLICATE,
    ]
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]
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

    status_response = client.get(f"/api/auth/payment-status?invoice_id={invoice_id}&email=refund-user@example.com")
    assert status_response.status_code == 200
    status_payload = status_response.json()
    assert status_payload["product_state"]["status"] == "inactive"
    assert status_payload["order"]["status"] == "refunded"
    assert status_payload["payment"]["status"] == "refunded"
    assert status_payload["payment"]["refunded_amount_minor"] == 99000

    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        refund = db.query(Refund).one()
        events = db.query(PaymentWebhookEvent).all()

    assert order.status is OrderStatus.REFUNDED
    assert payment.status is PaymentStatus.REFUNDED
    assert payment.refunded_amount_minor == 99000
    assert refund.status is RefundStatus.SUCCEEDED
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
        refund_event = db.query(PaymentWebhookEvent).filter(PaymentWebhookEvent.endpoint == "refund").one()

    assert payment.status is PaymentStatus.PARTIALLY_REFUNDED
    assert payment.refunded_amount_minor == 40000
    assert refund.provider_refund_id == "tx-provider-refund-id"
    assert refund.currency == "RUB"
    assert refund_event.status is PaymentWebhookEventStatus.PROCESSED
    assert refund_event.transaction_id == "tx-provider-refund-original"


def test_refund_webhook_rejects_failed_payment_without_refund_mutation() -> None:
    invoice_id = create_checkout_invoice(email="refund-failed-user@example.com")
    fail_response = client.post(
        "/api/cloudpayments/fail",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-refund-failed-original",
            "AccountId": "refund-failed-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "ReasonCode": "5",
            "Reason": "Insufficient funds",
        },
    )
    refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-refund-failed-refund",
            "PaymentTransactionId": "tx-refund-failed-original",
            "AccountId": "refund-failed-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
        },
    )

    assert fail_response.status_code == 200
    assert refund_response.status_code == 200
    assert refund_response.json() == {"code": 0}
    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()
        refund_count = db.query(Refund).count()

    assert order.status is OrderStatus.PAYMENT_FAILED
    assert payment.status is PaymentStatus.FAILED
    assert payment.refunded_amount_minor == 0
    assert refund_count == 0
    assert [event.status for event in events] == [PaymentWebhookEventStatus.PROCESSED, PaymentWebhookEventStatus.FAILED]
    assert events[-1].payment_id == payment.id
    assert events[-1].error_code == "payment_not_refundable"


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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]
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
    assert partial_status_payload["product_state"]["status"] == "active"
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

    assert order.status is OrderStatus.REFUNDED
    assert payment.status is PaymentStatus.REFUNDED
    assert payment.refunded_amount_minor == 99000
    assert [refund.provider_refund_id for refund in refunds] == [
        "refund-part-1",
        "refund-part-2",
    ]
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.PROCESSED,
    ]


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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    invoice_id = checkout_response.json()["purchase"]["invoice_id"]
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

    assert payment.status is PaymentStatus.PARTIALLY_REFUNDED
    assert payment.refunded_amount_minor == 40000
    assert len(refunds) == 1
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.PROCESSED,
    ]


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

    assert payment.status is PaymentStatus.PARTIALLY_REFUNDED
    assert payment.refunded_amount_minor == 70000
    assert len(refunds) == 1
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.FAILED,
    ]
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
    assert event.status is PaymentWebhookEventStatus.PROCESSED
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

    assert event.status is PaymentWebhookEventStatus.FAILED
    assert event.provider_account_id is None
    assert event.error_code == "provider_account_not_found"


def test_cloudpayments_payload_helpers_keep_normalization_contract() -> None:
    assert get_first({"primary": "", "fallback": "value"}, "primary", "fallback") == "value"
    assert get_first({"primary": "   ", "fallback": "value"}, "primary", "fallback") == "value"
    assert get_first({"flag": False}, "flag") is False
    assert get_first({"count": 0}, "count") == 0
    assert get_first({"blank": " \t\n"}, "blank") is None

    assert all(parse_bool(value) is True for value in ("true", "1", "yes", "y", True))
    assert all(parse_bool(value) is False for value in ("false", "0", "no", "n", False))
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
            {key: value for key, value in base_payload.items() if key != "RequireConfirmation"},
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
            "invalid_subscription_interval",
            "invalid_subscription_interval",
            0,
            {**base_payload, "Interval": "Year"},
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
            {key: value for key, value in base_payload.items() if key != "SuccessfulTransactionsNumber"},
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
            {key: value for key, value in base_payload.items() if key != "FailedTransactionsNumber"},
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

    responses = [client.post("/api/cloudpayments/recurrent", json=payload) for _, _, _, payload in scenario_payloads]

    assert [response.json()["code"] for response in responses] == [
        expected_code for _, _, expected_code, _ in scenario_payloads
    ]
    with SessionLocal() as db:
        events = db.query(PaymentWebhookEvent).all()

    assert [event.status for event in events] == [PaymentWebhookEventStatus.FAILED] * len(scenarios)
    events_by_provider_event_id = {
        event.provider_event_id: event for event in events if event.provider_event_id is not None
    }
    expected_by_provider_event_id = {
        payload["Id"]: error_code
        for _, error_code, _, payload in scenario_payloads
        if get_first(payload, "Id", "id") is not None
    }
    assert {
        provider_event_id: event.error_code for provider_event_id, event in events_by_provider_event_id.items()
    } == expected_by_provider_event_id
    missing_id_events = [event for event in events if event.provider_event_id is None]
    assert len(missing_id_events) == 2
    assert {event.error_code for event in missing_id_events} == {"missing_subscription_id"}


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

    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.PROCESSED,
        PaymentWebhookEventStatus.DUPLICATE,
        PaymentWebhookEventStatus.PROCESSED,
    ]
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
        users = db.query(User).filter(User.email_normalized == "shared@example.com").order_by(User.region).all()

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
        return (
            reset_token,
            token_hash,
            datetime.now(UTC) + timedelta(minutes=30),
        )

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
        assert stored_token.purpose == MagicLinkPurpose.PASSWORD_RESET
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
        assert stored_token.purpose == MagicLinkPurpose.PASSWORD_RESET
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
        stored_limit = db.query(PasswordResetRateLimit).filter_by(rate_limit_key="ip:anytoolai:ru:203.0.113.10").one()
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
        ip_limit = db.query(PasswordResetRateLimit).filter_by(rate_limit_key="ip:anytoolai:ru:testclient").one()
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
        stored_limit = db.query(PasswordResetRateLimit).filter_by(rate_limit_key="ip:anytoolai:ru:testclient").one()
        assert stored_limit.count == password_reset_router.PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX + 1


def test_password_reset_confirm_invalidates_other_outstanding_reset_tokens(
    monkeypatch,
) -> None:
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
                purpose=MagicLinkPurpose.PASSWORD_RESET,
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
    assert event.status is PaymentWebhookEventStatus.FAILED
    assert event.error_code == "order_not_found"


def test_cloudpayments_form_webhook_preserves_response_and_parsing_contract() -> None:
    response = client.post(
        "/api/cloudpayments/pay",
        headers={"Content-HMAC": "demo-signature"},
        data={
            "InvoiceId": "invoice-form-1",
            "TransactionId": "tx-form-1",
            "AccountId": "form-user@example.com",
            "Amount": "990.00",
            "Currency": "RUB",
            "CardFirstSix": "411111",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"code": 0}

    with SessionLocal() as db:
        event = db.query(PaymentWebhookEvent).one()

    assert event.invoice_id == "invoice-form-1"
    assert event.transaction_id == "tx-form-1"
    assert event.account_id == "form-user@example.com"
    assert event.amount_minor == 99000
    assert event.currency == "RUB"
    assert event.raw_payload["CardFirstSix"] == "[redacted]"
    assert event.status is PaymentWebhookEventStatus.FAILED
    assert event.error_code == "order_not_found"


def test_cloudpayments_webhook_rejects_non_finite_amount_without_500() -> None:
    for amount in ("NaN", "Infinity", "-Infinity"):
        response = client.post(
            "/api/cloudpayments/check",
            headers={"Content-HMAC": "demo-signature"},
            json={
                "InvoiceId": f"invoice-{amount}",
                "TransactionId": f"tx-{amount}",
                "AccountId": "non-finite-amount@example.com",
                "Amount": amount,
                "Currency": "RUB",
            },
        )

        assert response.status_code == 200
        assert response.json() == {"code": 12}

    with SessionLocal() as db:
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert len(events) == 3
    assert {event.raw_payload["Amount"] for event in events} == {"NaN", "Infinity", "-Infinity"}
    assert all(event.status is PaymentWebhookEventStatus.FAILED for event in events)
    assert all(event.error_code == "missing_amount" for event in events)
    assert all(event.error_message == "missing_amount" for event in events)
    assert all(event.amount_minor is None for event in events)
    assert all(event.amount is None for event in events)


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

    assert event.status is PaymentWebhookEventStatus.FAILED
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

    assert event.status is PaymentWebhookEventStatus.FAILED
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
        _event_idempotency_key("pay", "event-1", "invoice-1", "tx-1", None, "hash-1") == "cloudpayments:event:event-1"
    )
    assert (
        _event_idempotency_key("refund", None, "invoice-1", "tx-1", "refund-1", "hash-1")
        == "cloudpayments:refund:refund-1"
    )
    assert (
        _event_idempotency_key("pay", None, "invoice-1", "tx-1", None, "hash-1") == "cloudpayments:pay:transaction:tx-1"
    )
    assert (
        _event_idempotency_key("pay", None, "invoice-1", None, None, "hash-1")
        == "cloudpayments:pay:invoice:invoice-1:hash-1"
    )
    assert _event_idempotency_key("pay", None, None, None, None, "hash-1") == "cloudpayments:pay:payload:hash-1"


ACCOUNT_SUBSCRIPTION_RESPONSE_KEYS = {
    "subscription_id",
    "plan",
    "scope",
    "status",
    "renewal_mode",
    "current_period",
    "cancellation",
    "entitlement_validity",
}


def _account_subscription_datetime(value: datetime) -> datetime:
    return value.replace(tzinfo=None)


def _add_account_subscription_user(db, *, email: str) -> tuple[User, AuthSession, Plan]:
    now = datetime.now(timezone.utc)
    plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
    user = User(
        tenant_id="anytoolai",
        region="ru",
        email=email,
        email_normalized=email,
        status="active",
        password_hash="test-password-hash",
    )
    db.add(user)
    db.flush()
    session = AuthSession(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        token_hash=f"test-token-{email}",
        expires_at=now + timedelta(days=1),
        last_seen_at=now,
    )
    db.add(session)
    db.flush()
    return user, session, plan


def _add_account_subscription_row(
    db,
    *,
    user: User,
    plan: Plan,
    now: datetime,
    index: int = 0,
    status: SubscriptionStatus = SubscriptionStatus.ACTIVE,
    plan_id: uuid.UUID | None = None,
) -> Subscription:
    subscription = Subscription(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        plan_id=plan_id or plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=status,
        renewal_mode=SubscriptionRenewalMode.MANUAL,
        current_period_start=now - timedelta(days=index + 1),
        current_period_end=now + timedelta(days=30 + index),
        created_at=now + timedelta(seconds=index),
    )
    db.add(subscription)
    db.flush()
    return subscription


def _add_account_entitlement_row(
    db,
    *,
    user: User,
    plan: Plan,
    subscription: Subscription,
    status: EntitlementStatus,
    valid_from: datetime,
    valid_until: datetime,
    created_at: datetime,
) -> Entitlement:
    entitlement = Entitlement(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=status,
        valid_from=valid_from,
        valid_until=valid_until,
        source=EntitlementSource.TRIAL,
        created_at=created_at,
    )
    db.add(entitlement)
    return entitlement


def _seed_account_subscriptions_for_query_count(
    db,
    *,
    email: str,
    count: int,
) -> tuple[uuid.UUID, uuid.UUID]:
    now = datetime.now(timezone.utc)
    user, session, plan = _add_account_subscription_user(db, email=email)
    for index in range(count):
        subscription = _add_account_subscription_row(
            db,
            user=user,
            plan=plan,
            now=now,
            index=index,
            status=SubscriptionStatus.ACTIVE if index == 0 else SubscriptionStatus.EXPIRED,
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=subscription,
            status=EntitlementStatus.ACTIVE,
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=30 + index),
            created_at=now + timedelta(seconds=index),
        )
    db.commit()
    return user.id, session.id


def _count_sql_statements(callback) -> tuple[object, int]:
    statements = []

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", before_cursor_execute)
    try:
        result = callback()
    finally:
        event.remove(engine, "before_cursor_execute", before_cursor_execute)
    return result, len(statements)


def test_account_subscription_list_and_detail_response_shapes_are_unchanged() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        user, session, plan = _add_account_subscription_user(
            db,
            email="account-subscription-shape@example.com",
        )
        subscription = _add_account_subscription_row(db, user=user, plan=plan, now=now)
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=subscription,
            status=EntitlementStatus.ACTIVE,
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=29),
            created_at=now,
        )
        db.commit()
        user_id = user.id
        session_id = session.id
        subscription_id = subscription.id

    with SessionLocal() as db:
        user = db.get(User, user_id)
        session = db.get(AuthSession, session_id)
        list_payload = list_account_subscriptions_route(current=(user, session), db=db).model_dump(mode="json")
        detail_payload = get_account_subscription_route(
            subscription_id,
            current=(user, session),
            db=db,
        ).model_dump(mode="json")

    assert set(list_payload) == {"subscriptions"}
    assert len(list_payload["subscriptions"]) == 1
    assert list_payload["subscriptions"][0] == detail_payload
    assert set(detail_payload) == ACCOUNT_SUBSCRIPTION_RESPONSE_KEYS
    assert set(detail_payload["plan"]) == {"plan_id", "code", "name", "billing_period"}
    assert set(detail_payload["scope"]) == {
        "scope_type",
        "product_id",
        "bundle_id",
        "included_product_ids",
    }
    assert detail_payload["scope"]["included_product_ids"] == []
    assert set(detail_payload["current_period"]) == {"starts_at", "ends_at"}
    assert set(detail_payload["cancellation"]) == {"cancel_requested_at", "canceled_at"}
    assert set(detail_payload["entitlement_validity"]) == {"status", "valid_from", "valid_until"}


def test_account_subscription_projects_current_bundle_membership_product_ids() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        user, session, _ = _add_account_subscription_user(
            db,
            email="account-subscription-bundle-projection@example.com",
        )
        bundle_plan = db.query(Plan).filter(Plan.code == "core-tools-bundle-pro-ru").one()
        subscription = _add_account_subscription_row(
            db,
            user=user,
            plan=bundle_plan,
            now=now,
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=bundle_plan,
            subscription=subscription,
            status=EntitlementStatus.ACTIVE,
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=29),
            created_at=now,
        )
        membership_rows = (
            db.query(BundleProduct)
            .filter(
                BundleProduct.bundle_id == bundle_plan.bundle_id,
                BundleProduct.status == "active",
                BundleProduct.valid_from <= now,
                (BundleProduct.valid_to.is_(None) | (BundleProduct.valid_to > now)),
            )
            .all()
        )
        expected_product_ids = sorted(str(row.product_id) for row in membership_rows)
        bundle_id = bundle_plan.bundle_id
        db.commit()
        user_id = user.id
        session_id = session.id

    with SessionLocal() as db:
        user = db.get(User, user_id)
        session = db.get(AuthSession, session_id)
        response = list_account_subscriptions_route(current=(user, session), db=db)

    assert len(response.subscriptions) == 1
    scope = response.subscriptions[0].scope
    assert scope.scope_type == "bundle"
    assert scope.product_id is None
    assert scope.bundle_id == bundle_id
    assert [str(product_id) for product_id in scope.included_product_ids] == expected_product_ids


def test_account_subscription_relevant_entitlement_precedence_is_unchanged() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        user, session, plan = _add_account_subscription_user(
            db,
            email="account-subscription-entitlement-precedence@example.com",
        )
        current_subscription = _add_account_subscription_row(db, user=user, plan=plan, now=now, index=0)
        future_subscription = _add_account_subscription_row(
            db,
            user=user,
            plan=plan,
            now=now,
            index=1,
            status=SubscriptionStatus.EXPIRED,
        )
        history_subscription = _add_account_subscription_row(
            db,
            user=user,
            plan=plan,
            now=now,
            index=2,
            status=SubscriptionStatus.EXPIRED,
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=current_subscription,
            status=EntitlementStatus.REVOKED,
            valid_from=now - timedelta(days=20),
            valid_until=now - timedelta(days=10),
            created_at=now - timedelta(days=20),
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=current_subscription,
            status=EntitlementStatus.ACTIVE,
            valid_from=now + timedelta(days=1),
            valid_until=now + timedelta(days=31),
            created_at=now,
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=current_subscription,
            status=EntitlementStatus.ACTIVE,
            valid_from=now - timedelta(days=2),
            valid_until=now + timedelta(days=5),
            created_at=now + timedelta(minutes=1),
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=current_subscription,
            status=EntitlementStatus.ACTIVE,
            valid_from=now - timedelta(days=1),
            valid_until=now + timedelta(days=10),
            created_at=now,
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=future_subscription,
            status=EntitlementStatus.REVOKED,
            valid_from=now - timedelta(days=20),
            valid_until=now - timedelta(days=1),
            created_at=now - timedelta(days=20),
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=future_subscription,
            status=EntitlementStatus.ACTIVE,
            valid_from=now + timedelta(days=2),
            valid_until=now + timedelta(days=12),
            created_at=now + timedelta(minutes=2),
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=future_subscription,
            status=EntitlementStatus.ACTIVE,
            valid_from=now + timedelta(days=1),
            valid_until=now + timedelta(days=30),
            created_at=now + timedelta(minutes=1),
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=history_subscription,
            status=EntitlementStatus.EXPIRED,
            valid_from=now - timedelta(days=20),
            valid_until=now - timedelta(days=5),
            created_at=now - timedelta(days=20),
        )
        _add_account_entitlement_row(
            db,
            user=user,
            plan=plan,
            subscription=history_subscription,
            status=EntitlementStatus.REVOKED,
            valid_from=now - timedelta(days=10),
            valid_until=now - timedelta(days=1),
            created_at=now - timedelta(days=10),
        )
        db.commit()
        user_id = user.id
        session_id = session.id
        current_subscription_id = current_subscription.id
        future_subscription_id = future_subscription.id
        history_subscription_id = history_subscription.id

    with SessionLocal() as db:
        user = db.get(User, user_id)
        session = db.get(AuthSession, session_id)
        response = list_account_subscriptions_route(current=(user, session), db=db)

    subscriptions_by_id = {item.subscription_id: item for item in response.subscriptions}
    assert subscriptions_by_id[
        current_subscription_id
    ].entitlement_validity.valid_until == _account_subscription_datetime(now + timedelta(days=10))
    assert subscriptions_by_id[
        future_subscription_id
    ].entitlement_validity.valid_from == _account_subscription_datetime(now + timedelta(days=1))
    assert subscriptions_by_id[
        history_subscription_id
    ].entitlement_validity.valid_until == _account_subscription_datetime(now - timedelta(days=1))


def test_account_subscription_list_missing_plan_keeps_existing_error() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        user, session, plan = _add_account_subscription_user(
            db,
            email="account-subscription-missing-plan@example.com",
        )
        _add_account_subscription_row(
            db,
            user=user,
            plan=plan,
            now=now,
            plan_id=uuid.uuid4(),
        )
        db.commit()
        user_id = user.id
        session_id = session.id

    with SessionLocal() as db:
        user = db.get(User, user_id)
        session = db.get(AuthSession, session_id)
        with pytest.raises(HTTPException) as exc_info:
            list_account_subscriptions_route(current=(user, session), db=db)

    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == {"code": "subscription_plan_missing"}


@pytest.mark.parametrize("subscription_count", (1, 20))
def test_account_subscription_list_sql_queries_stay_constant(subscription_count: int) -> None:
    with SessionLocal() as db:
        user_id, session_id = _seed_account_subscriptions_for_query_count(
            db,
            email=f"account-subscription-query-count-{subscription_count}@example.com",
            count=subscription_count,
        )

    with SessionLocal() as db:
        user = db.get(User, user_id)
        session = db.get(AuthSession, session_id)
        response, query_count = _count_sql_statements(
            lambda: list_account_subscriptions_route(current=(user, session), db=db)
        )

    assert len(response.subscriptions) == subscription_count
    assert query_count == 3


def test_account_subscriptions_list_returns_only_authenticated_user_subscriptions() -> None:
    owner_response = client.post(
        "/api/auth/register",
        json={
            "email": "account-subscriptions-owner@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    other_response = client.post(
        "/api/auth/register",
        json={
            "email": "account-subscriptions-other@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert owner_response.status_code == 200
    assert other_response.status_code == 200
    token = owner_response.json()["token"]
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        owner = db.query(User).filter(User.email_normalized == "account-subscriptions-owner@example.com").one()
        other = db.query(User).filter(User.email_normalized == "account-subscriptions-other@example.com").one()
        provider_account = PaymentProviderAccount(
            tenant_id=owner.tenant_id,
            region=owner.region,
            provider="test-provider",
            public_identifier="pk_account_subscriptions",
            default_currency=plan.currency,
            enabled=True,
            test_mode=True,
            config={},
        )
        db.add(provider_account)
        db.flush()
        owner_subscription = Subscription(
            tenant_id=owner.tenant_id,
            region=owner.region,
            user_id=owner.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=SubscriptionStatus.ACTIVE,
            renewal_mode=SubscriptionRenewalMode.AUTOMATIC,
            current_period_start=now,
            current_period_end=now + timedelta(days=60),
            provider_account_id=provider_account.id,
            provider_subscription_id="provider-subscription-hidden",
        )
        other_subscription = Subscription(
            tenant_id=other.tenant_id,
            region=other.region,
            user_id=other.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=SubscriptionStatus.ACTIVE,
            renewal_mode=SubscriptionRenewalMode.MANUAL,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        db.add_all([owner_subscription, other_subscription])
        db.flush()
        order = Order(
            tenant_id=owner.tenant_id,
            region=owner.region,
            order_number="RU-ACCOUNT-SUBSCRIPTIONS",
            user_id=owner.id,
            plan_id=plan.id,
            status=OrderStatus.PAID,
            amount_minor=plan.price_amount_minor,
            currency=plan.currency,
            provider=provider_account.provider,
            provider_account_id=provider_account.id,
            merchant_order_id="account-subscriptions-order",
            provider_invoice_id="account-subscriptions-invoice",
            paid_at=now,
        )
        db.add(order)
        db.flush()
        db.add(
            Entitlement(
                tenant_id=owner.tenant_id,
                region=owner.region,
                user_id=owner.id,
                subscription_id=owner_subscription.id,
                plan_id=plan.id,
                scope_type=plan.scope_type,
                product_id=plan.product_id,
                bundle_id=plan.bundle_id,
                status=EntitlementStatus.ACTIVE,
                valid_from=now,
                valid_until=now + timedelta(days=30),
                source=EntitlementSource.ORDER,
                order_id=order.id,
                created_at=now,
            )
        )
        future_order = Order(
            tenant_id=owner.tenant_id,
            region=owner.region,
            order_number="RU-ACCOUNT-SUBSCRIPTIONS-FUTURE",
            user_id=owner.id,
            plan_id=plan.id,
            status=OrderStatus.PAID,
            amount_minor=plan.price_amount_minor,
            currency=plan.currency,
            provider=provider_account.provider,
            provider_account_id=provider_account.id,
            merchant_order_id="account-subscriptions-future-order",
            provider_invoice_id="account-subscriptions-future-invoice",
            paid_at=now + timedelta(days=1),
        )
        db.add(future_order)
        db.flush()
        db.add(
            Entitlement(
                tenant_id=owner.tenant_id,
                region=owner.region,
                user_id=owner.id,
                subscription_id=owner_subscription.id,
                plan_id=plan.id,
                scope_type=plan.scope_type,
                product_id=plan.product_id,
                bundle_id=plan.bundle_id,
                status=EntitlementStatus.ACTIVE,
                valid_from=now + timedelta(days=30),
                valid_until=now + timedelta(days=60),
                source=EntitlementSource.ORDER,
                order_id=future_order.id,
                created_at=now + timedelta(minutes=1),
            )
        )
        owner_subscription_id = owner_subscription.id
        other_subscription_id = other_subscription.id
        db.commit()

    response = client.get(
        "/api/account/subscriptions",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert "provider-subscription-hidden" not in response.text
    assert "provider_account_id" not in response.text
    assert "provider_subscription_id" not in response.text
    assert "payment_id" not in response.text
    assert "webhook_event_id" not in response.text
    subscriptions = response.json()["subscriptions"]
    assert len(subscriptions) == 1
    assert subscriptions[0]["subscription_id"] == str(owner_subscription_id)
    assert subscriptions[0]["subscription_id"] != str(other_subscription_id)
    assert subscriptions[0]["plan"]["code"] == "document-summary-pro"
    assert subscriptions[0]["scope"]["scope_type"] == "product"
    assert subscriptions[0]["status"] == "active"
    assert subscriptions[0]["renewal_mode"] == "automatic"
    assert subscriptions[0]["entitlement_validity"]["status"] == "active"
    assert subscriptions[0]["entitlement_validity"]["valid_from"] == now.replace(tzinfo=None).isoformat()


def test_account_subscription_detail_enforces_authenticated_ownership() -> None:
    owner_response = client.post(
        "/api/auth/register",
        json={
            "email": "account-subscription-detail-owner@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    other_register_response = client.post(
        "/api/auth/register",
        json={
            "email": "account-subscription-detail-other@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert owner_response.status_code == 200
    assert other_register_response.status_code == 200
    token = owner_response.json()["token"]
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        owner = db.query(User).filter(User.email_normalized == "account-subscription-detail-owner@example.com").one()
        other = db.query(User).filter(User.email_normalized == "account-subscription-detail-other@example.com").one()
        owner_subscription = Subscription(
            tenant_id=owner.tenant_id,
            region=owner.region,
            user_id=owner.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=SubscriptionStatus.ACTIVE,
            renewal_mode=SubscriptionRenewalMode.MANUAL,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
            cancel_requested_at=now + timedelta(days=1),
        )
        other_subscription = Subscription(
            tenant_id=other.tenant_id,
            region=other.region,
            user_id=other.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=SubscriptionStatus.ACTIVE,
            renewal_mode=SubscriptionRenewalMode.MANUAL,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        db.add_all([owner_subscription, other_subscription])
        db.commit()
        owner_subscription_id = owner_subscription.id
        other_subscription_id = other_subscription.id

    response = client.get(
        f"/api/account/subscriptions/{owner_subscription_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    foreign_response = client.get(
        f"/api/account/subscriptions/{other_subscription_id}",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["subscription_id"] == str(owner_subscription_id)
    assert response.json()["cancellation"]["cancel_requested_at"] is not None
    assert response.json()["cancellation"]["canceled_at"] is None
    assert foreign_response.status_code == 404
    assert foreign_response.json()["detail"]["code"] == "subscription_not_found"


def test_required_document_acceptance_hash_controls_terms_and_personal_consent_gate() -> None:
    from app.domains.legal.service import expected_acceptance_text_hash

    with SessionLocal() as db:
        legal_entity = create_legal_entity(db, region="ru")
        offer_document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="offer",
            version="2026-08-offer-v1",
            title="Публичная оферта",
        )
        personal_document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="pd_consent",
            version="2026-08-pd-v1",
            title="Согласие на обработку персональных данных",
        )
        offer_document_id = offer_document.id
        personal_document_id = personal_document.id
        offer_hash = expected_acceptance_text_hash(offer_document)
        personal_hash = expected_acceptance_text_hash(personal_document)

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "legal-hash-gate@example.com",
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    assert checkout_response.status_code == 409
    assert {document["document_version_id"] for document in checkout_response.json()["detail"]["documents"]} == {
        str(offer_document_id),
        str(personal_document_id),
    }

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "legal-hash-gate@example.com").one()
        offer_document = db.get(DocumentVersion, offer_document_id)
        personal_document = db.get(DocumentVersion, personal_document_id)
        create_document_acceptance_row(
            db,
            document=offer_document,
            user=user,
            acceptance_text_hash="0" * 64,
        )
        create_document_acceptance_row(
            db,
            document=personal_document,
            user=user,
            acceptance_text_hash=personal_hash,
        )

    bad_hash_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    assert bad_hash_response.status_code == 409
    bad_hash_detail = bad_hash_response.json()["detail"]
    assert bad_hash_detail["code"] == "missing_required_documents"
    assert [document["document_version_id"] for document in bad_hash_detail["documents"]] == [str(offer_document_id)]

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "legal-hash-gate@example.com").one()
        offer_document = db.get(DocumentVersion, offer_document_id)
        create_document_acceptance_row(
            db,
            document=offer_document,
            user=user,
            acceptance_text_hash=offer_hash,
        )

    accepted_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    assert accepted_response.status_code == 200, accepted_response.text
    with SessionLocal() as db:
        acceptances = db.query(DocumentAcceptance).all()
    assert len(acceptances) == 3
    assert any(acceptance.acceptance_text_hash == "0" * 64 for acceptance in acceptances)


def test_required_document_acceptance_scope_and_time_filters_still_apply() -> None:
    from app.domains.legal.service import expected_acceptance_text_hash

    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        legal_entity = create_legal_entity(db, region="ru")
        stale_document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="offer",
            version="2026-08-offer-v0",
            title="Публичная оферта",
        )
        stale_document.is_active = False
        active_document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="offer",
            version="2026-08-offer-v1",
            title="Публичная оферта",
        )
        active_document_id = active_document.id
        stale_document_id = stale_document.id
        active_hash = expected_acceptance_text_hash(active_document)
        stale_hash = expected_acceptance_text_hash(stale_document)
        db.commit()

    owner_response = client.post(
        "/api/auth/register",
        json={
            "email": "legal-scope-owner@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    other_response = client.post(
        "/api/auth/register",
        json={
            "email": "legal-scope-other@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert other_response.status_code == 200
    token = owner_response.json()["token"]

    with SessionLocal() as db:
        owner = db.query(User).filter(User.email == "legal-scope-owner@example.com").one()
        other_user = db.query(User).filter(User.email == "legal-scope-other@example.com").one()
        active_document = db.get(DocumentVersion, active_document_id)
        stale_document = db.get(DocumentVersion, stale_document_id)
        create_document_acceptance_row(
            db,
            document=active_document,
            user=other_user,
            acceptance_text_hash=active_hash,
        )
        create_document_acceptance_row(
            db,
            document=active_document,
            user=owner,
            tenant_id="other-tenant",
            acceptance_text_hash=active_hash,
        )
        create_document_acceptance_row(
            db,
            document=active_document,
            user=owner,
            region="eu",
            acceptance_text_hash=active_hash,
        )
        create_document_acceptance_row(
            db,
            document=active_document,
            user=owner,
            accepted_at=now + timedelta(days=1),
            acceptance_text_hash=active_hash,
        )
        create_document_acceptance_row(
            db,
            document=stale_document,
            user=owner,
            acceptance_text_hash=stale_hash,
        )

    checkout_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": False,
        },
    )
    assert checkout_response.status_code == 409
    detail = checkout_response.json()["detail"]
    assert detail["code"] == "missing_required_documents"
    assert [document["document_version_id"] for document in detail["documents"]] == [str(active_document_id)]


def test_create_document_acceptance_rejects_substituted_hash_in_endpoint_and_service() -> None:
    from app.domains.legal.service import (
        LegalAcceptanceError,
        create_document_acceptance,
    )

    with SessionLocal() as db:
        legal_entity = create_legal_entity(db, region="ru")
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="offer",
            version="2026-08-offer-v1",
            title="Публичная оферта",
        )
        document_id = document.id
        with pytest.raises(LegalAcceptanceError) as error:
            create_document_acceptance(
                db,
                document=document,
                acceptance_text_hash="f" * 64,
            )
        assert error.value.code == "invalid_acceptance_text_hash"
        assert db.query(DocumentAcceptance).count() == 0

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "legal-service-hash@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]

    response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "document_version_id": str(document_id),
            "acceptance_text_hash": "f" * 64,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_acceptance_text_hash"


def test_automatic_checkout_keeps_recurring_consent_missing_when_hash_is_wrong() -> None:
    from app.domains.legal.service import expected_acceptance_text_hash

    with SessionLocal() as db:
        plan = db.query(Plan).filter(Plan.code == "document-summary-pro").one()
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
        legal_entity = create_legal_entity(db)
        document = create_document_version(
            db,
            legal_entity=legal_entity,
            doc_type="recurring_consent",
            version="2026-08-recurring-v1",
            title="Согласие на рекуррентные платежи",
        )
        document_id = document.id
        document_hash = expected_acceptance_text_hash(document)

    register_response = client.post(
        "/api/auth/register",
        json={
            "email": "recurring-hash-gate@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    token = register_response.json()["token"]

    with SessionLocal() as db:
        user = db.query(User).filter(User.email == "recurring-hash-gate@example.com").one()
        document = db.get(DocumentVersion, document_id)
        assert document is not None
        create_document_acceptance_row(
            db,
            document=document,
            user=user,
            acceptance_text_hash="1" * 64,
            entrypoint_value="document-summary",
        )

    bad_hash_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
        },
    )
    assert bad_hash_response.status_code == 409
    bad_hash_detail = bad_hash_response.json()["detail"]
    assert bad_hash_detail["code"] == "missing_required_documents"
    assert [document["document_version_id"] for document in bad_hash_detail["documents"]] == [str(document_id)]

    acceptance_id = accept_document_for_token(
        token,
        document=document,
        entrypoint_value="document-summary",
    )
    with SessionLocal() as db:
        correct_acceptance = db.get(DocumentAcceptance, uuid.UUID(acceptance_id))
    assert correct_acceptance.acceptance_text_hash == document_hash

    accepted_response = client.post(
        "/api/auth/checkout-intent",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
            "auto_renew": True,
            "recurring_consent_acceptance_id": acceptance_id,
        },
    )
    assert accepted_response.status_code == 200, accepted_response.text


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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
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
            "plan_id": plan_id_for_code("document-summary-pro"),
            "entrypoint_type": "product",
            "entrypoint_value": "document-summary",
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
    assert ru_documents_response.json()["documents"][0]["document_version_id"] == str(ru_document_id)
    assert eu_documents_response.json()["documents"][0]["document_version_id"] == str(eu_document_id)
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
            "acceptance_text_hash": ru_documents_response.json()["documents"][0]["acceptance_text_hash"],
        },
    )
    eu_accept_response = client.post(
        "/api/legal/acceptances",
        headers={"Authorization": f"Bearer {eu_token}"},
        json={
            "document_version_id": str(eu_document_id),
            "acceptance_text_hash": eu_documents_response.json()["documents"][0]["acceptance_text_hash"],
        },
    )

    assert ru_accept_response.status_code == 200
    assert eu_accept_response.status_code == 200

    with SessionLocal() as db:
        acceptances = db.query(DocumentAcceptance).all()

    assert len(acceptances) == 2
    assert {(acceptance.region, acceptance.document_version_id) for acceptance in acceptances} == {
        ("ru", ru_document_id),
        ("eu", eu_document_id),
    }


def test_cloudpayments_webhook_rejects_invalid_signature_when_secret_is_set() -> None:
    require_signed_cloudpayments_webhooks_for_test()
    app.dependency_overrides.clear()

    from app.settings import settings  # noqa: E402

    with override_settings(settings, cloudpayments_api_secret="test-secret"):
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

    assert event.status is PaymentWebhookEventStatus.FAILED
    assert event.error_message == "invalid_cloudpayments_signature"
    assert event.processed_at


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

    responses = [client.post(f"/api/cloudpayments/{endpoint}", json=payload) for endpoint, payload in scenarios]

    assert [response.status_code for response in responses] == [400, 400, 400]
    assert [response.json()["detail"] for response in responses] == [
        "invalid_cloudpayments_signature",
        "invalid_cloudpayments_signature",
        "invalid_cloudpayments_signature",
    ]
    with SessionLocal() as db:
        events = db.query(PaymentWebhookEvent).order_by(PaymentWebhookEvent.received_at).all()

    assert [event.endpoint for event in events] == ["confirm", "cancel", "recurrent"]
    assert [event.status for event in events] == [
        PaymentWebhookEventStatus.FAILED,
        PaymentWebhookEventStatus.FAILED,
        PaymentWebhookEventStatus.FAILED,
    ]
    assert {event.error_code for event in events} == {"invalid_cloudpayments_signature"}


def test_cloudpayments_webhook_rejects_non_ascii_signature_without_500() -> None:
    secret = "test-secret"
    from app.settings import settings  # noqa: E402

    object.__setattr__(settings, "cloudpayments_enabled", True)
    object.__setattr__(settings, "cloudpayments_api_secret", secret)
    payload = b'{"InvoiceId":"invoice-non-ascii","Amount":"1490.00","Currency":"RUB"}'
    valid_signature = base64.b64encode(hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()).decode(
        "ascii"
    )

    assert (
        verify_cloudpayments_signature(
            payload,
            {"Content-HMAC": f"{valid_signature}å"},
        )
        is False
    )

    object.__setattr__(settings, "cloudpayments_enabled", False)
    object.__setattr__(settings, "cloudpayments_api_secret", "")
