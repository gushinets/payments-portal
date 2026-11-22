"""Observed mixed LBX calendar formats, with synthetic ownership and terms."""

from dataclasses import replace
from datetime import date

import pytest

from app.domains.billing.paid_cycles import CalendarEvidence, CalendarPrecision, CycleKind, classify_cycle
from app.domains.billing.reconciliation_contracts import SubscriptionProof
from app.domains.catalog.commercial_offer import CommercialPeriod
from app.integrations.lbx.reconciliation import normalize_subscription
from apps.api.tests.factories.reconciliation import (
    agreement_factory,
    subject_factory,
    subscription_factory,
    tariff_factory,
    user_factory,
)
from apps.api.tests.support.any709_step1 import step1_settings


def normalized_proof(
    *,
    start: str | None = "2026-11-13",
    end: str | None = "2026-12-12",
    subscription_start: str | None = "2026-11-13 00:00:00",
    instance_start: str | None = "2026-11-13 00:00:00",
    subscription_end: str | None = None,
    instance_end: str | None = None,
    period: CommercialPeriod | None = None,
) -> SubscriptionProof:
    subject = subject_factory()
    if period is not None:
        accepted = subject.purchase.accepted.model_copy(
            update={"offer": replace(subject.purchase.accepted.offer, period=period)}
        )
        subject = replace(subject, purchase=replace(subject.purchase, accepted=accepted))
    period = subject.purchase.accepted.offer.period
    point = subscription_factory().model_copy(
        update={
            "period_type": {"day": 1, "week": 2, "month": 3, "year": 4}[period.unit],
            "period_length": period.length,
            "subscription_start_date": subscription_start,
            "subscription_end_date": subscription_end,
            "subscription_instance_start_date": instance_start,
            "subscription_instance_end_date": instance_end,
            "last_tariffication_period_start": start,
            "last_tariffication_period_end": end,
        }
    )
    tariff = tariff_factory(subject)
    tariff = replace(
        tariff,
        value=tariff.value.model_copy(
            update={
                "float_period": {"calendar_month": 0, "instance_start": 1, "first_instance_start": 2}[period.anchor]
            }
        ),
    )
    return normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=tariff,
        subscription=point,
    )


@pytest.mark.parametrize(
    "suffix",
    [" 00:00:00", "T00:00:00"]
    + [separator + "00:00:00." + "0" * digits for separator in (" ", "T") for digits in range(1, 7)],
)
def test_monthly_instance_midnight_is_calendar_evidence_without_rewriting_raw_fields(suffix: str) -> None:
    raw = "2026-11-13" + suffix
    proof = normalized_proof(subscription_start=raw, instance_start=raw)
    assert proof.complete and proof.financial == "allowed" and proof.calendar_complete
    assert proof.cycle == CalendarEvidence(
        precision=CalendarPrecision.DATE, start="2026-11-13", end="2026-12-12", anchor="2026-11-13"
    )
    assert proof.calendar["subscription_start_date"] == raw
    assert proof.calendar["subscription_instance_start_date"] == raw
    assert proof.document()["calendar"] == proof.calendar
    assert proof.access_end_at is None
    period = subject_factory().purchase.accepted.offer.period
    initial = classify_cycle(proof.cycle, period)
    assert initial.kind == CycleKind.FIRST and initial.key == "date:2026-11-13:2026-12-12"
    plain = normalized_proof(subscription_start="2026-11-13", instance_start="2026-11-13")
    repeated = classify_cycle(plain.cycle, period, first=proof.cycle, latest=proof.cycle)
    assert repeated.kind == CycleKind.SAME and repeated.key == initial.key


@pytest.mark.parametrize(
    "start,end",
    [
        ("2026-01-31", "2026-02-27"),
        ("2024-01-31", "2024-02-28"),
        ("2024-02-29", "2024-03-28"),
        ("1970-01-02", "1970-02-01"),
        ("1969-12-31", "1970-01-30"),
    ],
)
def test_monthly_instance_midnight_retains_month_end_and_leap_arithmetic(start: str, end: str) -> None:
    proof = normalized_proof(
        start=start, end=end, subscription_start=start + " 00:00:00", instance_start=start + " 00:00:00"
    )
    assert proof.calendar_complete
    assert classify_cycle(proof.cycle, subject_factory().purchase.accepted.offer.period).kind == CycleKind.FIRST


@pytest.mark.parametrize("field", ["subscription_start", "instance_start"])
@pytest.mark.parametrize("suffix", ["", " 00:00:00"])
@pytest.mark.parametrize("day,complete", [("2026-11-12", True), ("2026-11-13", True), ("2026-11-14", False)])
def test_monthly_instance_calendar_starts_cannot_follow_the_current_cycle(
    field: str, suffix: str, day: str, complete: bool
) -> None:
    proof = normalized_proof(**{field: day + suffix})
    assert proof.calendar_complete is complete
    if not complete:
        assert proof.cycle is None


@pytest.mark.parametrize(
    "unit,length,anchor,end",
    [
        ("day", 1, "instance_start", "2026-11-13"),
        ("week", 1, "instance_start", "2026-11-19"),
        ("year", 1, "instance_start", "2027-11-12"),
        ("month", 2, "instance_start", "2027-01-12"),
        ("month", 1, "first_instance_start", "2026-12-12"),
        ("month", 1, "calendar_month", "2026-11-30"),
    ],
)
def test_midnight_date_bridge_does_not_enable_other_period_profiles(
    unit: str, length: int, anchor: str, end: str
) -> None:
    period = CommercialPeriod(unit, length, anchor, date(2026, 1, 1), None)
    proof = normalized_proof(end=end, period=period)
    assert not proof.calendar_complete and proof.cycle is None


