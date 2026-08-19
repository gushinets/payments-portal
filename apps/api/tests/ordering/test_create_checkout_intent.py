from __future__ import annotations

import hashlib
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import settings
from app.domains.identity.session import utc_now
from app.main import app
from app.models import (
    AuthSession,
    Bundle,
    DocumentAcceptance,
    DocumentVersion,
    EntrypointSession,
    LegalEntity,
    Order,
    OrderItem,
    PaymentProviderAccount,
    Plan,
    Product,
    ProductAccessState,
    Region,
    User,
)
from apps.api.tests.support.settings import override_settings


@contextmanager
def overridden_db(db_session: Session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def create_client() -> TestClient:
    return TestClient(app)


def create_user_with_session(
    db_session: Session,
    *,
    token: str,
    email: str,
) -> User:
    user = User(
        tenant_id="anytoolai",
        region="ru",
        email=email,
        email_normalized=email,
        status="active",
        metadata_={},
    )
    db_session.add(user)
    db_session.flush()
    db_session.add(
        AuthSession(
            tenant_id="anytoolai",
            region="ru",
            user_id=user.id,
            token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
            expires_at=utc_now() + timedelta(days=1),
        )
    )
    db_session.commit()
    return user


def seed_region(db_session: Session) -> None:
    db_session.add(
        Region(
            code="ru",
            name="Russia",
            residency_zone="ru",
            default_currency="RUB",
            default_locale="ru-RU",
            status="active",
        )
    )
    db_session.commit()


def seed_catalog(db_session: Session) -> dict[str, object]:
    seed_region(db_session)

    document_product = Product(
        tenant_id="anytoolai",
        code="document-summary",
        platform_product_id="document-summary",
        name="Document Summary",
        status="active",
    )
    prompt_product = Product(
        tenant_id="anytoolai",
        code="prompt-optimizer",
        platform_product_id="prompt-optimizer",
        name="Prompt Optimizer",
        status="active",
    )
    bundle = Bundle(
        tenant_id="anytoolai",
        region="ru",
        code="core-tools-bundle",
        name="Core Tools Bundle",
        status="active",
    )
    db_session.add_all([document_product, prompt_product, bundle])
    db_session.flush()

    document_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="document-summary-pro",
        name="Document Summary Pro",
        scope_type="product",
        product_id=document_product.id,
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
        name="Core Tools Bundle Pro",
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
        name="All Access Pro",
        scope_type="all_access",
        price_amount_minor=198000,
        currency="RUB",
        billing_period="month",
        renewal_mode="manual",
        trial_days=7,
        status="active",
    )
    db_session.add_all([document_plan, bundle_plan, all_access_plan])
    db_session.commit()

    return {
        "document_product": document_product,
        "bundle": bundle,
        "document_plan": document_plan,
        "bundle_plan": bundle_plan,
        "all_access_plan": all_access_plan,
    }


def seed_provider_account(
    db_session: Session,
    *,
    public_identifier: str | None = "pk_test_provider",
    default_currency: str = "RUB",
    widget_mode: str = "charge",
) -> PaymentProviderAccount:
    account = PaymentProviderAccount(
        tenant_id="anytoolai",
        region="ru",
        provider="cloudpayments",
        public_identifier=public_identifier,
        default_currency=default_currency,
        enabled=True,
        test_mode=True,
        config={"widget_mode": widget_mode, "receipt_mode": "deferred"},
    )
    db_session.add(account)
    db_session.commit()
    return account


def create_legal_entity(db_session: Session) -> LegalEntity:
    entity = LegalEntity(
        tenant_id="anytoolai",
        region="ru",
        name="AnytoolAI RU",
        entity_type="individual_entrepreneur",
        legal_address="Draft legal address",
        support_email="support@example.com",
        status="active",
    )
    db_session.add(entity)
    db_session.commit()
    db_session.refresh(entity)
    return entity


def create_document_version(
    db_session: Session,
    *,
    legal_entity: LegalEntity,
    version: str,
    title: str = "Публичная оферта",
) -> DocumentVersion:
    now = datetime.now(timezone.utc)
    document = DocumentVersion(
        id=uuid.uuid4(),
        tenant_id=legal_entity.tenant_id,
        region=legal_entity.region,
        legal_entity_id=legal_entity.id,
        doc_type="offer",
        version=version,
        title=title,
        url_path=f"/{legal_entity.region}/offer",
        content_hash=f"sha256:{version}",
        published_at=now,
        effective_from=now,
        is_active=True,
        requires_acceptance=True,
    )
    db_session.add(document)
    db_session.commit()
    db_session.refresh(document)
    return document


def post_checkout_intent(client: TestClient, *, token: str, payload: dict) -> object:
    return client.post(
        "/api/v1/ordering/checkout/intent",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )


