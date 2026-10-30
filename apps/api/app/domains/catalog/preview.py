"""Source product discovery and explicit current-offer states; no sale/access grant."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.core.errors import AppError
from app.domains.catalog.contracts import CapabilityManifest, SourceProvenance
from app.domains.catalog.link_publication import StoredProductLink
from app.domains.catalog.product_link import CurrentOffer


class CatalogUnavailable(AppError):
    def __init__(self, reason: str = "catalog_unavailable") -> None:
        super().__init__(reason)


class CatalogProductNotFound(AppError):
    def __init__(self) -> None:
        super().__init__("catalog_product_not_found")


Availability = Literal["DETAILS_REQUIRED", "UNMAPPED", "CURRENT_OFFER", "OFFER_UNSUPPORTED", "OFFER_INCOMPLETE"]


@dataclass(frozen=True)
class ProductPreview:
    product_id: str
    kernel_provenance: SourceProvenance
    availability: Availability
    link: StoredProductLink | None = None
    offer: CurrentOffer | None = None
    reason: str | None = None
    manifest: CapabilityManifest | None = None


def require_enabled_product(manifest: CapabilityManifest, product_id: str) -> None:
    product = next((item for item in manifest.products if item.product_id == product_id and item.enabled), None)
    if product is None:
        raise CatalogProductNotFound()


def list_product_previews(manifest: CapabilityManifest) -> tuple[ProductPreview, ...]:
    return tuple(
        ProductPreview(item.product_id, manifest.provenance, "DETAILS_REQUIRED")
        for item in sorted(manifest.products, key=lambda item: item.product_id)
        if item.enabled
    )
