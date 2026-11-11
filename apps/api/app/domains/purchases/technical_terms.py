"""Immutable purchased meaning and source provenance; no I/O or access derivation."""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.catalog.admission import require_selected_capability
from app.domains.catalog.commercial_offer import canonical_document, commercial_digest
from app.domains.catalog.contracts import CapabilityManifest, SourceProvenance
from app.domains.catalog.mapping_evidence import Digest, Nonempty
from app.domains.catalog.product_link import ProductLinkDocument, ProductLinkRequest, QUANTITY_LINK_SCHEMA
from app.domains.catalog.technical_offer import TechnicalOffer as TechnicalOffer


class TestTermsSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["development-purchase-terms:v1"]
    source_version: Nonempty
    provenance: Literal[SourceProvenance.SIMULATED]
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
    schema_version: Literal["purchased-technical-terms:v1", "purchased-technical-terms:v2"] = (
        "purchased-technical-terms:v1"
    )
    source_version: Nonempty
    source_digest: Digest
    provenance: SourceProvenance = SourceProvenance.SIMULATED
    mapping_digest: Digest | None = Field(default=None, exclude_if=lambda value: value is None)
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
        if self.schema_version == "purchased-technical-terms:v1":
            if self.provenance != SourceProvenance.SIMULATED or self.mapping_digest is not None:
                raise ValueError("legacy technical terms remain simulated")
        elif (
            self.provenance != SourceProvenance.CONFIGURED_SOURCE
            or self.kernel_provenance != SourceProvenance.CONFIGURED_SOURCE
            or self.mapping_digest is None
            or self.source_version != QUANTITY_LINK_SCHEMA
        ):
            raise ValueError("configured technical terms require mapping provenance")
        if self.selection.product_id != self.offer.product_id or self.digest != commercial_digest(
            canonical_document(self.model_dump(mode="json", exclude={"digest"}))
        ):
            raise ValueError("invalid technical terms identity")
        return self

    def confirmation_digest(self) -> str:
        """Selected accepted meaning, separate from full-source audit identity."""
        return commercial_digest(
            canonical_document(
                {
                    "schema_version": "selected-technical-terms:v1",
                    "provenance": self.provenance,
                    "offer": self.offer.model_dump(mode="json"),
                    "account_id": self.account_id,
                    "revision_id": str(self.revision_id),
                    "selection": self.selection.model_dump(mode="json"),
                    "commercial_fingerprint": self.commercial_fingerprint,
                    "kernel_provenance": self.kernel_provenance,
                }
            )
        )


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
        "provenance": SourceProvenance.SIMULATED,
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


def bind_published_terms(
    link: ProductLinkDocument,
    manifest: CapabilityManifest,
    *,
    revision_id: UUID,
    commercial_fingerprint: str,
) -> AcceptedTechnicalTerms:
    """Bind the published quantity; unrelated manifest changes are audit-only."""
    offer = link.technical_offer
    if offer is None or link.schema_version != QUANTITY_LINK_SCHEMA:
        raise ValueError("published technical offer required")
    if manifest.provenance != SourceProvenance.CONFIGURED_SOURCE:
        raise ValueError("configured Kernel source required")
    require_selected_capability(manifest, product_id=offer.product_id, metric_units={offer.metric_key: offer.unit})
    document = {
        "schema_version": "purchased-technical-terms:v2",
        "source_version": link.schema_version,
        "source_digest": link.content_digest(),
        "provenance": SourceProvenance.CONFIGURED_SOURCE,
        "mapping_digest": link.identity_digest,
        "offer": offer.model_dump(mode="json"),
        "account_id": link.scope.external_billing_account_id,
        "revision_id": str(revision_id),
        "selection": link.selection.model_dump(mode="json"),
        "commercial_fingerprint": commercial_fingerprint,
        "kernel_manifest_version": manifest.manifest_version,
        "kernel_provenance": manifest.provenance,
    }
    return AcceptedTechnicalTerms.model_validate(
        {**document, "digest": commercial_digest(canonical_document(document))}
    )
