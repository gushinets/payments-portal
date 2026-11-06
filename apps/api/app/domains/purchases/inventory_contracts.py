"""One attempt's scoped inventory conclusions and original local versions."""

from dataclasses import dataclass
from uuid import UUID

from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.discovery import ProductDiscovery
from app.domains.billing.reconciliation_contracts import ReconciliationResult, SubscriptionProof
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete, PurchaseRefused


class InventoryStale(PurchaseInventoryIncomplete):
    """Local versions changed during this attempt; repeat with a fresh subject."""


@dataclass(frozen=True)
class InventoryCandidateProof:
    purchase: Purchase
    provider_id: str | None
    proof: SubscriptionProof | None


@dataclass(frozen=True)
class InventoryResult:
    customer: CustomerOpen
    purchases: tuple[Purchase, ...]
    conflicts: tuple[UUID, ...]
    pending: tuple[UUID, ...]
    complete: bool
    products: tuple[ProductDiscovery, ...] = ()
    sources: tuple[ReconciliationResult, ...] = ()
    discovery_ids: tuple[UUID, ...] = ()

    def require_clear(self, purchase: Purchase, *, original: bool = False) -> None:
        if purchase.id in self.conflicts:
            raise PurchaseRefused("purchase_existing_subscription_review", 409)
        relevant = {
            item.id
            for item in self.purchases
            if item.accepted.selection.tariff_id == purchase.accepted.selection.tariff_id
        }
        if not self.complete or any(
            (identity != purchase.id or not original) and identity in relevant for identity in self.pending
        ):
            raise PurchaseInventoryIncomplete()
