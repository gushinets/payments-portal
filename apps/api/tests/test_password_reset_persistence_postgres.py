from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import Session

from app.infrastructure.persistence.authentication_rate_limit import (
    clear_authentication_rate_limit,
    get_login_account_rate_limit_state,
    increment_authentication_rate_limit,
    prune_expired_authentication_rate_limits,
    record_login_account_failure,
)
from app.infrastructure.persistence.password_reset import increment_password_reset_rate_limit
from app.models import AuthenticationRateLimit


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


def test_authentication_rate_limit_fixed_window_increment_and_reset(db_session: Session) -> None:
    key = "registration:account:anytoolai:ru:persistence@example.com"
    first_attempt_at = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
    first_window_expires_at = first_attempt_at + timedelta(minutes=15)

    assert (
        increment_authentication_rate_limit(
            db_session,
            key=key,
            now=first_attempt_at,
            expires_at=first_window_expires_at,
        )
        == 1
    )
    assert (
        increment_authentication_rate_limit(
            db_session,
            key=key,
            now=first_attempt_at + timedelta(minutes=1),
            expires_at=first_window_expires_at + timedelta(minutes=1),
        )
        == 2
    )

    persisted = db_session.get(AuthenticationRateLimit, key)
    assert persisted is not None
    assert persisted.window_start == first_attempt_at
    assert persisted.expires_at == first_window_expires_at

    next_window_at = first_window_expires_at
    assert (
        increment_authentication_rate_limit(
            db_session,
            key=key,
            now=next_window_at,
            expires_at=next_window_at + timedelta(minutes=15),
        )
        == 1
    )


def test_login_account_failure_state_read_is_non_mutating(db_session: Session) -> None:
    key = "login:account:anytoolai:ru:persistence@example.com"
    first_attempt_at = datetime(2026, 9, 30, 10, 0, tzinfo=UTC)
    expires_at = first_attempt_at + timedelta(minutes=15)

    first_state = record_login_account_failure(
        db_session,
        key=key,
        now=first_attempt_at,
        expires_at=expires_at,
    )
    second_attempt_at = first_attempt_at + timedelta(seconds=1)
    second_state = record_login_account_failure(
        db_session,
        key=key,
        now=second_attempt_at,
        expires_at=expires_at,
    )
    observed_state = get_login_account_rate_limit_state(db_session, key=key)

    assert first_state.count == 1
    assert second_state.count == 2
    assert second_state.updated_at == second_attempt_at
    assert observed_state == second_state

    observed_again = get_login_account_rate_limit_state(db_session, key=key)
    assert observed_again == observed_state


def test_authentication_rate_limit_clear_and_expired_prune(db_session: Session) -> None:
    now = datetime(2026, 9, 30, 11, 0, tzinfo=UTC)
    expired_key = "verification:ip:anytoolai:ru:192.0.2.10"
    retained_key = "login:ip:anytoolai:ru:192.0.2.11"

    increment_authentication_rate_limit(
        db_session,
        key=expired_key,
        now=now - timedelta(minutes=16),
        expires_at=now - timedelta(minutes=1),
    )
    increment_authentication_rate_limit(
        db_session,
        key=retained_key,
        now=now,
        expires_at=now + timedelta(minutes=15),
    )

    assert prune_expired_authentication_rate_limits(db_session, now=now) == 1
    assert db_session.get(AuthenticationRateLimit, expired_key) is None
    assert db_session.get(AuthenticationRateLimit, retained_key) is not None
    assert clear_authentication_rate_limit(db_session, key=retained_key) == 1
    assert get_login_account_rate_limit_state(db_session, key=retained_key) is None
