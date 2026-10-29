"""SIMULATED lifecycle/term proof; these tests never call real LBX."""

from dataclasses import replace
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof, RECONCILIATION_SCHEMA
from app.integrations.lbx.financial import Subscription, prove_subscription
from app.integrations.lbx.errors import LbxScopeMismatch
from app.integrations.lbx.reconciliation import normalize_subscription
from apps.api.tests.factories.reconciliation import (
    subject_factory,
    user_factory,
    agreement_factory,
    tariff_factory,
    subscription_factory,
)
from apps.api.tests.support.any709_step1 import step1_settings


@pytest.mark.parametrize(
    "state,block,lifecycle,financial,reason",
    [
        (-2, 0, "inactive", "blocked", "waiting"),
        (-1, 0, "inactive", "blocked", "inactive"),
        (0, 0, "inactive", "blocked", "inactive"),
        (2, 0, "active", "allowed", "active"),
        (2, 1, "active", "blocked", "financial_block"),
        (2, 3, "active", "blocked", "administrative_block"),
        (3, 0, "ended", "blocked", "ended"),
    ],
)
def test_billing_subscription_reconciliation_lifecycle(
    state: int, block: int, lifecycle: str, financial: str, reason: str
) -> None:
    subject = subject_factory()
    point = subscription_factory().model_copy(update={"state": state, "current_blocking": block})
    if state == -2:
        point = point.model_copy(
            update={"last_tariffication_period_start": None, "last_tariffication_period_end": None}
        )
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=point,
    )
    assert proof.complete and proof.commercial == CommercialProof.MATCH
    assert (proof.lifecycle, proof.financial) == (lifecycle, financial)
    assert reason in proof.reasons


@pytest.mark.parametrize(
    "change,classification",
    [
        ({"total_price": None}, CommercialProof.INCOMPLETE),
        ({"services": None}, CommercialProof.INCOMPLETE),
        ({"currency_symbol": None}, CommercialProof.INCOMPLETE),
        ({"services": []}, CommercialProof.MISMATCH),
        ({"currency_symbol": "USD"}, CommercialProof.MISMATCH),
        ({"period_length": 2}, CommercialProof.MISMATCH),
        ({"tariff_id": 702}, CommercialProof.MISMATCH),
    ],
)
def test_billing_subscription_reconciliation_commercial(change: dict, classification: CommercialProof) -> None:
    subject = subject_factory()
    point = subscription_factory().model_copy(update=change)
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=point,
    )
    assert proof.commercial == classification
    assert proof.identity == IdentityProof.MATCH


@pytest.mark.parametrize("field,value", [("price", 15), ("multiplicator", 2), ("tariff_service_id", 1002)])
def test_billing_subscription_reconciliation_effective_drift(field: str, value: int) -> None:
    subject = subject_factory()
    raw = subscription_factory().model_dump()
    raw["services"][0][field] = value
    # A catalog price or unchanged provider instance cannot mask effective drift.
    raw["services"][0]["tariff_price"] = 999
    raw["subscription_instance_id"] = 123
    point = Subscription.model_validate(raw)
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=point,
    )
    assert proof.commercial == CommercialProof.MISMATCH


@pytest.mark.parametrize(
    "change",
    [
        {"state": 99},
        {"current_blocking": 99},
        {"last_tariffication_period_start": None},
        {"last_tariffication_period_start": "1970-01-01 00:00:00"},
        {"last_tariffication_period_end": "2026-09-01"},
        {"last_tariffication_period_start": "2026-02-30"},
        {"subscription_instance_start_date": "2026-10-15"},
    ],
)
def test_billing_subscription_reconciliation_unknown_or_incomplete(change: dict) -> None:
    subject = subject_factory()
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=subscription_factory().model_copy(update=change),
    )
    assert not proof.complete and proof.financial is None


@pytest.mark.parametrize("kind", ["customer", "agreement", "seller", "subscription"])
def test_billing_subscription_reconciliation_ownership_conflicts(kind: str) -> None:
    subject = subject_factory()
    user, agreement, point = user_factory(), agreement_factory(), subscription_factory()
    if kind == "customer":
        user = user.model_copy(update={"outer_id": "foreign"})
    elif kind == "agreement":
        agreement = agreement.model_copy(update={"user_id": 999})
    elif kind == "seller":
        agreement = agreement.model_copy(update={"organization_id": 999})
    else:
        point = point.model_copy(update={"agreement_id": 999})
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user,
        agreement=agreement,
        tariff=None,
        subscription=point.model_copy(update={"total_price": None}),
    )
    assert proof.identity == IdentityProof.CONFLICT and proof.financial is None


def test_billing_subscription_reconciliation_negative_independent_of_terms_and_sale_flags() -> None:
    subject = subject_factory()
    tariff = tariff_factory(subject)
    tariff = replace(tariff, value=tariff.value.model_copy(update={"archive": 1, "assign_unavailable": 1}))
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff,
        subscription=subscription_factory(),
    )
    assert proof.complete and proof.commercial == CommercialProof.MATCH
    for point in (
        subscription_factory().model_copy(update={"state": 3, "total_price": None}),
        subscription_factory().model_copy(update={"current_blocking": 1, "services": None}),
    ):
        proof = normalize_subscription(
            subject,
            step1_settings(),
            user=user_factory(),
            agreement=agreement_factory(),
            tariff=None,
            subscription=point,
        )
        assert proof.financial == "blocked" and not proof.complete
    ended = subscription_factory().model_copy(update={"state": 3})
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory().model_copy(update={"close_date": "2026-10-20"}),
        tariff=tariff,
        subscription=ended,
    )
    assert proof.lifecycle == "ended" and proof.complete
    with pytest.raises(LbxScopeMismatch):
        prove_subscription(
            ended,
            agreement_id=456,
            selection=subject.purchase.accepted.selection,
            offer=subject.purchase.accepted.offer,
        )


