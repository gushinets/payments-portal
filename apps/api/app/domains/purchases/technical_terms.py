"""Immutable simulated purchased meaning; no source I/O or access derivation."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.catalog.admission import require_selected_capability
from app.domains.catalog.commercial_offer import canonical_document, commercial_digest
from app.domains.catalog.contracts import CapabilityManifest, SourceProvenance
from app.domains.catalog.mapping_evidence import Digest, Nonempty
from app.domains.catalog.product_link import ProductLinkRequest

# Exact in JavaScript/JSON and within PostgreSQL BIGINT; no lossy quantity encoding.
TechnicalQuantity = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class TechnicalOffer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product_id: Nonempty
    metric_key: Nonempty
    unit: Nonempty
    quantity: TechnicalQuantity
    quantity_mode: Literal["fixed_per_cycle"]


class TestTermsSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["development-purchase-terms:v1"]
    source_version: Nonempty
    provenance: Literal["SIMULATED"]
    purpose: Nonempty
    offers: tuple[TechnicalOffer, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_offers(self) -> TestTermsSource:
        if len({offer.product_id for offer in self.offers}) != len(self.offers) or len(
            {offer.metric_key for offer in self.offers}
        ) != len(self.offers):
            raise ValueError("duplicate technical offer")
        return self

    def content_digest(self) -> str:
        return commercial_digest(canonical_document(self.model_dump(mode="json")))


class AcceptedTechnicalTerms(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["purchased-technical-terms:v1"] = "purchased-technical-terms:v1"
    source_version: Nonempty
    source_digest: Digest
    provenance: Literal["SIMULATED"] = "SIMULATED"
    offer: TechnicalOffer
    account_id: Nonempty
    revision_id: UUID
    selection: ProductLinkRequest
    commercial_fingerprint: Digest
    kernel_manifest_version: Digest
    kernel_provenance: SourceProvenance
    digest: Digest

    @model_validator(mode="after")
    def verify_digest(self) -> AcceptedTechnicalTerms:
        if self.selection.product_id != self.offer.product_id or self.digest != commercial_digest(
            canonical_document(self.model_dump(mode="json", exclude={"digest"}))
        ):
            raise ValueError("invalid technical terms identity")
        return self


def bind_test_terms(
    source: TestTermsSource,
    manifest: CapabilityManifest,
    *,
    account_id: str,
    revision_id: UUID,
    selection: ProductLinkRequest,
    commercial_fingerprint: str,
) -> AcceptedTechnicalTerms:
    offer = next((item for item in source.offers if item.product_id == selection.product_id), None)
    if offer is None:
        raise ValueError("technical product unavailable")
    require_selected_capability(manifest, product_id=offer.product_id, metric_units={offer.metric_key: offer.unit})
    document = {
        "schema_version": "purchased-technical-terms:v1",
        "source_version": source.source_version,
        "source_digest": source.content_digest(),
        "provenance": "SIMULATED",
        "offer": offer.model_dump(mode="json"),
        "account_id": account_id,
        "revision_id": str(revision_id),
        "selection": selection.model_dump(mode="json"),
        "commercial_fingerprint": commercial_fingerprint,
        "kernel_manifest_version": manifest.manifest_version,
        "kernel_provenance": manifest.provenance,
    }
    return AcceptedTechnicalTerms.model_validate(
        {**document, "digest": commercial_digest(canonical_document(document))}
    )
