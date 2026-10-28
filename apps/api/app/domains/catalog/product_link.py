"""Versioned product association. Live prices and purchase consent live elsewhere."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal
from urllib.parse import quote

from pydantic import AwareDatetime, Field, model_validator

from app.domains.catalog.commercial_offer import (
    CommercialEvidenceMode,
    CommercialMoney,
    CommercialPeriod,
    CommercialQuantity,
    CommercialScope,
    canonical_document,
    commercial_digest,
)
from app.domains.catalog.contracts import SourceProvenance
from app.domains.catalog.mapping_evidence import Digest, ImmutableInput, Nonempty, PositiveInteger


LINK_SCHEMA = "product-link-v2"


class ProductLinkRequest(ImmutableInput):
    product_id: Nonempty
    tariff_id: PositiveInteger
    tariff_service_id: PositiveInteger
    period_id: PositiveInteger
    # One explicit commercial service; never a technical allowance.
    quantity: PositiveInteger = 1

    @property
    def billing_offer_id(self) -> str:
        return "selected-offer:v1:" + ":".join(
            quote(str(value), safe="") for value in (self.tariff_id, self.tariff_service_id, self.period_id)
        )


class ProductLinkDocument(ImmutableInput):
    schema_version: Literal["product-link-v2"] = LINK_SCHEMA
    scope: CommercialScope
    selection: ProductLinkRequest
    kernel_provenance: SourceProvenance
    lbx_evidence_mode: CommercialEvidenceMode
    manifest_version: Digest
    manifest_generated_at: AwareDatetime
    evaluated_at: AwareDatetime
    published_at: AwareDatetime
    publisher_principal: str = Field(pattern=r"^os-euid:[0-9]+$")
    reason: Nonempty
    identity_digest: Digest
    product_revision_number: PositiveInteger | None = None

    def identity_json(self) -> str:
        return canonical_document(
            {
                "schema": LINK_SCHEMA,
                "scope": asdict(self.scope),
                "selection": self.selection.model_dump(mode="json"),
                "kernel_provenance": self.kernel_provenance,
                "lbx_evidence_mode": self.lbx_evidence_mode,
            }
        )

    @model_validator(mode="after")
    def validate_identity(self) -> ProductLinkDocument:
        if commercial_digest(self.identity_json()) != self.identity_digest or self.published_at < self.evaluated_at:
            raise ValueError("invalid product link identity/audit")
        return self


@dataclass(frozen=True)
class CurrentOffer:
    """Only proven current fields; absent future policies are not fabricated."""

    money: CommercialMoney
    period: CommercialPeriod
    quantity: CommercialQuantity
    tariff_id: int
    tariff_service_id: int
    period_id: int
    period_membership_id: int
    price_id: int
    prepaid: bool
    full_funding_required: bool
    block_to_close_days: int
    evidence_mode: CommercialEvidenceMode
    observed_at: datetime
    fingerprint: str


def current_offer_fingerprint(account_id: str, selection: ProductLinkRequest, offer: CurrentOffer) -> str:
    """Current acceptance identity, reproducible from old immutable snapshots.

    The next scheduled price is observation metadata. The selected price's
    identity/start and all current commercial conditions remain material.
    """
    period = asdict(offer.period)
    del period["price_effective_until"]
    return commercial_digest(
        canonical_document(
            {
                "schema": "current-terms:v2",
                "scope": account_id,
                "selection": selection.model_dump(),
                "money": asdict(offer.money),
                "period": period,
                "quantity": asdict(offer.quantity),
                "price_id": offer.price_id,
                "period_membership_id": offer.period_membership_id,
                "defaults": [offer.tariff_service_id],
                "prepaid": offer.prepaid,
                "full_funding_required": offer.full_funding_required,
                "block_to_close_days": offer.block_to_close_days,
            }
        )
    )
