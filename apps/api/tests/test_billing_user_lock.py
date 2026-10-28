"""Only a known row-lock timeout is an expected temporary billing refusal."""

from __future__ import annotations

from unittest.mock import Mock
from uuid import uuid4

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.domains.billing import customers
from app.domains.billing.contracts import BillingRefused
from app.infrastructure.queries import billing_customers as queries


@pytest.mark.parametrize("sqlstate", ["55P03", "57014", "08006", None])
def test_user_lock_distinguishes_contention_from_other_database_failures(sqlstate: str | None) -> None:
    db = Mock(spec=Session)
    db.get_bind.return_value.dialect.name = "postgresql"
    original = Exception("private database diagnostic")
    original.sqlstate = sqlstate
    failure = OperationalError("SELECT", {}, original)
    db.scalars.side_effect = failure
    expected = queries.BillingUserLockBusy if sqlstate == "55P03" else OperationalError
    with pytest.raises(expected) as caught:
        queries.lock_user(db, uuid4())
    if sqlstate != "55P03":
        assert caught.value is failure
    db.commit.assert_not_called()
    db.rollback.assert_not_called()


def test_billing_lock_refusal_contains_no_database_diagnostics(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(customers, "lock_storage_user", Mock(side_effect=queries.BillingUserLockBusy("private")))
    with pytest.raises(BillingRefused) as caught:
        customers.lock_user(Mock(spec=Session), uuid4())
    assert caught.value.code == "billing_busy"
    assert caught.value.status == 503
    assert "private" not in str(caught.value)
