"""Shared lock identity and exact failure classification; no provider/DB I/O."""

from __future__ import annotations

from unittest.mock import Mock

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.domains.billing.contracts import BillingRefused
from app.domains.billing import customer_scope
from app.domains.catalog import link_publication
from app.domains.catalog.commercial_offer import CommercialScope
from app.infrastructure.persistence import billing_connections as storage
from app.infrastructure.persistence.commercial_mappings import MappingStorageBusy, MappingStorageDeadline


def db_session() -> Mock:
    db = Mock(spec=Session)
    db.get_bind.return_value.dialect.name = "postgresql"
    db.connection.return_value.get_isolation_level.return_value = "READ COMMITTED"
    return db


@pytest.mark.parametrize("sqlstate", ["55P03", "57014", "40P01", "08006", None])
def test_connection_lock_preserves_non_contention_failures(sqlstate: str | None) -> None:
    db = db_session()
    cause = Exception("private database diagnostic")
    cause.sqlstate = sqlstate
    original = OperationalError("SELECT", {}, cause)
    db.execute.side_effect = original
    expected = storage.ConnectionScopeBusy if sqlstate == "55P03" else OperationalError
    with pytest.raises(expected) as caught:
        storage.lock_connection_scope(db, tenant_id="anytoolai", region="ru", provider_origin="https://billing.test")
    if sqlstate != "55P03":
        assert caught.value is original
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


@pytest.mark.parametrize("isolation", ["REPEATABLE READ", "SERIALIZABLE"])
def test_unsupported_snapshot_cannot_authorize_scope_after_wait(isolation: str) -> None:
    db = db_session()
    db.connection.return_value.get_isolation_level.return_value = isolation
    with pytest.raises(storage.ConnectionIsolationUnsupported):
        storage.lock_connection_scope(db, tenant_id="anytoolai", region="ru", provider_origin="https://billing.test")
    db.execute.assert_not_called()


def test_customer_contention_is_safe_and_temporary(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.tests.support.any709_step1 import step1_settings

    monkeypatch.setattr(
        customer_scope, "lock_connection_scope", Mock(side_effect=storage.ConnectionScopeBusy("private"))
    )
    with pytest.raises(BillingRefused) as caught:
        customer_scope.lock_customer_connection(db_session(), step1_settings())
    assert caught.value.code == "billing_busy" and caught.value.status == 503
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("sqlstate", ["57014", "08006"])
def test_publication_preserves_deadline_and_unexpected_failure_meaning(
    monkeypatch: pytest.MonkeyPatch, sqlstate: str
) -> None:
    cause = Exception("private database diagnostic")
    cause.sqlstate = sqlstate
    original = OperationalError("SELECT", {}, cause)
    monkeypatch.setattr(link_publication, "lock_connection_scope", Mock(side_effect=original))
    with pytest.raises(MappingStorageDeadline if sqlstate == "57014" else OperationalError) as caught:
        link_publication._lock_connection(
            db_session(), CommercialScope("anytoolai", "ru", "scope"), "https://billing.test"
        )
    if sqlstate != "57014":
        assert caught.value is original


def test_publication_contention_uses_existing_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(link_publication, "lock_connection_scope", Mock(side_effect=storage.ConnectionScopeBusy()))
    with pytest.raises(MappingStorageBusy):
        link_publication._lock_connection(
            db_session(), CommercialScope("anytoolai", "ru", "scope"), "https://billing.test"
        )
