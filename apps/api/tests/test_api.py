from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite+pysqlite:///:memory:"
os.environ["CLOUDPAYMENTS_API_SECRET"] = ""
os.environ["SKIP_LEGAL_SEED"] = "true"

api_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(api_root))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import (  # noqa: E402
    AuthSession,
    Bundle,
    BundleProduct,
    DocumentAcceptance,
    DocumentVersion,
    LegalEntity,
    Order,
    OrderItem,
    Payment,
    PaymentWebhookEvent,
    Plan,
    ProductAccessState,
    Product,
    Refund,
    User,
)
from app.legal_seed import RU_DOCUMENT_VERSIONS, seed_legal_documents  # noqa: E402


client = TestClient(app)


def setup_function() -> None:
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
        price_amount_minor=990,
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
        price_amount_minor=990,
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
        price_amount_minor=1980,
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
        price_amount_minor=1980,
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
    assert order.amount_minor == 1980
    assert item.item_type == "bundle_plan"
    assert item.plan_id == bundle_plan_id
    assert item.bundle_id == bundle_id
    assert item.product_id is None
    assert item.product_code_snapshot is None
    assert item.plan_code_snapshot == "core-tools-bundle-pro-ru"
    assert item.amount_minor == 1980
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
    assert order.amount_minor == 1980
    assert item.item_type == "all_access_plan"
    assert item.plan_id == all_access_plan_id
    assert item.bundle_id is None
    assert item.product_id is None
    assert item.product_code_snapshot is None
    assert item.plan_code_snapshot == "all-access-pro-ru"
    assert item.amount_minor == 1980
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
            "Amount": "9.90",
            "Currency": "RUB",
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
    assert payment.amount_minor == 990
    assert "CardFirstSix" not in payment.raw_summary


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
            "Amount": "9.90",
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
            "Amount": "9.90",
            "Currency": "RUB",
        },
    )
    fail_response = client.post(
        "/api/cloudpayments/fail",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-late-fail-declined",
            "AccountId": "late-fail-user@example.com",
            "Amount": "9.90",
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
        "Amount": "9.90",
        "Currency": "RUB",
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
            "Amount": "9.90",
            "Currency": "RUB",
        },
    )

    refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-refund-1",
            "RefundId": "refund-1",
            "Amount": "9.90",
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
    assert status_payload["payment"]["refunded_amount_minor"] == 990

    with SessionLocal() as db:
        order = db.query(Order).one()
        payment = db.query(Payment).one()
        refund = db.query(Refund).one()
        events = db.query(PaymentWebhookEvent).all()

    assert order.status == "refunded"
    assert payment.status == "refunded"
    assert payment.refunded_amount_minor == 990
    assert refund.status == "succeeded"
    assert refund.provider_refund_id == "refund-1"
    assert len(events) == 2


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
            "Amount": "9.90",
            "Currency": "RUB",
        },
    )

    first_refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-multi-refund-1",
            "RefundId": "refund-part-1",
            "Amount": "4.00",
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
    assert partial_status_payload["payment"]["amount_minor"] == 990
    assert partial_status_payload["payment"]["refunded_amount_minor"] == 400

    second_refund_response = client.post(
        "/api/cloudpayments/refund",
        json={
            "InvoiceId": invoice_id,
            "TransactionId": "tx-multi-refund-1",
            "RefundId": "refund-part-2",
            "Amount": "5.90",
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
    assert payment.refunded_amount_minor == 990
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
            "Amount": "9.90",
            "Currency": "RUB",
        },
    )
    refund_payload = {
        "InvoiceId": invoice_id,
        "TransactionId": "tx-duplicate-refund-1",
        "RefundId": "refund-duplicate-1",
        "Amount": "4.00",
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
    assert payment.refunded_amount_minor == 400
    assert len(refunds) == 1
    assert [event.status for event in events] == ["processed", "processed", "processed"]


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
        headers={"Content-HMAC": "demo-signature"},
        json={
            "InvoiceId": "invoice-1",
            "TransactionId": "tx-1",
            "AccountId": "user@example.com",
            "Amount": "9.90",
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
    assert event.amount_minor == 990
    assert str(event.amount) == "9.90"
    assert event.currency == "RUB"
    assert event.raw_payload["CardFirstSix"] == "[redacted]"
    assert event.headers["content-hmac"] == "[redacted]"
    assert event.status == "ignored"
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
