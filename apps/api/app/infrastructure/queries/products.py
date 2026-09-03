from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Bundle, Plan, PlanStatus, Product, ProductStatus, SubscriptionScopeType


def get_product_by_code(db: Session, *, tenant_id: str, code: str) -> Product | None:
    return db.query(Product).filter(Product.tenant_id == tenant_id, Product.code == code).first()


def get_product_by_id(db: Session, product_id: uuid.UUID) -> Product | None:
    return db.get(Product, product_id)


def list_sellable_product_offers(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    now: datetime,
) -> list[tuple[Product, Plan]]:
    return (
        db.query(Product, Plan)
        .join(Plan, Plan.product_id == Product.id)
        .filter(
            Product.tenant_id == tenant_id,
            Product.status == ProductStatus.ACTIVE,
            Plan.tenant_id == tenant_id,
            Plan.region == region,
            Plan.status == PlanStatus.ACTIVE,
            Plan.scope_type == SubscriptionScopeType.PRODUCT,
            Plan.valid_from <= now,
            (Plan.valid_to.is_(None) | (Plan.valid_to > now)),
        )
        .order_by(Product.code.asc(), Plan.code.asc())
        .all()
    )


def get_bundle_by_code(db: Session, *, tenant_id: str, code: str) -> Bundle | None:
    return db.query(Bundle).filter(Bundle.tenant_id == tenant_id, Bundle.code == code).first()


def get_bundle_by_id(db: Session, bundle_id: uuid.UUID) -> Bundle | None:
    return db.get(Bundle, bundle_id)
