from __future__ import annotations

from uuid import UUID

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.domains.identity.session import utc_now
from app.models import Bundle, Plan, Product


def get_active_plan_by_code(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    plan_code: str,
) -> Plan | None:
    now = utc_now()
    return (
        db.query(Plan)
        .filter(
            Plan.tenant_id == tenant_id,
            Plan.region == region,
            Plan.code == plan_code,
            Plan.status == "active",
            Plan.valid_from <= now,
            or_(Plan.valid_to.is_(None), Plan.valid_to > now),
        )
        .order_by(Plan.valid_from.desc(), Plan.created_at.desc())
        .first()
    )


def get_product_by_id(db: Session, *, product_id: UUID | None) -> Product | None:
    if product_id is None:
        return None
    return db.get(Product, product_id)


def get_bundle_by_id(db: Session, *, bundle_id: UUID | None) -> Bundle | None:
    if bundle_id is None:
        return None
    return db.get(Bundle, bundle_id)
