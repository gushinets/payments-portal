"""Pure negative interpretation, never source admission or paid verification."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.domains.billing.readback_contracts import BoundReadbackSubject, NegativeBasis
from app.integrations.lbx.readback import inspect_readback
from apps.api.tests.factories.reconciliation import (
    subject_factory,
    user_factory,
    agreement_factory,
    subscription_factory,
)


@pytest.mark.parametrize(
    "change,closed,expected",
    [
        ({"current_blocking": 1, "total_price": None, "period_length": 2}, False, "active"),
        ({"current_blocking": 3, "services": None}, False, "active"),
        ({"state": -2, "currency_symbol": None}, False, "inactive"),
        ({"state": 3, "services": None}, False, "ended"),
        ({"state": 99}, False, None),
        ({"current_blocking": 99}, False, None),
        ({}, False, None),
        ({"state": 99, "total_price": None}, True, "ended"),
    ],
)
def test_negative_is_independent_of_incomplete_material(change: dict, closed: bool, expected: str | None) -> None:
    old = subject_factory()
    now = datetime.now(UTC)
    subject = BoundReadbackSubject(
        old.purchase,
        old.customer,
        "anytoolai",
        "ru",
        uuid4(),
        old.agreement_id,
        old.agreement_key,
        old.provider_subscription_id,
        old.subscription_id,
        old.fence,
        None,
        now,
        now + timedelta(minutes=2),
    )
    agreement = agreement_factory().model_copy(update={"close_date": "2026-11-05"} if closed else {})
    finding = inspect_readback(
        subject,
        user=user_factory(),
        agreement=agreement,
        subscription=subscription_factory().model_copy(update=change),
        window=(now, now),
        reads=("customer", "agreement", "subscription"),
    )
    if expected is None:
        assert finding.negative is None
    else:
        assert finding.negative.lifecycle == expected
        assert finding.negative.commercial == "INCOMPLETE"
        assert finding.negative.basis == (NegativeBasis.AGREEMENT if closed else NegativeBasis.SUBSCRIPTION)
        if "period_length" in change:
            assert "effective_terms_mismatch" in finding.negative.reasons
            assert "effective_terms_incomplete" in finding.negative.reasons


@pytest.mark.parametrize("kind", ["customer", "seller", "relationship"])
def test_unproven_owner_is_only_a_scoped_hint(kind: str) -> None:
    old = subject_factory()
    now = datetime.now(UTC)
    subject = BoundReadbackSubject(
        old.purchase,
        old.customer,
        "anytoolai",
        "ru",
        uuid4(),
        old.agreement_id,
        old.agreement_key,
        old.provider_subscription_id,
        old.subscription_id,
        old.fence,
        None,
        now,
        now + timedelta(minutes=2),
    )
    user, agreement, point = user_factory(), agreement_factory(), subscription_factory().model_copy(update={"state": 3})
    if kind == "customer":
        user = user.model_copy(update={"outer_id": "foreign"})
    elif kind == "seller":
        agreement = agreement.model_copy(update={"organization_id": 999})
    else:
        point = point.model_copy(update={"agreement_id": 999})
    finding = inspect_readback(
        subject,
        user=user,
        agreement=agreement,
        subscription=point,
        window=(now, now),
        reads=("customer", "agreement", "subscription"),
    )
    assert finding.negative is None and finding.subject == subject


def test_readback_uses_point_selection_without_second_self_id_checks() -> None:
    old = subject_factory()
    now = datetime.now(UTC)
    subject = BoundReadbackSubject(
        old.purchase,
        old.customer,
        "anytoolai",
        "ru",
        uuid4(),
        old.agreement_id,
        old.agreement_key,
        old.provider_subscription_id,
        old.subscription_id,
        old.fence,
        None,
        now,
        now + timedelta(minutes=2),
    )
    finding = inspect_readback(
        subject,
        user=user_factory().model_copy(update={"user_id": 999}),
        agreement=agreement_factory().model_copy(update={"agreement_id": 998}),
        subscription=subscription_factory().model_copy(update={"subscription_id": 997, "state": 3}),
        window=(now, now),
        reads=("customer", "agreement", "subscription"),
    )
    assert finding.negative.provider_subscription_id == subject.provider_subscription_id
    assert finding.negative.agreement_id == subject.agreement_id
