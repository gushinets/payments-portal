"""Synthetic durable-work shapes; no provider or customer authority."""

from datetime import datetime
from uuid import uuid4

from app.models import BillingWorkItem


def work_factory(
    *,
    kind: str,
    key: str,
    reference: str,
    due: datetime,
    priority: int = 1,
    owner: str | None = None,
    expires: datetime | None = None,
) -> BillingWorkItem:
    return BillingWorkItem(
        work_item_id=uuid4(),
        work_kind=kind,
        scope_kind="subscription",
        scope_reference=reference,
        coalescing_key=key,
        payload_schema_version="billing-work:v1",
        payload_document={},
        priority=priority,
        next_attempt_at=due,
        work_state="pending",
        enqueue_generation=0,
        attempt_count=0,
        lease_owner=owner,
        lease_expires_at=expires,
    )
