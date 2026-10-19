"""Anonymous DB-only previews. Stored approval is never current sellability."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.core.errors import AppError
from app.domains.catalog.commercial_offer import CommercialScope
from app.domains.catalog.mapping_evidence import MappingRefused
from app.domains.catalog.publication import StoredMapping, validate_stored_mapping
from app.infrastructure.queries.catalog import list_mapping_heads


class CatalogUnavailable(AppError):
    def __init__(self) -> None:
        super().__init__("catalog_unavailable")


class CatalogProductNotFound(AppError):
    def __init__(self) -> None:
        super().__init__("catalog_product_not_found")


@dataclass(frozen=True)
class ProductPreview:
    product_id: str
    # Multiple distinct eligible heads are intentionally not ranked by price.
    offers: tuple[StoredMapping, ...]


def list_product_previews(db: Session, *, scope: CommercialScope, allow_simulated: bool) -> tuple[ProductPreview, ...]:
    if not scope.external_billing_account_id:
        raise CatalogUnavailable()
    grouped: dict[str, list[StoredMapping]] = {}
    for row in list_mapping_heads(db, account_id=scope.external_billing_account_id):
        try:
            stored = validate_stored_mapping(
                row, scope=scope, offer_id=row.billing_offer_id, allow_simulated=allow_simulated
            )
        except MappingRefused as error:
            if error.code == "mapping_simulation_forbidden":
                continue
            # Do not conceal an invalid head by selecting older evidence or
            # publishing a product identity taken from an unvalidated document.
            raise CatalogUnavailable() from None
        grouped.setdefault(stored.document.material.technical.product_id, []).append(stored)
    return tuple(ProductPreview(product_id, tuple(grouped[product_id])) for product_id in sorted(grouped))


def get_product_preview(
    db: Session, *, scope: CommercialScope, allow_simulated: bool, product_id: str
) -> ProductPreview:
    for product in list_product_previews(db, scope=scope, allow_simulated=allow_simulated):
        if product.product_id == product_id:
            return product
    raise CatalogProductNotFound()
