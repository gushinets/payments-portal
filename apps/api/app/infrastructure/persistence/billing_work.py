"""Atomic recurring-work upsert mechanics; caller owns the transaction."""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import case, func, or_, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.models import BillingWorkItem

RECURRING_INDEX = "work_kind IN ('subscription_reconciliation', 'subscription_trust_expiry', 'billing_enrollment_sweep', 'customer_inventory', 'external_create_deadline')"


def coalesce(
    db: Session,
    *,
    kind: str,
    key: str,
    scope_kind: str,
    reference: str,
    due: datetime,
    priority: int,
    payload: dict,
    hint: bool = False,
    replace_deadline: bool = False,
) -> None:
    insert = pg_insert if db.get_bind().dialect.name == "postgresql" else sqlite_insert
    statement = insert(BillingWorkItem).values(
        work_item_id=uuid4(),
        work_kind=kind,
        scope_kind=scope_kind,
        scope_reference=reference,
        coalescing_key=key,
        payload_schema_version="billing-work:v1",
        payload_document=payload,
        priority=priority,
        next_attempt_at=due,
        work_state="pending",
        enqueue_generation=0,
        attempt_count=0,
    )
    table = BillingWorkItem.__table__.c
    updates = {
        "updated_at": func.now(),
        "work_state": case((table.work_state == "completed", "pending"), else_=table.work_state),
        "next_attempt_at": due
        if replace_deadline
        else case(
            (or_(table.work_state == "completed", table.next_attempt_at > due), due), else_=table.next_attempt_at
        ),
        "enqueue_generation": table.enqueue_generation + 1,
        "payload_document": payload,
        "priority": priority,
    }
    statement = statement.on_conflict_do_update(
        index_elements=["work_kind", "coalescing_key"],
        index_where=text(RECURRING_INDEX),
        set_=updates,
        where=(table.payload_document != payload)
        if replace_deadline
        else None
        if hint
        else table.work_state == "completed",
    )
    db.execute(statement)
