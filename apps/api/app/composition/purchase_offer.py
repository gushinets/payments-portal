"""Live source admission for an accepted purchase's original offer."""

from starlette.concurrency import run_in_threadpool

from app.composition.sources import SourceResources
from app.core.settings import Settings
from app.domains.catalog.commercial_offer import OfferRefusalKind, SelectedOfferRefused
from app.domains.catalog.preview import CatalogProductNotFound, require_enabled_product
from app.domains.catalog.product_link import current_offer_fingerprint
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import financial
from app.domains.purchases.contracts import Purchase, PurchaseRefused
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.current_offer import read_current_offer


def require_configured_seller(configuration: Settings) -> None:
    if error := configuration.lbx_purchase_configuration_error:
        raise PurchaseRefused(error, 503)


async def live_original(
    sources: SourceResources,
    configuration: Settings,
    purchase: Purchase,
    factory: SessionFactory,
    *,
    budget: PreflightBudget,
) -> bool:
    # One total deadline spans customer ensure, original-offer checks and financial I/O.
    require_configured_seller(configuration)
    if purchase.accepted.seller_id != int(configuration.lbx_seller_organization_id):
        await run_in_threadpool(financial.changed_unsent_terms, factory, purchase)
        return False
    manifest = await sources.require_kernel().fetch_manifest(budget=budget)
    try:
        require_enabled_product(manifest, purchase.accepted.selection.product_id)
        offer = await read_current_offer(
            sources.require_lbx(), selection=purchase.accepted.selection, configuration=configuration, budget=budget
        )
    except CatalogProductNotFound:
        await run_in_threadpool(financial.changed_unsent_terms, factory, purchase)
        return False
    except SelectedOfferRefused as error:
        if error.kind != OfferRefusalKind.NOT_SELLABLE:
            raise
        await run_in_threadpool(financial.changed_unsent_terms, factory, purchase)
        return False
    # Recompute immutable historical fields under the current comparison and
    # connection scope. Historical account FKs and accepted digests stay unchanged.
    if offer.fingerprint != current_offer_fingerprint(
        configuration.lbx_external_billing_account_id, purchase.accepted.selection, purchase.accepted.offer
    ):
        await run_in_threadpool(financial.changed_unsent_terms, factory, purchase)
        return False
    return True
