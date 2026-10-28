"""Bulk receipt bookkeeping inside the caller's fenced apply transaction."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models import ExternalBillingWebhookDelivery as Delivery, WebhookDeliveryState


def mark_processed(
    db: Session, *, correlation_schema: str, work_id: UUID, generation: int, started_at: datetime, now: datetime
) -> None:
    db.execute(
        update(Delivery)
        .where(
            Delivery.processing_state == WebhookDeliveryState.PENDING,
            Delivery.correlation_schema_version == correlation_schema,
            Delivery.correlation_document["work_item_id"].as_string() == str(work_id),
            Delivery.correlation_document["enqueue_generation"].as_integer() <= generation,
        )
        .values(processing_state=WebhookDeliveryState.PROCESSED, processing_started_at=started_at, processed_at=now)
        .execution_options(synchronize_session=False)
    )
