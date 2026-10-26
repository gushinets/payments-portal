"""Outer source I/O with complete resource-owning DB work dispatched by framework."""

from __future__ import annotations

from starlette.concurrency import run_in_threadpool

from app.composition.mapping_operator import configured_mapping_scope
from app.composition.sources import SourceResources
from app.core.database import SessionLocal
from app.core.settings import Settings
from app.domains.catalog.commercial_offer import OfferRefusalKind, SelectedOfferRefused
from app.domains.catalog.link_publication import query_product_link
from app.domains.catalog.preview import (
    ProductPreview,
    list_product_previews,
    require_enabled_product,
)
from app.integrations.lbx.current_offer import read_current_offer


async def catalog_preview(
    sources: SourceResources,
    configuration: Settings,
    *,
    product_id: str | None = None,
) -> tuple[ProductPreview, ...]:
    async with sources.preflight.operation() as budget:
        manifest = await sources.require_kernel().fetch_manifest(budget=budget)
        if product_id is None:
            return list_product_previews(manifest)
        require_enabled_product(manifest, product_id)
        # No DB resource is made on the event loop or moved between threads.
        if not configuration.lbx_external_billing_account_id:
            return (
                ProductPreview(
                    product_id, manifest.provenance, "OFFER_INCOMPLETE", reason=configuration.lbx_configuration_error
                ),
            )
        link = await run_in_threadpool(
            query_product_link,
            SessionLocal,
            scope=configured_mapping_scope(configuration),
            product_id=product_id,
            deadline=budget.work_deadline,
            lock_timeout_seconds=configuration.mapping_lock_timeout_seconds,
        )
        budget.check()
        if link is None:
            return (ProductPreview(product_id, manifest.provenance, "UNMAPPED"),)
        try:
            offer = await read_current_offer(
                sources.require_lbx(), selection=link.document.selection, configuration=configuration, budget=budget
            )
        except SelectedOfferRefused as error:
            # Protocol/outage errors retain HTTP failure treatment at Presentation.
            if error.reason.startswith("lbx_") or error.reason == "selected_source_changed":
                raise
            availability = "OFFER_UNSUPPORTED" if error.kind == OfferRefusalKind.NOT_SELLABLE else "OFFER_INCOMPLETE"
            return (ProductPreview(product_id, manifest.provenance, availability, link, reason=error.code),)
        return (ProductPreview(product_id, manifest.provenance, "CURRENT_OFFER", link, offer),)
