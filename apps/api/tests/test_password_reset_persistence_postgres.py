from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.infrastructure.persistence.password_reset import increment_password_reset_rate_limit


pytestmark = pytest.mark.postgres


def test_password_reset_rate_limit_upsert_returns_persisted_attempt_count(db_session: Session) -> None:
    key = "account:anytoolai:ru:persistence@example.com"
    first_attempt_at = datetime(2026, 9, 13, 9, 0, tzinfo=UTC)
    first_window_expires_at = first_attempt_at + timedelta(minutes=15)

    assert (
        increment_password_reset_rate_limit(
            db_session,
            key=key,
            now=first_attempt_at,
            expires_at=first_window_expires_at,
        )
        == 1
    )
    assert (
        increment_password_reset_rate_limit(
            db_session,
            key=key,
            now=first_attempt_at + timedelta(minutes=1),
            expires_at=first_window_expires_at + timedelta(minutes=1),
        )
        == 2
    )

    next_window_at = first_window_expires_at + timedelta(seconds=1)
    assert (
        increment_password_reset_rate_limit(
            db_session,
            key=key,
            now=next_window_at,
            expires_at=next_window_at + timedelta(minutes=15),
        )
        == 1
    )
