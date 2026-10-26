"""Source-backed discovery and current selected commercial values. Always no-store."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field, model_validator

from app.composition.catalog import catalog_preview
from app.core.errors import AppError
from app.core.settings import settings
from app.domains.catalog.commercial_offer import CommercialEvidenceMode
from app.domains.catalog.contracts import SourceProvenance
from app.domains.catalog.preview import Availability, CatalogProductNotFound, CatalogUnavailable, ProductPreview


router = APIRouter(prefix="/api/catalog", tags=["catalog"])
ExactAmount = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")]


class CatalogMoney(BaseModel):
    recurring_amount: ExactAmount
    connection_amount: ExactAmount
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]
    units: Literal["major"] = "major"
    decimal_places: Annotated[int, Field(strict=True, ge=0, le=36)]

    @model_validator(mode="after")
    def require_proven_scale(self) -> CatalogMoney:
        for amount in (self.recurring_amount, self.connection_amount):
            if len(amount.partition(".")[2]) != self.decimal_places:
                raise ValueError("catalog money must retain the proven scale")
        return self


class CatalogPeriod(BaseModel):
    unit: Literal["day", "week", "month", "year"]
    length: Annotated[int, Field(strict=True, gt=0)]
    anchor: Literal["calendar_month", "instance_start", "first_instance_start"]


class CatalogOffer(BaseModel):
    revision_id: UUID
    revision_number: Annotated[int, Field(strict=True, gt=0)]
    billing_provenance: CommercialEvidenceMode
    money: CatalogMoney
    period: CatalogPeriod
    commercial_quantity: Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]
    prepaid: bool
    full_funding_required: bool


class CatalogProductResponse(BaseModel):
    product_id: str
    kernel_provenance: SourceProvenance
    availability: Availability
    availability_reason: str | None
    offer: CatalogOffer | None


class CatalogProductsResponse(BaseModel):
    products: list[CatalogProductResponse]


def present_product(product: ProductPreview) -> CatalogProductResponse:
    offer = product.offer
    presented = None
    if offer is not None:
        if product.link is None:
            raise CatalogUnavailable()
        money, period = offer.money, offer.period
        # Normalization already proved exact divisibility at this currency scale.
        presented = CatalogOffer(
            revision_id=product.link.mapping_revision_id,
            revision_number=product.link.revision_number,
            billing_provenance=offer.evidence_mode,
            money=CatalogMoney(
                recurring_amount=format(money.recurring_amount, f".{money.decimal_places}f"),
                connection_amount=format(money.connection_amount, f".{money.decimal_places}f"),
                currency=money.currency,
                decimal_places=money.decimal_places,
            ),
            period=CatalogPeriod(unit=period.unit, length=period.length, anchor=period.anchor),
            commercial_quantity=str(offer.quantity.selected),
            prepaid=offer.prepaid,
            full_funding_required=offer.full_funding_required,
        )
    return CatalogProductResponse(
        product_id=product.product_id,
        kernel_provenance=product.kernel_provenance,
        availability=product.availability,
        availability_reason=product.reason,
        offer=presented,
    )


async def read_preview(request: Request, product_id: str | None = None) -> tuple[ProductPreview, ...]:
    try:
        return await catalog_preview(request.app.state.sources, settings, product_id=product_id)
    except CatalogProductNotFound:
        raise HTTPException(
            status_code=404, detail={"code": "catalog_product_not_found"}, headers={"Cache-Control": "no-store"}
        ) from None
    except AppError as error:
        raise HTTPException(
            status_code=503,
            detail={"code": "catalog_unavailable", "reason": error.code},
            headers={"Cache-Control": "no-store"},
        ) from None


@router.get("/products", response_model=CatalogProductsResponse)
async def list_products(request: Request, response: Response) -> CatalogProductsResponse:
    response.headers["Cache-Control"] = "no-store"
    return CatalogProductsResponse(products=[present_product(item) for item in await read_preview(request)])


@router.get("/products/{product_id:path}", response_model=CatalogProductResponse)
async def product_detail(product_id: str, request: Request, response: Response) -> CatalogProductResponse:
    response.headers["Cache-Control"] = "no-store"
    return present_product((await read_preview(request, product_id))[0])
