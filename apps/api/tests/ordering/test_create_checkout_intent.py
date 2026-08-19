from __future__ import annotations

import hashlib
from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.identity.session import utc_now
from app.main import app
from app.models import AuthSession, EntrypointSession, Plan, Product, Region, User


def test_create_checkout_intent(db_session: Session) -> None:
    # Удалить/переписать - нужен сейчас для тестов
    token = "test-ordering-token"
    user = User(
        tenant_id="anytoolai",
        region="ru",
        email="ordering@example.com",
        email_normalized="ordering@example.com",
        status="active",
        metadata_={},
    )
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
    db_session.add(
        Product(
            tenant_id="anytoolai",
            code="document-summary",
            platform_product_id="document-summary",
            name="Document Summary",
            status="active",
        )
    )
    db_session.add(user)
    db_session.flush()

    product = (
        db_session.query(Product)
        .filter(
            Product.tenant_id == "anytoolai",
            Product.code == "document-summary",
        )
        .one()
    )
    db_session.add(
        Plan(
            tenant_id="anytoolai",
            region="ru",
            code="document-summary-pro",
            name="Document Summary Pro",
            scope_type="product",
            product_id=product.id,
            price_amount_minor=99000,
            currency="RUB",
            billing_period="month",
            renewal_mode="manual",
            trial_days=7,
            status="active",
        )
    )
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

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/ordering/checkout/intent",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product": "document-summary",
                    "plan_code": "document-summary-pro",
                    "auto_renew": False,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200


def test_create_checkout_intent_normalizes_all_access_entrypoint_value(db_session: Session) -> None:
    token = "test-ordering-all-access-token"
    user = User(
        tenant_id="anytoolai",
        region="ru",
        email="ordering-all-access@example.com",
        email_normalized="ordering-all-access@example.com",
        status="active",
        metadata_={},
    )
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
    db_session.add(user)
    db_session.add(
        Plan(
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
    )
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

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/v1/ordering/checkout/intent",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "product": "all-access",
                    "plan_code": "all-access-pro-ru",
                    "entrypoint_type": "catalog",
                    "auto_renew": True,
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["checkout"]["action"]["merchant_order_id"].startswith(
        "all-access-"
    )

    entrypoint_session = db_session.query(EntrypointSession).one()
    assert entrypoint_session.entrypoint_value == "all-access"
