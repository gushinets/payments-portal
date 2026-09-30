from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models import AuthenticationRateLimit


@dataclass(frozen=True)
class LoginAccountRateLimitState:
    count: int
    window_start: datetime
    expires_at: datetime
    updated_at: datetime


def _increment_authentication_rate_limit(
    db: Session,
    *,
    key: str,
    now: datetime,
    expires_at: datetime,
) -> LoginAccountRateLimitState:
    db.execute(
        text(
            """
            INSERT INTO authentication_rate_limits (
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
                    WHEN authentication_rate_limits.expires_at <= :now THEN 1
                    ELSE authentication_rate_limits.count + 1
                END,
                window_start = CASE
                    WHEN authentication_rate_limits.expires_at <= :now THEN :now
                    ELSE authentication_rate_limits.window_start
                END,
                expires_at = CASE
                    WHEN authentication_rate_limits.expires_at <= :now THEN :expires_at
                    ELSE authentication_rate_limits.expires_at
                END,
                updated_at = :now
            RETURNING count
            """
        ),
        {"key": key, "now": now, "expires_at": expires_at},
    ).scalar_one()
    row = db.query(AuthenticationRateLimit).populate_existing().filter_by(rate_limit_key=key).one()
    return LoginAccountRateLimitState(
        count=row.count,
        window_start=row.window_start,
        expires_at=row.expires_at,
        updated_at=row.updated_at,
    )


def increment_authentication_rate_limit(
    db: Session,
    *,
    key: str,
    now: datetime,
    expires_at: datetime,
) -> int:
    return _increment_authentication_rate_limit(
        db,
        key=key,
        now=now,
        expires_at=expires_at,
    ).count


def get_login_account_rate_limit_state(
    db: Session,
    *,
    key: str,
) -> LoginAccountRateLimitState | None:
    row = db.query(AuthenticationRateLimit).filter_by(rate_limit_key=key).one_or_none()
    if row is None:
        return None
    return LoginAccountRateLimitState(
        count=row.count,
        window_start=row.window_start,
        expires_at=row.expires_at,
        updated_at=row.updated_at,
    )


def record_login_account_failure(
    db: Session,
    *,
    key: str,
    now: datetime,
    expires_at: datetime,
) -> LoginAccountRateLimitState:
    return _increment_authentication_rate_limit(
        db,
        key=key,
        now=now,
        expires_at=expires_at,
    )


def clear_authentication_rate_limit(db: Session, *, key: str) -> int:
    result = db.execute(
        text("DELETE FROM authentication_rate_limits WHERE rate_limit_key = :key"),
        {"key": key},
    )
    return result.rowcount


def prune_expired_authentication_rate_limits(db: Session, *, now: datetime) -> int:
    result = db.execute(
        text("DELETE FROM authentication_rate_limits WHERE expires_at <= :now"),
        {"now": now},
    )
    return result.rowcount
