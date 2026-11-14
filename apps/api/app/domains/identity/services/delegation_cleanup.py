"""Independent bounded reclamation; expired exchanged tokens retain parent evidence."""

from app.core.time import utc_now
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.persistence.backend_delegations import prune_delegation_batch

CLEANUP_BATCH_SIZE = 100


def cleanup_batch(factory: SessionFactory, *, tenant_id: str, region: str) -> bool:
    with factory() as db:
        more = prune_delegation_batch(db, tenant_id=tenant_id, region=region, now=utc_now(), limit=CLEANUP_BATCH_SIZE)
        db.commit()
        return more
