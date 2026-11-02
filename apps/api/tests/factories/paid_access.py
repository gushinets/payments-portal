"""Explicit simulated paid projection factories; no current terms fallback."""

from app.domains.billing.paid_contracts import EffectiveState, PaidGrant


def grant_document(product: str) -> dict:
    return EffectiveState(grants=(PaidGrant(product_id=product),)).model_dump(mode="json")
