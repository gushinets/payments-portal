from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.time import utc_now
from app.domains.identity.session import DEFAULT_REGION, DEFAULT_TENANT_ID
from app.infrastructure.queries.products import list_sellable_product_offers
from app.models import BillingPeriod, SubscriptionRenewalMode

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


class CatalogPlanResponse(BaseModel):
    plan_id: uuid.UUID
    code: str
    name: str
    price_amount_minor: int
    currency: str
    billing_period: BillingPeriod
    renewal_mode: SubscriptionRenewalMode
    trial_days: int


class CatalogProductResponse(BaseModel):
    product_id: uuid.UUID
    code: str
    name: str
    description: str | None
    plan: CatalogPlanResponse


class CatalogProductsResponse(BaseModel):
    products: list[CatalogProductResponse]


@router.get("/products", response_model=CatalogProductsResponse)
def list_catalog_products(db: Annotated[Session, Depends(get_db)]) -> CatalogProductsResponse:
    offers = list_sellable_product_offers(
        db,
        tenant_id=DEFAULT_TENANT_ID,
        region=DEFAULT_REGION,
        now=utc_now(),
    )
    seen_product_ids: set[uuid.UUID] = set()
    for product, _plan in offers:
        if product.id in seen_product_ids:
            raise HTTPException(
                status_code=500,
                detail={
                    "code": "ambiguous_catalog_product_offer",
                    "product_code": product.code,
                },
            )
        seen_product_ids.add(product.id)

    return CatalogProductsResponse(
        products=[
            CatalogProductResponse(
                product_id=product.id,
                code=product.code,
                name=product.name,
                description=product.description,
                plan=CatalogPlanResponse(
                    plan_id=plan.id,
                    code=plan.code,
                    name=plan.name,
                    price_amount_minor=plan.price_amount_minor,
                    currency=plan.currency,
                    billing_period=plan.billing_period,
                    renewal_mode=plan.renewal_mode,
                    trial_days=plan.trial_days,
                ),
            )
            for product, plan in offers
        ]
    )