def test_create_checkout_intent(db_session: Session) -> None:
    seed_catalog(db_session)
    create_user_with_session(
        db_session,
        token="test-ordering-token",
        email="ordering@example.com",
    )

    with overridden_db(db_session):
        with create_client() as client:
            response = post_checkout_intent(
                client,
                token="test-ordering-token",
                payload={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["product_state"]["product_code"] == "document-summary"
    assert payload["product_state"]["plan_code"] == "document-summary-pro"
    assert payload["product_state"]["plan_name"] == "Document Summary Pro"
    assert payload["product_state"]["invoice_id"].startswith("document-summary-")
    assert payload["product_state"]["transaction_id"] is None
    assert payload["product_state"]["status"] == "pending"
    assert payload["product_state"]["starts_at"] is not None
    assert payload["product_state"]["expires_at"] is None
    assert payload["checkout"]["amount_minor"] == 99000
    assert payload["checkout"]["amount"] == 990.0
    assert payload["checkout"]["currency"] == "RUB"
    action = payload["checkout"]["action"]
    assert action["provider"] == "cloudpayments"
    assert action["experience"] == "widget"
    assert action["mode"] == "charge"
    assert action["public_identifier"] == "pk_test_provider"
    assert action["amount_minor"] == 99000
    assert float(action["amount"]) == 990.0
    assert action["currency"] == "RUB"
    assert action["merchant_order_id"] == payload["product_state"]["invoice_id"]
    assert action["provider_invoice_id"] == payload["product_state"]["invoice_id"]
    assert action["account_id"] == "ordering@example.com"
    assert action["description"] == "Document Summary Pro"
    assert action["metadata"] == {
        "product_code": "document-summary",
        "plan_code": "document-summary-pro",
    }

    order = db_session.query(Order).one()
    item = db_session.query(OrderItem).one()
    state = db_session.query(ProductAccessState).one()
    assert order.status == "pending_payment"
    assert order.metadata_["payment_mode"] == "charge"
    assert item.item_type == "product_plan"
    assert state.last_invoice_id == payload["product_state"]["invoice_id"]


def test_create_checkout_intent_rejects_missing_cloudpayments_public_terminal_id(
    db_session: Session,
) -> None:
    seed_catalog(db_session)
    seed_provider_account(db_session, public_identifier=None)
    create_user_with_session(
        db_session,
        token="missing-terminal-token",
        email="missing-terminal@example.com",
    )

    with override_settings(settings, cloudpayments_public_id=""):
        with overridden_db(db_session):
            with create_client() as client:
                response = post_checkout_intent(
                    client,
                    token="missing-terminal-token",
                    payload={
                        "product": "document-summary",
                        "plan_code": "document-summary-pro",
                        "auto_renew": False,
                    },
                )

    assert response.status_code == 409
    assert response.json()["detail"] == "cloudpayments_public_terminal_id_missing"
    assert db_session.query(Order).count() == 0
    assert db_session.query(OrderItem).count() == 0
    assert db_session.query(ProductAccessState).count() == 0


def test_create_checkout_intent_supports_two_stage_cloudpayments_widget_mode(
    db_session: Session,
) -> None:
    seed_catalog(db_session)
    seed_provider_account(db_session, widget_mode="auth")
    create_user_with_session(
        db_session,
        token="auth-mode-token",
        email="auth-mode@example.com",
    )

    with overridden_db(db_session):
        with create_client() as client:
            response = post_checkout_intent(
                client,
                token="auth-mode-token",
                payload={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )

    assert response.status_code == 200
    assert response.json()["checkout"]["action"]["mode"] == "auth"
    order = db_session.query(Order).one()
    assert order.metadata_["payment_mode"] == "auth"
    assert db_session.query(OrderItem).count() == 1
    assert db_session.query(ProductAccessState).count() == 1


def test_create_checkout_intent_rejects_plan_provider_currency_mismatch(
    db_session: Session,
) -> None:
    seed_catalog(db_session)
    seed_provider_account(db_session, default_currency="RUB")
    create_user_with_session(
        db_session,
        token="currency-mismatch-token",
        email="currency-mismatch@example.com",
    )
    plan = db_session.query(Plan).filter(Plan.code == "document-summary-pro").one()
    plan.currency = "EUR"
    db_session.commit()

    with overridden_db(db_session):
        with create_client() as client:
            response = post_checkout_intent(
                client,
                token="currency-mismatch-token",
                payload={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )

    assert response.status_code == 409
    assert response.json()["detail"] == "provider_currency_mismatch"
    assert db_session.query(Order).count() == 0
    assert db_session.query(OrderItem).count() == 0
    assert db_session.query(ProductAccessState).count() == 0


def test_create_checkout_intent_snapshots_bundle_catalog_plan(db_session: Session) -> None:
    catalog = seed_catalog(db_session)
    create_user_with_session(
        db_session,
        token="bundle-token",
        email="bundle-user@example.com",
    )

    with overridden_db(db_session):
        with create_client() as client:
            response = post_checkout_intent(
                client,
                token="bundle-token",
                payload={
                    "product": "core-tools-bundle",
                    "plan_code": "core-tools-bundle-pro-ru",
                    "entrypoint_type": "bundle",
                    "auto_renew": True,
                },
            )

    assert response.status_code == 200
    invoice_id = response.json()["product_state"]["invoice_id"]
    assert invoice_id.startswith("core-tools-bundle-")

    order = db_session.query(Order).one()
    item = db_session.query(OrderItem).one()
    assert order.plan_id == catalog["bundle_plan"].id
    assert order.amount_minor == 198000
    assert item.item_type == "bundle_plan"
    assert item.plan_id == catalog["bundle_plan"].id
    assert item.bundle_id == catalog["bundle"].id
    assert item.product_id is None
    assert item.product_code_snapshot is None
    assert item.plan_code_snapshot == "core-tools-bundle-pro-ru"
    assert item.amount_minor == 198000
    assert item.trial_days_snapshot == 7


def test_create_checkout_intent_snapshots_all_access_catalog_plan(
    db_session: Session,
) -> None:
    catalog = seed_catalog(db_session)
    create_user_with_session(
        db_session,
        token="all-access-token",
        email="all-access-user@example.com",
    )

    with overridden_db(db_session):
        with create_client() as client:
            response = post_checkout_intent(
                client,
                token="all-access-token",
                payload={
                    "product": "all-access",
                    "plan_code": "all-access-pro-ru",
                    "entrypoint_type": "catalog",
                    "auto_renew": True,
                },
            )

    assert response.status_code == 200
    product_state = response.json()["product_state"]
    assert product_state["invoice_id"].startswith("all-access-")
    assert product_state["plan_code"] == "all-access-pro-ru"
    assert response.json()["checkout"]["action"]["merchant_order_id"].startswith("all-access-")

    order = db_session.query(Order).one()
    item = db_session.query(OrderItem).one()
    entrypoint_session = db_session.query(EntrypointSession).one()
    assert order.plan_id == catalog["all_access_plan"].id
    assert order.amount_minor == 198000
    assert item.item_type == "all_access_plan"
    assert item.plan_id == catalog["all_access_plan"].id
    assert item.bundle_id is None
    assert item.product_id is None
    assert item.product_code_snapshot is None
    assert item.plan_code_snapshot == "all-access-pro-ru"
    assert item.amount_minor == 198000
    assert item.trial_days_snapshot == 7
    assert entrypoint_session.entrypoint_value == "all-access"


def test_create_checkout_intent_rejects_inactive_catalog_plan_without_legacy_fallback(
    db_session: Session,
) -> None:
    seed_catalog(db_session)
    create_user_with_session(
        db_session,
        token="inactive-plan-token",
        email="inactive-plan-user@example.com",
    )
    plan = db_session.query(Plan).filter(Plan.code == "document-summary-pro").one()
    plan.status = "inactive"
    db_session.commit()

    with overridden_db(db_session):
        with create_client() as client:
            response = post_checkout_intent(
                client,
                token="inactive-plan-token",
                payload={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown_product_plan"
    assert db_session.query(Order).count() == 0


def test_create_checkout_intent_rejects_catalog_plan_outside_validity_window(
    db_session: Session,
) -> None:
    seed_catalog(db_session)
    create_user_with_session(
        db_session,
        token="expired-plan-token",
        email="expired-plan-user@example.com",
    )
    plan = db_session.query(Plan).filter(Plan.code == "document-summary-pro").one()
    now = datetime.now(timezone.utc)
    plan.valid_from = now - timedelta(days=30)
    plan.valid_to = now - timedelta(seconds=1)
    db_session.commit()

    with overridden_db(db_session):
        with create_client() as client:
            response = post_checkout_intent(
                client,
                token="expired-plan-token",
                payload={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown_product_plan"
    assert db_session.query(Order).count() == 0


def test_create_checkout_intent_rejects_active_plan_for_inactive_product(
    db_session: Session,
) -> None:
    seed_catalog(db_session)
    create_user_with_session(
        db_session,
        token="inactive-product-token",
        email="inactive-product-user@example.com",
    )
    product = db_session.query(Product).filter(Product.code == "document-summary").one()
    product.status = "inactive"
    db_session.commit()

    with overridden_db(db_session):
        with create_client() as client:
            response = post_checkout_intent(
                client,
                token="inactive-product-token",
                payload={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown_product_plan"
    assert db_session.query(Order).count() == 0


def test_create_checkout_intent_rejects_active_plan_for_inactive_bundle(
    db_session: Session,
) -> None:
    seed_catalog(db_session)
    create_user_with_session(
        db_session,
        token="inactive-bundle-token",
        email="inactive-bundle-user@example.com",
    )
    bundle = db_session.query(Bundle).filter(Bundle.code == "core-tools-bundle").one()
    bundle.status = "inactive"
    db_session.commit()

    with overridden_db(db_session):
        with create_client() as client:
            response = post_checkout_intent(
                client,
                token="inactive-bundle-token",
                payload={
                    "product": "core-tools-bundle",
                    "plan_code": "core-tools-bundle-pro-ru",
                    "entrypoint_type": "bundle",
                    "auto_renew": True,
                },
            )

    assert response.status_code == 400
    assert response.json()["detail"] == "unknown_product_plan"
    assert db_session.query(Order).count() == 0


def test_create_checkout_intent_requires_acceptance_again_when_active_document_version_changes(
    db_session: Session,
) -> None:
    seed_catalog(db_session)
    legal_entity = create_legal_entity(db_session)
    first_document = create_document_version(
        db_session,
        legal_entity=legal_entity,
        version="2026-07-ru-v1",
    )
    create_user_with_session(
        db_session,
        token="legal-token",
        email="legal-user@example.com",
    )

    with overridden_db(db_session):
        with create_client() as client:
            checkout_response = post_checkout_intent(
                client,
                token="legal-token",
                payload={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )

            assert checkout_response.status_code == 409
            detail = checkout_response.json()["detail"]
            missing_document = detail["documents"][0]
            assert detail["code"] == "missing_required_documents"
            assert missing_document["document_version_id"] == str(first_document.id)
            assert missing_document["version"] == "2026-07-ru-v1"
            assert missing_document["acceptance_text"] == "Я принимаю документ «Публичная оферта»."
            assert "offer" not in missing_document["acceptance_text"]
            assert "2026-07-ru-v1" not in missing_document["acceptance_text"]
            assert missing_document["acceptance_text_hash"]

            invalid_accept_response = client.post(
                "/api/legal/acceptances",
                headers={"Authorization": "Bearer legal-token"},
                json={
                    "document_version_id": str(first_document.id),
                    "acceptance_text_hash": "a" * 64,
                    "entrypoint_type": "product",
                    "entrypoint_value": "document-summary",
                },
            )
            assert invalid_accept_response.status_code == 400
            assert invalid_accept_response.json()["detail"] == "invalid_acceptance_text_hash"

            accept_first_response = client.post(
                "/api/legal/acceptances",
                headers={"Authorization": "Bearer legal-token"},
                json={
                    "document_version_id": str(first_document.id),
                    "acceptance_text_hash": missing_document["acceptance_text_hash"],
                    "entrypoint_type": "product",
                    "entrypoint_value": "document-summary",
                },
            )
            assert accept_first_response.status_code == 200

            retry_first_response = post_checkout_intent(
                client,
                token="legal-token",
                payload={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )
            assert retry_first_response.status_code == 200

            first_document.is_active = False
            db_session.commit()
            second_document = create_document_version(
                db_session,
                legal_entity=legal_entity,
                version="2026-07-ru-v2",
            )

            checkout_second_response = post_checkout_intent(
                client,
                token="legal-token",
                payload={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )
            assert checkout_second_response.status_code == 409
            second_detail = checkout_second_response.json()["detail"]
            second_missing_document = second_detail["documents"][0]
            assert second_detail["code"] == "missing_required_documents"
            assert second_missing_document["document_version_id"] == str(second_document.id)
            assert second_missing_document["version"] == "2026-07-ru-v2"

            accept_second_response = client.post(
                "/api/legal/acceptances",
                headers={"Authorization": "Bearer legal-token"},
                json={
                    "document_version_id": str(second_document.id),
                    "acceptance_text_hash": second_missing_document["acceptance_text_hash"],
                    "entrypoint_type": "product",
                    "entrypoint_value": "document-summary",
                },
            )
            assert accept_second_response.status_code == 200

            retry_second_response = post_checkout_intent(
                client,
                token="legal-token",
                payload={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )
            assert retry_second_response.status_code == 200

    acceptances = db_session.query(DocumentAcceptance).order_by(DocumentAcceptance.accepted_at).all()
    assert len(acceptances) == 2
    assert {acceptance.version for acceptance in acceptances} == {
        "2026-07-ru-v1",
        "2026-07-ru-v2",
    }