def test_daily_first_instance_midnight_proves_adjacent_days_without_an_instant() -> None:
    period = CommercialPeriod("day", 1, "first_instance_start", date(2026, 10, 1), None)
    # Date formatting from the live 043 response for tariff 31, period 4.
    raw_start = "2026-10-13 00:00:00"
    first = normalized_proof(
        start="2026-11-20", end="2026-11-20", subscription_start=raw_start, instance_start=raw_start, period=period
    )
    assert first.complete and first.calendar_complete and first.financial == "allowed"
    assert first.cycle == CalendarEvidence(
        precision=CalendarPrecision.DATE, start="2026-11-20", end="2026-11-20", anchor="2026-10-13"
    )
    assert first.calendar["subscription_start_date"] == raw_start
    assert first.access_end_at is None
    initial = classify_cycle(first.cycle, period)
    assert initial.kind == CycleKind.FIRST and initial.key == "date:2026-11-20:2026-11-20"

    renewed = normalized_proof(
        start="2026-11-21", end="2026-11-21", subscription_start=raw_start, instance_start=raw_start, period=period
    )
    assert renewed.calendar_complete
    later = classify_cycle(renewed.cycle, period, first=first.cycle, latest=first.cycle)
    assert later.kind == CycleKind.LATER and later.key == "date:2026-11-21:2026-11-21"


@pytest.mark.parametrize(
    "start,end,anchor,instance_start",
    [
        ("2026-11-20", "2026-11-20", "2026-11-21 00:00:00", "2026-11-20 00:00:00"),
        ("2026-11-20", "2026-11-20", "2026-11-20 00:00:00", "2026-11-21 00:00:00"),
        ("2026-11-20", "2026-11-20", "2026-11-20 00:00:01", "2026-11-20 00:00:00"),
        ("2026-11-20", "2026-11-20", "2026-11-20T00:00:00+03:00", "2026-11-20 00:00:00"),
        ("2026-11-20", "2026-11-21T00:00:00Z", "2026-11-20 00:00:00", "2026-11-20 00:00:00"),
        ("2026-11-20", "2026-11-20", "1970-01-01T00:00:00.000", "2026-11-20 00:00:00"),
    ],
)
def test_daily_first_instance_rejects_inconsistent_or_unproven_calendar(
    start: str, end: str, anchor: str, instance_start: str
) -> None:
    period = CommercialPeriod("day", 1, "first_instance_start", date(2026, 10, 1), None)
    proof = normalized_proof(
        start=start, end=end, subscription_start=anchor, instance_start=instance_start, period=period
    )
    assert classify_cycle(proof.cycle, period).kind == CycleKind.AMBIGUOUS


@pytest.mark.parametrize(
    "instance_start",
    [
        None,
        "1970-01-01 00:00:00",
        "2026-11-13 12:00:00",
        "2026-11-13 00:00:00.000001",
        "2026-11-13T00:00:00Z",
        "2026-11-13T00:00:00+03:00",
    ],
)
def test_monthly_instance_unproven_anchor_never_creates_a_cycle(instance_start: str | None) -> None:
    proof = normalized_proof(instance_start=instance_start)
    period = subject_factory().purchase.accepted.offer.period
    assert classify_cycle(proof.cycle, period).kind == CycleKind.AMBIGUOUS


@pytest.mark.parametrize(
    "sentinel",
    ["1970-01-01T00:00:00"]
    + ["1970-01-01" + separator + "00:00:00." + "0" * digits for separator in (" ", "T") for digits in range(1, 7)],
)
def test_epoch_sentinel_spelling_never_creates_monthly_cycle(sentinel: str) -> None:
    proof = normalized_proof(
        start="2026-11-01",
        end="2026-11-30",
        subscription_start="2026-11-01 00:00:00",
        instance_start=sentinel,
    )

    assert not proof.calendar_complete or proof.cycle is None
    assert classify_cycle(proof.cycle, subject_factory().purchase.accepted.offer.period).kind == CycleKind.AMBIGUOUS
    assert proof.calendar["subscription_instance_start_date"] == sentinel
    assert proof.document()["calendar"] == proof.calendar
    assert proof.access_end_at is None


@pytest.mark.parametrize("end", [None, "0000-00-00", "2026-11-12", "2026-02-30", "2026-12-13T00:00:00Z"])
def test_monthly_instance_missing_or_mixed_cycle_bounds_remain_incomplete(end: str | None) -> None:
    proof = normalized_proof(end=end)
    assert not proof.calendar_complete and proof.cycle is None


@pytest.mark.parametrize("field", ["subscription_end", "instance_end"])
@pytest.mark.parametrize("end", ["2026-11-13 00:00:00", "2026-12-12 00:00:00", "2026-12-12T00:00:00Z"])
def test_monthly_instance_bridge_does_not_relax_original_end_checks(field: str, end: str) -> None:
    proof = normalized_proof(**{field: end})
    assert not proof.calendar_complete and proof.cycle is None


def test_monthly_instance_reanchoring_cannot_reset_an_established_cycle() -> None:
    initial = normalized_proof()
    changed = normalized_proof(
        start="2026-12-14",
        end="2027-01-13",
        subscription_start="2026-11-13 00:00:00",
        instance_start="2026-12-14 00:00:00",
    )
    assert initial.calendar_complete and changed.calendar_complete
    period = subject_factory().purchase.accepted.offer.period
    assert classify_cycle(changed.cycle, period, first=initial.cycle, latest=initial.cycle).kind == CycleKind.AMBIGUOUS
