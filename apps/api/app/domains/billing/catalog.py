from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.domains.billing.service.catalog import CatalogOfferResult, list_catalog_offers
from app.domains.identity.session import DEFAULT_REGION, DEFAULT_TENANT_ID
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


def present_catalog_offer(result: CatalogOfferResult) -> CatalogProductResponse:
    return CatalogProductResponse(
        product_id=result.product_id,
        code=result.product_code,
        name=result.product_name,
        description=result.product_description,
        plan=CatalogPlanResponse(
            plan_id=result.plan_id,
            code=result.plan_code,
            name=result.plan_name,
            price_amount_minor=result.price_amount_minor,
            currency=result.currency,
            billing_period=result.billing_period,
            renewal_mode=result.renewal_mode,
            trial_days=result.trial_days,
        ),
    )


@router.get("/products", response_model=CatalogProductsResponse)
def list_catalog_products(db: Annotated[Session, Depends(get_db)]) -> CatalogProductsResponse:
    results = list_catalog_offers(
        db,
        tenant_id=DEFAULT_TENANT_ID,
        region=DEFAULT_REGION,
    )
    return CatalogProductsResponse(products=[present_catalog_offer(result) for result in results])
