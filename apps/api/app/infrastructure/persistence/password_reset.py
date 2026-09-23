from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import AuthSession, MagicLinkPurpose, MagicLinkToken


def increment_password_reset_rate_limit(
    db: Session,
    *,
    key: str,
    now: datetime,
    expires_at: datetime,
) -> int:
    return db.execute(
        text(
            """
            INSERT INTO password_reset_rate_limits (
                rate_limit_key,
                count,
                window_start,
                expires_at,
                created_at,
                updated_at
            )
            VALUES (:key, 1, :now, :expires_at, :now, :now)
            ON CONFLICT(rate_limit_key) DO UPDATE SET
                count = CASE
                    WHEN password_reset_rate_limits.expires_at <= :now THEN 1
                    ELSE password_reset_rate_limits.count + 1
                END,
                window_start = CASE
                    WHEN password_reset_rate_limits.expires_at <= :now THEN :now
                    ELSE password_reset_rate_limits.window_start
                END,
                expires_at = CASE
                    WHEN password_reset_rate_limits.expires_at <= :now THEN :expires_at
                    ELSE password_reset_rate_limits.expires_at
                END,
                updated_at = :now
            RETURNING count
            """
        ),
        {"key": key, "now": now, "expires_at": expires_at},
    ).scalar_one()


def prune_expired_password_reset_rate_limits(db: Session, *, now: datetime) -> None:
    db.execute(
        text("DELETE FROM password_reset_rate_limits WHERE expires_at <= :now"),
        {"now": now},
    )


def prune_expired_password_reset_tokens(db: Session, *, now: datetime) -> None:
    (
        db.query(MagicLinkToken)
        .filter(
            MagicLinkToken.purpose == MagicLinkPurpose.PASSWORD_RESET,
            MagicLinkToken.expires_at <= now,
        )
        .delete(synchronize_session=False)
    )


def claim_valid_password_reset_token(
    db: Session,
    *,
    token_hash: str,
    tenant_id: str,
    region: str,
    now: datetime,
) -> int:
    return (
        db.query(MagicLinkToken)
        .filter(
            MagicLinkToken.token_hash == token_hash,
            MagicLinkToken.tenant_id == tenant_id,
            MagicLinkToken.region == region,
            MagicLinkToken.purpose == MagicLinkPurpose.PASSWORD_RESET,
            MagicLinkToken.used_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .update({"used_at": now}, synchronize_session=False)
    )


def invalidate_outstanding_password_reset_tokens(
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
            MagicLinkToken.purpose == MagicLinkPurpose.PASSWORD_RESET,
            MagicLinkToken.used_at.is_(None),
        )
        .update({"used_at": now}, synchronize_session=False)
    )


def revoke_active_auth_sessions(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    user_id: uuid.UUID,
    now: datetime,
) -> int:
    return (
        db.query(AuthSession)
        .filter(
            AuthSession.tenant_id == tenant_id,
            AuthSession.region == region,
            AuthSession.user_id == user_id,
            AuthSession.revoked_at.is_(None),
        )
        .update({"revoked_at": now}, synchronize_session=False)
    )
