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


def get_order_item(db: Session, order_id: uuid.UUID) -> OrderItem | None:
    return db.query(OrderItem).filter(OrderItem.order_id == order_id).first()


def get_latest_order_for_user_entrypoint(
    db: Session,
    *,
    user_id: uuid.UUID,
    product_id: uuid.UUID | None,
    bundle_id: uuid.UUID | None,
    scope_type: str,
    entrypoint_code: str,
) -> Order | None:
    query = (
        db.query(Order)
        .join(OrderItem, OrderItem.order_id == Order.id)
        .filter(Order.user_id == user_id)
        .order_by(Order.created_at.desc())
    )
    if product_id is not None:
        query = query.filter(
            (OrderItem.product_code_snapshot == entrypoint_code)
            | (OrderItem.product_id == product_id)
        )
    elif bundle_id is not None:
        query = query.filter(
            (OrderItem.product_code_snapshot == entrypoint_code)
            | (OrderItem.bundle_id == bundle_id)
        )
    else:
        query = query.filter(OrderItem.item_type == f"{scope_type}_plan")
    return query.first()
