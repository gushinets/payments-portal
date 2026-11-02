"""Owned accepted purchases for the cabinet, independent of source availability."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.core.settings import Settings
from app.domains.billing.customers import authenticate
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.service import accepted
from app.infrastructure.queries import purchases as queries
from app.models import PurchaseIntentState


@dataclass(frozen=True)
class AccountPurchase:
    id: UUID
    product_id: str
    state: PurchaseIntentState
    created_at: datetime


def list_account_purchases(
    factory: SessionFactory, configuration: Settings, token: str, *, after: UUID | None, limit: int
) -> tuple[tuple[AccountPurchase, ...], UUID | None]:
    with factory() as db:
        user = authenticate(db, configuration, token)
        rows = queries.account_purchases(db, user.id, after=after, limit=limit + 1)
        items = tuple(
            AccountPurchase(row.purchase_intent_id, accepted(row).selection.product_id, row.state, row.created_at)
            for row in rows[:limit]
        )
        return items, items[-1].id if len(rows) > limit else None
