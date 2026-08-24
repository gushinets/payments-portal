from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Plan


def get_plan_by_id(db: Session, plan_id: uuid.UUID, *, for_update: bool = False) -> Plan | None:
    query = db.query(Plan).filter(Plan.id == plan_id)
    return (query.with_for_update() if for_update else query).first()
