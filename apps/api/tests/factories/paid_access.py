"""Accepted subscription inputs for allowance/schema checks; no paid writer."""

from dataclasses import dataclass
from uuid import UUID

from app.domains.purchases.contracts import AcceptedPurchase


@dataclass(frozen=True)
class AcceptedSubscription:
    subscription_id: UUID
    user_id: UUID
    accepted: AcceptedPurchase
