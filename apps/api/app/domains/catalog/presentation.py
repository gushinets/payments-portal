"""Shared catalog and purchase HTTP models and exact money projection."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, Field, field_serializer, model_validator

from app.domains.catalog.commercial_offer import canonical_document
from app.domains.catalog.mapping_evidence import MappingEvidenceMode, PublicationState
from app.domains.catalog.preview import CatalogUnavailable, ProductPreview
from app.domains.catalog.publication import StoredMapping


ExactAmount = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")]
ExactPositiveInteger = Annotated[str, Field(pattern=r"^[1-9][0-9]*$")]


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


class CatalogAllowance(BaseModel):
    metric_key: str
    unit: str
    quantity: Annotated[int, Field(strict=True, gt=0)]

    @field_serializer("quantity")
    def exact_quantity(self, quantity: int) -> ExactPositiveInteger:
        # Preserve an approved integer beyond JavaScript's safe Number range.
        return str(quantity)


class CatalogTermSummary(BaseModel):
    prepaid: bool
    full_funding_required: bool
    tax_treatment: Literal["included", "not_applicable"]
    discounts: Literal["none"]
    proration: Literal["none"]
    connection_charge_basis: Literal["per_service_unit", "once"]


class CatalogOffer(BaseModel):
    offer_id: UUID
    revision_id: UUID
    revision_number: Annotated[int, Field(strict=True, gt=0)]
    evidence_mode: MappingEvidenceMode
    publication_state: PublicationState
    money: CatalogMoney
    period: CatalogPeriod
    allowance: CatalogAllowance
    terms: CatalogTermSummary


class CatalogProductResponse(BaseModel):
    product_id: str
    evidence_mode: MappingEvidenceMode
    availability: Literal["APPROVED_UNVERIFIED_NOW", "SIMULATED_PREVIEW", "UNAVAILABLE_AMBIGUOUS_OFFERS"]
    offer: CatalogOffer | None


class CatalogProductsResponse(BaseModel):
    products: list[CatalogProductResponse]


def present_offer(stored: StoredMapping) -> CatalogOffer:
    material = stored.document.material
    money, period, policy = material.terms.money, material.terms.period, material.terms.policy
    # Fixed-point formatting cannot round: validate the stored fractional scale
    # before padding. No binary float or Decimal context arithmetic is involved.
    amounts = [format(value, "f") for value in (money.recurring_amount, money.connection_amount)]
    for index, amount in enumerate(amounts):
        whole, _, fraction = amount.partition(".")
        if len(fraction) > money.decimal_places:
            if any(digit != "0" for digit in fraction[money.decimal_places :]):
                raise CatalogUnavailable()
            fraction = fraction[: money.decimal_places]
        amounts[index] = whole + ("." + fraction.ljust(money.decimal_places, "0") if money.decimal_places else "")
    return CatalogOffer(
        offer_id=uuid5(
            NAMESPACE_URL,
            "portal-catalog-offer:v1:"
            + canonical_document([material.scope.external_billing_account_id, material.billing_offer_id]),
        ),
        revision_id=stored.mapping_revision_id,
        revision_number=stored.revision_number,
        evidence_mode=stored.document.evidence_mode,
        publication_state=stored.document.publication_state,
        money=CatalogMoney(
            recurring_amount=amounts[0],
            connection_amount=amounts[1],
            currency=money.currency,
            decimal_places=money.decimal_places,
        ),
        period=CatalogPeriod(unit=period.unit, length=period.length, anchor=period.anchor),
        allowance=CatalogAllowance(
            metric_key=material.technical.metric_key,
            unit=material.technical.unit,
            quantity=material.technical.allowance,
        ),
        terms=CatalogTermSummary(
            prepaid=policy.prepaid,
            full_funding_required=policy.full_funding_required,
            tax_treatment=policy.tax_treatment,
            discounts=policy.discounts,
            proration=policy.proration,
            connection_charge_basis=policy.connection_charge_basis,
        ),
    )


def present_product(product: ProductPreview) -> CatalogProductResponse:
    evidence_mode = (
        MappingEvidenceMode.SIMULATED
        if any(offer.document.evidence_mode == MappingEvidenceMode.SIMULATED for offer in product.offers)
        else MappingEvidenceMode.GENUINE
    )
    if len(product.offers) != 1:
        return CatalogProductResponse(
            product_id=product.product_id,
            evidence_mode=evidence_mode,
            availability="UNAVAILABLE_AMBIGUOUS_OFFERS",
            offer=None,
        )
    offer = present_offer(product.offers[0])
    return CatalogProductResponse(
        product_id=product.product_id,
        evidence_mode=evidence_mode,
        availability=(
            "SIMULATED_PREVIEW" if offer.evidence_mode == MappingEvidenceMode.SIMULATED else "APPROVED_UNVERIFIED_NOW"
        ),
        offer=offer,
    )
