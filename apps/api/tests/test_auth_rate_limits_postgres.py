from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.domains.identity.errors import AuthenticationRateLimitedError
from app.domains.identity.services.auth import (
    _login_account_cooldown_seconds,
    _persist_fixed_window_attempt,
)
from app.infrastructure.persistence.authentication_rate_limit import (
    clear_authentication_rate_limit,
    get_login_account_rate_limit_state,
    record_login_account_failure,
)
from app.models import AuthenticationRateLimit


pytestmark = pytest.mark.postgres


def test_rate_limited_attempt_is_committed_before_public_error(db_session: Session) -> None:
    now = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
    key = "registration:account:anytoolai:ru:durable@example.com"

    for index in range(5):
        _persist_fixed_window_attempt(
            db_session,
            key=key,
            limit=5,
            now=now + timedelta(seconds=index),
        )

    with pytest.raises(AuthenticationRateLimitedError):
        _persist_fixed_window_attempt(
            db_session,
            key=key,
            limit=5,
            now=now + timedelta(seconds=5),
        )

    db_session.expire_all()
    stored = db_session.get(AuthenticationRateLimit, key)
    assert stored is not None
    assert stored.count == 6


@pytest.mark.parametrize(
    ("failure_count", "cooldown_seconds"),
    [(9, 0), (10, 1), (11, 2), (12, 4), (13, 8), (14, 16), (15, 32), (16, 60), (100, 60)],
)
def test_login_account_cooldown_schedule(failure_count: int, cooldown_seconds: int) -> None:
    assert _login_account_cooldown_seconds(failure_count) == cooldown_seconds


def test_login_failure_state_can_be_cleared_after_success(db_session: Session) -> None:
    now = datetime(2026, 9, 30, 13, 0, tzinfo=UTC)
    key = "login:account:anytoolai:ru:clear@example.com"
    record_login_account_failure(
        db_session,
        key=key,
        now=now,
        expires_at=now + timedelta(minutes=15),
    )
    db_session.commit()

    assert get_login_account_rate_limit_state(db_session, key=key) is not None
    assert clear_authentication_rate_limit(db_session, key=key) == 1
    db_session.commit()
    assert get_login_account_rate_limit_state(db_session, key=key) is None
