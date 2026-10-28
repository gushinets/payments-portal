"""Redacted hint contract; receipt never establishes billing facts."""

from dataclasses import dataclass
from uuid import UUID

RECEIPT_SCHEMA = "billing-webhook-receipt:v1"
CORRELATION_SCHEMA = "billing-webhook-work:v1"


@dataclass(frozen=True)
class SubscriptionHint:
    event: str
    subscription_id: str
    agreement_id: str
    customer_id: str | None
    payload_hash: str


@dataclass(frozen=True)
class HintReceipt:
    delivery_id: UUID
    queued: bool
