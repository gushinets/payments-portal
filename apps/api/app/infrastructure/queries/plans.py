from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Plan


def get_plan_by_id(db: Session, plan_id: uuid.UUID, *, for_update: bool = False) -> Plan | None:
    query = db.query(Plan).filter(Plan.id == plan_id)
    return (query.with_for_update() if for_update else query).first()


def list_plans_by_ids(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    plan_ids: set[uuid.UUID],
) -> list[Plan]:
    if not plan_ids:
        return []
    return (
        db.query(Plan)
        .filter(
            Plan.tenant_id == tenant_id,
            Plan.region == region,
            Plan.id.in_(plan_ids),
        )
        .all()
    )
