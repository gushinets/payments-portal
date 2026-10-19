"""Select offer heads before inspecting schema, scope or evidence mode."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import CommercialMappingRevision


def list_mapping_heads(db: Session, *, account_id: str) -> list[CommercialMappingRevision]:
    heads = (
        select(
            CommercialMappingRevision.billing_offer_id.label("offer_id"),
            func.max(CommercialMappingRevision.revision_number).label("revision"),
        )
        .where(CommercialMappingRevision.external_billing_account_id == account_id)
        .group_by(CommercialMappingRevision.billing_offer_id)
        .subquery()
    )
    return list(
        db.scalars(
            select(CommercialMappingRevision)
            .join(
                heads,
                (CommercialMappingRevision.billing_offer_id == heads.c.offer_id)
                & (CommercialMappingRevision.revision_number == heads.c.revision),
            )
            .where(CommercialMappingRevision.external_billing_account_id == account_id)
            .order_by(CommercialMappingRevision.billing_offer_id)
        )
    )
