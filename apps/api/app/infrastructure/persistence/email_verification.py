from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import MagicLinkPurpose, MagicLinkToken


def get_email_verification_token(
    db: Session,
    *,
    token_hash: str,
    tenant_id: str,
    region: str,
) -> MagicLinkToken | None:
    return (
        db.query(MagicLinkToken)
        .filter(
            MagicLinkToken.token_hash == token_hash,
            MagicLinkToken.tenant_id == tenant_id,
            MagicLinkToken.region == region,
            MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_VERIFICATION,
        )
        .populate_existing()
        .first()
    )


def claim_valid_email_verification_token(
    db: Session,
    *,
    token_hash: str,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
    now: datetime,
) -> int:
    return (
        db.query(MagicLinkToken)
        .filter(
            MagicLinkToken.token_hash == token_hash,
            MagicLinkToken.tenant_id == tenant_id,
            MagicLinkToken.region == region,
            MagicLinkToken.user_id == user_id,
            MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_VERIFICATION,
            MagicLinkToken.used_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .update({"used_at": now}, synchronize_session=False)
    )


def invalidate_outstanding_email_verification_tokens(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
    now: datetime,
) -> int:
    return (
        db.query(MagicLinkToken)
        .filter(
            MagicLinkToken.tenant_id == tenant_id,
            MagicLinkToken.region == region,
            MagicLinkToken.user_id == user_id,
            MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_VERIFICATION,
            MagicLinkToken.used_at.is_(None),
        )
        .update({"used_at": now}, synchronize_session=False)
    )


def get_newest_outstanding_email_verification_token(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
    now: datetime,
) -> MagicLinkToken | None:
    return (
        db.query(MagicLinkToken)
        .filter(
            MagicLinkToken.tenant_id == tenant_id,
            MagicLinkToken.region == region,
            MagicLinkToken.user_id == user_id,
            MagicLinkToken.purpose == MagicLinkPurpose.EMAIL_VERIFICATION,
            MagicLinkToken.used_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .order_by(MagicLinkToken.created_at.desc(), MagicLinkToken.id.desc())
        .first()
    )
