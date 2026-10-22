from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import CommercialMappingRevision


def mapping_revision_history(db: Session, *, account_id: str, offer_id: str) -> Iterator[CommercialMappingRevision]:
    """Read retained pins after the publisher has acquired this scope's lock."""
    statement = (
        select(CommercialMappingRevision)
        .where(
            CommercialMappingRevision.external_billing_account_id == account_id,
            CommercialMappingRevision.billing_offer_id == offer_id,
        )
        .order_by(CommercialMappingRevision.revision_number)
        .execution_options(yield_per=100)
    )
    yield from db.scalars(statement)


def find_mapping_revision(
    db: Session, *, account_id: str, offer_id: str, revision: int | None = None
) -> CommercialMappingRevision | None:
    """Select before validating. Never fall back past an invalid latest row."""
    statement = select(CommercialMappingRevision).where(
        CommercialMappingRevision.external_billing_account_id == account_id,
        CommercialMappingRevision.billing_offer_id == offer_id,
    )
    if revision is not None:
        statement = statement.where(CommercialMappingRevision.revision_number == revision)
    return db.scalar(statement.order_by(CommercialMappingRevision.revision_number.desc()).limit(1))
