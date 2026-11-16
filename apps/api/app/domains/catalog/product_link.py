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
from app.domains.catalog.contracts import MAX_PRODUCT_ID_LENGTH, SourceProvenance
from app.domains.catalog.mapping_evidence import Digest, ImmutableInput, Nonempty, PositiveInteger
from app.domains.catalog.technical_offer import TechnicalOffer
from app.domains.catalog.technical_source import LEGACY_KERNEL_OWNERSHIP, SourceIdentifier, TechnicalOwnership


LINK_SCHEMA = "product-link-v2"
QUANTITY_LINK_SCHEMA = "product-link-v3"
OWNED_LINK_SCHEMA = "product-link-v4"
LINK_SCHEMAS = (LINK_SCHEMA, QUANTITY_LINK_SCHEMA, OWNED_LINK_SCHEMA)


class ProductLinkRequest(ImmutableInput):
    product_id: str = Field(min_length=1, max_length=MAX_PRODUCT_ID_LENGTH, pattern=r"\S")
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
    schema_version: Literal["product-link-v2", "product-link-v3", "product-link-v4"] = LINK_SCHEMA
    scope: CommercialScope
    selection: ProductLinkRequest
    technical_offer: TechnicalOffer | None = Field(default=None, exclude_if=lambda value: value is None)
    kernel_provenance: SourceProvenance | None = Field(default=None, exclude_if=lambda value: value is None)
    manifest_provenance: SourceProvenance | None = Field(default=None, exclude_if=lambda value: value is None)
    technical_source_id: SourceIdentifier | None = Field(default=None, exclude_if=lambda value: value is None)
    backend_consumer_id: SourceIdentifier | None = Field(default=None, exclude_if=lambda value: value is None)
    lbx_evidence_mode: CommercialEvidenceMode
    manifest_version: Digest
    manifest_generated_at: AwareDatetime
    evaluated_at: AwareDatetime
    published_at: AwareDatetime
    publisher_principal: str = Field(pattern=r"^os-euid:[0-9]+$")
    reason: Nonempty
    identity_digest: Digest
    product_revision_number: PositiveInteger | None = None

    @property
    def ownership(self) -> TechnicalOwnership:
        if self.schema_version == OWNED_LINK_SCHEMA:
            return TechnicalOwnership(self.technical_source_id, self.backend_consumer_id)
        return LEGACY_KERNEL_OWNERSHIP

    @property
    def source_provenance(self) -> SourceProvenance:
        return self.manifest_provenance if self.schema_version == OWNED_LINK_SCHEMA else self.kernel_provenance

    def content_digest(self) -> str:
        """Complete immutable source/audit document, separate from selected identity."""
        return commercial_digest(canonical_document(self.model_dump(mode="json")))

    def identity_json(self) -> str:
        return canonical_document(
            {
                "schema": self.schema_version,
                "scope": asdict(self.scope),
                "selection": self.selection.model_dump(mode="json"),
                **(
                    {
                        "technical_source_id": self.technical_source_id,
                        "backend_consumer_id": self.backend_consumer_id,
                        "manifest_provenance": self.manifest_provenance,
                    }
                    if self.schema_version == OWNED_LINK_SCHEMA
                    else {"kernel_provenance": self.kernel_provenance}
                ),
                "lbx_evidence_mode": self.lbx_evidence_mode,
                **({"technical_offer": self.technical_offer.model_dump(mode="json")} if self.technical_offer else {}),
            }
        )

    @model_validator(mode="after")
    def validate_identity(self) -> ProductLinkDocument:
        if self.schema_version == OWNED_LINK_SCHEMA:
            if (
                self.technical_source_id is None
                or self.backend_consumer_id is None
                or self.manifest_provenance is None
                or self.kernel_provenance is not None
            ):
                raise ValueError("owned link requires explicit source provenance")
        elif (
            self.technical_source_id is not None
            or self.backend_consumer_id is not None
            or self.manifest_provenance is not None
            or self.kernel_provenance is None
        ):
            raise ValueError("historical link cannot acquire ownership metadata")
        if self.schema_version in (QUANTITY_LINK_SCHEMA, OWNED_LINK_SCHEMA):
            if (
                self.technical_offer is None
                or self.technical_offer.product_id != self.selection.product_id
                or self.source_provenance != SourceProvenance.CONFIGURED_SOURCE
                or self.lbx_evidence_mode != CommercialEvidenceMode.CONFIGURED_SOURCE
            ):
                raise ValueError("invalid configured technical offer")
        elif self.technical_offer is not None:
            raise ValueError("legacy product link has no technical offer")
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
    block_to_close_days: int | None
    evidence_mode: CommercialEvidenceMode
    observed_at: datetime
    fingerprint: str


def current_offer_fingerprint(account_id: str, selection: ProductLinkRequest, offer: CurrentOffer) -> str:
    """Current acceptance identity, reproducible from old immutable snapshots.

    Scheduled prices and LBX's block-to-close setting are observation metadata.
    The selected price's identity/start and purchase conditions remain material.
    Recomputing old snapshots here never changes their stored accepted digest.
    """
    period = asdict(offer.period)
    del period["price_effective_until"]
    return commercial_digest(
        canonical_document(
            {
                "schema": "current-terms:v3",
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
            }
        )
    )
