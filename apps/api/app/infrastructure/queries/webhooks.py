from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.models import PaymentWebhookEvent


def get_processed_webhook_event(db: Session, event_id: uuid.UUID) -> PaymentWebhookEvent | None:
    return db.query(PaymentWebhookEvent).filter(PaymentWebhookEvent.id == event_id).with_for_update().first()