@pytest.mark.parametrize("field", ["currency_id", "balance_blocks", "payment_type", "float_period"])
def test_billing_subscription_reconciliation_missing_policy(field: str) -> None:
    subject = subject_factory()
    tariff = tariff_factory(subject)
    tariff = replace(tariff, value=tariff.value.model_copy(update={field: None}))
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff,
        subscription=subscription_factory(),
    )
    assert not proof.complete and proof.commercial == CommercialProof.INCOMPLETE


def test_billing_subscription_reconciliation_invalid_decoder_and_runbook_contract() -> None:
    with pytest.raises(ValidationError):
        Subscription.model_validate(
            {
                "subscription_id": 1,
                "agreement_id": 2,
                "tariff_id": 3,
                "subscription_start_date": "secret arbitrary text",
            }
        )
    runbook = Path("docs/engineering/ANY-715-billing-operations.md").read_text()
    for phrase in (
        RECONCILIATION_SCHEMA,
        "get_user()",
        "get_agreement()",
        "get_tariff()",
        "get_subscription()",
        "COMPLETE_MATCH",
        "COMPLETE_MISMATCH",
        "INCOMPLETE",
        "six hours",
        "SIMULATED",
        "NOT_RUN",
        "primary_subscription_id=NULL",
        "read_started_at",
    ):
        assert phrase in runbook


def test_billing_subscription_reconciliation_extra_service_and_contradictory_tariff_read() -> None:
    subject = subject_factory()
    point = subscription_factory()
    extra = point.model_copy(update={"services": [*point.services, point.services[0]]})
    evidence = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=extra,
    )
    assert evidence.commercial == CommercialProof.MISMATCH
    for changes in ({"external_billing_account_id": "foreign"}, {"tariff_id": 702}):
        tariff = replace(tariff_factory(subject), **changes)
        evidence = normalize_subscription(
            subject,
            step1_settings(),
            user=user_factory(),
            agreement=agreement_factory(),
            tariff=tariff,
            subscription=point,
        )
        assert evidence.commercial == CommercialProof.INCOMPLETE and not evidence.complete
        assert evidence.financial is None
        evidence = normalize_subscription(
            subject,
            step1_settings(),
            user=user_factory(),
            agreement=agreement_factory(),
            tariff=tariff,
            subscription=point.model_copy(update={"current_blocking": 1}),
        )
        assert evidence.identity == IdentityProof.INCOMPLETE and evidence.financial is None


@pytest.mark.parametrize(
    "field,value",
    [
        ("payment_type", 1),
        ("balance_blocks", 0),
        ("dynamic_rent", 1),
        ("dynamic_rent_unblock_type", 1),
        ("demo_period_length", 1),
        ("proportional_rent", 1),
        ("currency_id", 2),
    ],
)
def test_billing_subscription_reconciliation_unsupported_policy(field: str, value: int) -> None:
    subject = subject_factory()
    tariff = tariff_factory(subject)
    tariff = replace(tariff, value=tariff.value.model_copy(update={field: value}))
    evidence = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff,
        subscription=subscription_factory(),
    )
    assert evidence.commercial == CommercialProof.MISMATCH


@pytest.mark.parametrize(
    "start,cycle_start,cycle_end,end,complete",
    [
        ("2026-10-01 12:00:00", "2026-10-01 00:00:00", "2026-11-01 00:00:00", "2026-11-01 00:00:00", False),
        ("2026-10-01 00:00:00", "2026-10-01 00:00:00", "2026-11-01 12:00:00", "2026-11-01 00:00:00", False),
        ("2026-10-01 12:00:00", "2026-10-01 12:00:00", "2026-10-01 14:00:00", "2026-10-01 14:00:00", True),
        ("2026-10-01", "2026-10-01 12:00:00", "2026-11-01 00:00:00", "2026-11-02", False),
        ("2026-09-30", "2026-10-01 12:00:00", "2026-11-01 00:00:00", "2026-11-02", True),
        ("2026-10-01", "2026-10-01", "2026-11-01", "2026-11-01", True),
    ],
)
def test_billing_subscription_reconciliation_preserves_calendar_precision(
    start: str, cycle_start: str, cycle_end: str, end: str, complete: bool
) -> None:
    subject = subject_factory()
    raw = subscription_factory().model_dump()
    raw.update(
        subscription_instance_start_date=start,
        subscription_instance_end_date=end,
        last_tariffication_period_start=cycle_start,
        last_tariffication_period_end=cycle_end,
    )
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff_factory(subject),
        subscription=Subscription.model_validate(raw),
    )
    assert proof.calendar_complete is complete and proof.complete is complete
    assert (proof.financial == "allowed") is complete
    assert proof.calendar["subscription_instance_start_date"] == start
    assert proof.calendar["last_tariffication_period_end"] == cycle_end
