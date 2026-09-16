from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domains.billing.errors import AmbiguousCatalogProductOfferError
from app.infrastructure.queries.products import list_sellable_product_offers
from app.models import BillingPeriod, SubscriptionRenewalMode


@dataclass(frozen=True)
class CatalogOfferResult:
    product_id: uuid.UUID
    product_code: str
    product_name: str
    product_description: str | None
    plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    price_amount_minor: int
    currency: str
    billing_period: BillingPeriod
    renewal_mode: SubscriptionRenewalMode
    trial_days: int


def list_catalog_offers(
    db: Session,
    *,
    tenant_id: str,
    region: str,
) -> list[CatalogOfferResult]:
    offers = list_sellable_product_offers(
        db,
        tenant_id=tenant_id,
        region=region,
        now=utc_now(),
    )
    seen_product_ids: set[uuid.UUID] = set()
    results: list[CatalogOfferResult] = []
    for product, plan in offers:
        if product.id in seen_product_ids:
            raise AmbiguousCatalogProductOfferError(product_code=product.code)
        seen_product_ids.add(product.id)
        results.append(
            CatalogOfferResult(
                product_id=product.id,
                product_code=product.code,
                product_name=product.name,
                product_description=product.description,
                plan_id=plan.id,
                plan_code=plan.code,
                plan_name=plan.name,
                price_amount_minor=plan.price_amount_minor,
                currency=plan.currency,
                billing_period=plan.billing_period,
                renewal_mode=plan.renewal_mode,
                trial_days=plan.trial_days,
            )
        )
    return results
