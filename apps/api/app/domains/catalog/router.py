"""Safe DB-only catalog HTTP entrypoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import AppEnv, settings
from app.domains.catalog.commercial_offer import CommercialScope
from app.domains.catalog.presentation import (
    CatalogProductResponse,
    CatalogProductsResponse,
    present_product,
)
from app.domains.catalog.presentation import CatalogMoney as CatalogMoney
from app.domains.catalog.presentation import CatalogAllowance as CatalogAllowance
from app.domains.catalog.presentation import present_offer as present_offer
from app.domains.catalog.preview import (
    CatalogProductNotFound,
    CatalogUnavailable,
    get_product_preview,
    list_product_previews,
)


router = APIRouter(prefix="/api/catalog", tags=["catalog"])


def catalog_scope() -> CommercialScope:
    return CommercialScope(settings.instance_tenant_id, settings.instance_region, settings.mapping_account_id)


@router.get("/products", response_model=CatalogProductsResponse)
def list_products(response: Response, db: Annotated[Session, Depends(get_db)]) -> CatalogProductsResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        products = list_product_previews(
            db, scope=catalog_scope(), allow_simulated=settings.app_env != AppEnv.PRODUCTION
        )
        return CatalogProductsResponse(products=[present_product(product) for product in products])
    except CatalogUnavailable:
        raise HTTPException(
            status_code=503, detail={"code": "catalog_unavailable"}, headers={"Cache-Control": "no-store"}
        ) from None


@router.get("/products/{product_id:path}", response_model=CatalogProductResponse)
def product_detail(
    product_id: str, response: Response, db: Annotated[Session, Depends(get_db)]
) -> CatalogProductResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        return present_product(
            get_product_preview(
                db, scope=catalog_scope(), allow_simulated=settings.app_env != AppEnv.PRODUCTION, product_id=product_id
            )
        )
    except CatalogProductNotFound:
        raise HTTPException(
            status_code=404, detail={"code": "catalog_product_not_found"}, headers={"Cache-Control": "no-store"}
        ) from None
    except CatalogUnavailable:
        raise HTTPException(
            status_code=503, detail={"code": "catalog_unavailable"}, headers={"Cache-Control": "no-store"}
        ) from None
