from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Bundle, Product


def get_product_by_code(db: Session, *, tenant_id: str, code: str) -> Product | None:
    return db.query(Product).filter(Product.tenant_id == tenant_id, Product.code == code).first()


def get_product_by_id(db: Session, product_id: uuid.UUID) -> Product | None:
    return db.get(Product, product_id)


def get_bundle_by_code(db: Session, *, tenant_id: str, code: str) -> Bundle | None:
    return db.query(Bundle).filter(Bundle.tenant_id == tenant_id, Bundle.code == code).first()


def get_bundle_by_id(db: Session, bundle_id: uuid.UUID) -> Bundle | None:
    return db.get(Bundle, bundle_id)
