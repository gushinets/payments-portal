"""Local lock order for new purchase acceptance; no I/O or transaction owner."""

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.customer_scope import lock_customer_connection
from app.domains.catalog.link_publication import StoredProductLink
from app.infrastructure.persistence.commercial_mappings import lock_mapping_scope


def lock_purchase_link(db: Session, configuration: Settings, link: StoredProductLink, product_id: str) -> str:
    """Caller holds user; take origin before product, head and consent locks."""
    lock_customer_connection(db, configuration)
    account = link.document.scope.external_billing_account_id
    lock_mapping_scope(db, account_id=account, offer_id="product-head:v2:" + product_id)
    return account
