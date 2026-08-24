from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import Order, OrderItem


def get_order_by_id(db: Session, order_id: uuid.UUID, *, for_update: bool = False) -> Order | None:
    query = db.query(Order).filter(Order.id == order_id)
    return (query.with_for_update() if for_update else query).first()


def get_order_item_with_plan(db: Session, order_id: uuid.UUID) -> OrderItem | None:
    return (
        db.query(OrderItem)
        .filter(OrderItem.order_id == order_id, OrderItem.plan_id.is_not(None))
        .first()
    )
