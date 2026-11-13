"""Provider-neutral policy and calendar proofs, without mocked persistence."""

from dataclasses import replace
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from app.domains.billing.paid_cycles import CalendarEvidence, CycleKind, classify_cycle
from app.domains.billing.paid_policy import (
    CandidateConclusion as C,
    PaidDecision,
    PrimaryCandidate,
    first_primary,
    paid_decision,
)
from app.domains.billing.paid_contracts import EffectiveState, canonical_state
from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    IdentityProof,
    SubscriptionCandidateSubject,
    SubscriptionProof,
)
from app.domains.catalog.commercial_offer import CommercialPeriod
from apps.api.tests.factories.reconciliation import subject_factory
from apps.api.tests.support.any709_step1 import step1_settings


def period(unit: str = "month", length: int = 1, anchor: str = "instance_start") -> CommercialPeriod:
    return CommercialPeriod(unit, length, anchor, date(2026, 1, 1), None)


def calendar(start: str, end: str, anchor: str | None, precision: str = "date") -> CalendarEvidence:
    return CalendarEvidence(start=start, end=end, anchor=anchor, precision=precision)


@pytest.mark.parametrize(
    "start,end,anchor,unit,length",
    [
        ("2026-01-31", "2026-02-27", "2026-01-31", "month", 1),
        ("2024-02-29", "2025-02-27", "2024-02-29", "year", 1),
        ("2026-10-31", "2026-10-31", "2026-10-31", "day", 1),
        ("2026-10-01", "2026-10-14", "2026-10-01", "week", 2),
    ],
)
def test_paid_access_first_calendar_cycles(start: str, end: str, anchor: str, unit: str, length: int) -> None:
    value = calendar(start, end, anchor)
    assert classify_cycle(value, period(unit, length)).kind == CycleKind.FIRST
    assert classify_cycle(value, period(unit, length), first=value, latest=value).kind == CycleKind.SAME


@pytest.mark.parametrize("later,end", [("2026-03-31", "2026-04-29"), ("2026-07-31", "2026-08-30")])
def test_paid_access_skipped_months_use_original_anchor(later: str, end: str) -> None:
    first = calendar("2026-01-31", "2026-02-27", "2026-01-31")
    latest = calendar("2026-02-28", "2026-03-30", first.anchor)
    assert (
        classify_cycle(calendar(later, end, first.anchor), period(), first=first, latest=latest).kind == CycleKind.LATER
    )


@pytest.mark.parametrize(
    "current",
    [
        calendar("2026-02-28", "2026-03-27", "2026-02-28"),  # anchor edit
        calendar("2026-01-31", "2026-03-01", "2026-01-31"),  # recalculation
        calendar("2026-01-01", "2026-01-30", "2026-01-31"),  # reversal
        calendar("2026-02-27", "2026-03-30", "2026-01-31"),  # overlap
        calendar("2026-03-31T00:00:00", "2026-04-30T00:00:00", "2026-01-31T00:00:00", "unresolved"),
        calendar("2026-03-31", "2026-04-29", None),
    ],
)
def test_paid_access_ambiguous_cycles_never_refill(current: CalendarEvidence) -> None:
    first = calendar("2026-01-31", "2026-02-27", "2026-01-31")
    assert classify_cycle(current, period(), first=first, latest=first).kind == CycleKind.AMBIGUOUS


def test_paid_access_timestamp_precision_and_leap_anchor() -> None:
    value = calendar(
        "2026-01-31T12:34:56.123456+03:00",
        "2026-02-28T12:34:56.123456+03:00",
        "2026-01-31T12:34:56.123456+03:00",
        "timestamp",
    )
    assert classify_cycle(value, period()).kind == CycleKind.FIRST
    first = calendar("2024-02-29", "2025-02-27", "2024-02-29")
    later = calendar("2028-02-29", "2029-02-27", first.anchor)
    assert classify_cycle(later, period("year"), first=first, latest=first).kind == CycleKind.LATER
    with pytest.raises(ValidationError):
        calendar("2026-01-01", "2026-01-31", "2026-01-01", "UTC_GUESSED")


@pytest.mark.parametrize(
    "candidates,complete,expected",
    [
        ((), True, False),
        ((("own", "eligible"),), True, True),
        ((("other", "eligible"),), True, False),
        ((("own", "eligible"), ("other", "eligible")), True, False),
        ((("own", "eligible"), ("hidden", "incomplete")), True, False),
        ((("own", "eligible"),), False, False),
        ((("own", "ineligible"),), True, False),
    ],
)
def test_paid_access_first_primary(candidates: tuple, complete: bool, expected: bool) -> None:
    assert (
        first_primary("own", tuple(PrimaryCandidate(key, C(state)) for key, state in candidates), complete=complete)
        == expected
    )


@pytest.mark.parametrize(
    "changes,review,expected",
    [
        ({}, False, PaidDecision.GRANT),
        ({"complete": False, "commercial": CommercialProof.INCOMPLETE}, False, PaidDecision.KEEP),
        ({"identity": IdentityProof.INCOMPLETE}, False, PaidDecision.KEEP),
        ({"identity": IdentityProof.CONFLICT}, False, PaidDecision.DENY),
        (
            {"financial": "blocked", "commercial": CommercialProof.INCOMPLETE, "complete": False},
            False,
            PaidDecision.DENY,
        ),
        ({"lifecycle": "ended", "complete": False}, False, PaidDecision.DENY),
        ({"commercial": CommercialProof.MISMATCH}, False, PaidDecision.DENY),
        ({}, True, PaidDecision.DENY),
    ],
)
def test_paid_access_normalized_decisions(changes: dict, review: bool, expected: PaidDecision) -> None:
    now = subject_factory().claimed_at
    proof = SubscriptionProof(
        now, now, IdentityProof.MATCH, CommercialProof.MATCH, "active", "allowed", {}, True, True, (), ()
    )
    assert paid_decision(replace(proof, **changes), review=review) == expected


def test_paid_access_duplicate_metric_does_not_remove_independent_metrics_or_grants() -> None:
    from app.domains.billing.paid_contracts import EffectiveAllowance, PaidGrant

    cycle = calendar("2026-10-01", "2026-10-31", "2026-10-01")
    allowance = EffectiveAllowance(
        allowance_id="one",
        product_id="proposal_ai",
        metric_key="proposal_ai.test_generations",
        unit="generation",
        quantity=100,
        cycle=cycle,
    )
    independent = allowance.model_copy(
        update={
            "allowance_id": "other",
            "product_id": "brief_decoder",
            "metric_key": "brief_decoder.test_analyses",
            "quantity": 300,
            "unit": "analysis",
        }
    )
    state = canonical_state(
        [
            EffectiveState(
                grants=(PaidGrant(product_id="proposal_ai"), PaidGrant(product_id="brief_decoder")),
                allowances=(allowance, allowance.model_copy(update={"allowance_id": "duplicate"}), independent),
            )
        ]
    )
    assert {grant.product_id for grant in state.grants} == {"proposal_ai", "brief_decoder"}
    assert state.allowances == (independent,)


def test_paid_access_equivalent_timestamp_spelling_preserves_established_cycle() -> None:
    first = calendar(
        "2026-01-01T00:30:00.123456+03:00",
        "2026-02-01T00:30:00.123456+03:00",
        "2026-01-01T00:30:00.123456+03:00",
        "timestamp",
    )
    equivalent = calendar(
        "2025-12-31T21:30:00.123456Z", "2026-01-31T21:30:00.123456Z", "2025-12-31T21:30:00.123456Z", "timestamp"
    )
    original = classify_cycle(first, period())
    recovered = classify_cycle(equivalent, period(), first=first, latest=first)
    assert recovered.kind == CycleKind.SAME and recovered.key == original.key


@pytest.mark.parametrize("budget", [0, -1, 300, 301])
def test_paid_access_clock_budget_has_no_default_and_rejects_invalid(budget: int) -> None:
    assert step1_settings().paid_access_clock_skew_seconds is None
    with pytest.raises(ValidationError):
        step1_settings(paid_access_clock_skew_seconds=budget)
    assert canonical_state([EffectiveState()]) == EffectiveState()


@pytest.mark.parametrize(
    "start,end,anchor,expected",
    [
        ("2026-10-31", "2026-10-31", "2026-10-31", "date"),
        (
            "2026-10-31T12:34:56.123456+03:00",
            "2026-11-30T12:34:56.123456+03:00",
            "2026-10-31T12:34:56.123456+03:00",
            "timestamp",
        ),
        ("2026-10-31 12:34:56.123456", "2026-11-30 12:34:56.123456", "2026-10-31 12:34:56.123456", "unresolved"),
        ("2026-10-31", "2026-11-30T12:34:56Z", "2026-10-31", "unresolved"),
    ],
)
def test_paid_access_integration_calendar_is_lossless(start: str, end: str, anchor: str, expected: str) -> None:
    from app.integrations.lbx.calendar import normalize_calendar
    from apps.api.tests.factories.reconciliation import subscription_factory
    from app.integrations.lbx.financial import Subscription

    raw = subscription_factory().model_dump()
    raw.update(
        last_tariffication_period_start=start,
        last_tariffication_period_end=end,
        subscription_instance_start_date=anchor,
    )
    point = Subscription.model_validate(raw)
    normalized = normalize_calendar(
        {
            "last_tariffication_period_start": point.last_tariffication_period_start,
            "last_tariffication_period_end": point.last_tariffication_period_end,
            "subscription_instance_start_date": point.subscription_instance_start_date,
        },
        "instance_start",
    )
    assert normalized.precision == expected and (normalized.start, normalized.end, normalized.anchor) == (
        start,
        end,
        anchor,
    )
    with pytest.raises(ValidationError):
        Subscription.model_validate({**raw, "last_tariffication_period_start": "2026-01-01T00:00:00.123456789Z"})


@pytest.mark.parametrize(
    "anchor_kind,subscription_start,instance_start,expected",
    [
        ("first_instance_start", "2026-10-15", "2026-10-20", "2026-10-15"),
        ("instance_start", "2026-10-15", "2026-10-20", "2026-10-20"),
        ("calendar_month", "2026-10-15", "2026-10-20", "2026-10-01"),
    ],
)
def test_paid_access_calendar_anchor_keeps_provider_meaning(
    anchor_kind: str,
    subscription_start: str,
    instance_start: str,
    expected: str,
) -> None:
    from app.integrations.lbx.calendar import normalize_calendar

    normalized = normalize_calendar(
        {
            "subscription_start_date": subscription_start,
            "subscription_instance_start_date": instance_start,
            "last_tariffication_period_start": "2026-10-01",
            "last_tariffication_period_end": "2026-10-31",
        },
        anchor_kind,
    )
    assert normalized.anchor == expected


@pytest.mark.parametrize("offset", ["+03:00", "-04:00"])
@pytest.mark.parametrize("bound", [False, True])
def test_calendar_month_zoned_activation_normalizes_to_calendar_boundary(offset: str, bound: bool) -> None:
    from apps.api.tests.factories.reconciliation import (
        agreement_factory,
        subscription_factory,
        tariff_factory,
        user_factory,
    )
    from app.integrations.lbx.reconciliation import normalize_subscription

    subject = subject_factory()
    monthly = period(anchor="calendar_month")
    accepted = subject.purchase.accepted.model_copy(
        update={"offer": replace(subject.purchase.accepted.offer, period=monthly)}
    )
    subject = replace(subject, purchase=replace(subject.purchase, accepted=accepted))
    if not bound:
        subject = SubscriptionCandidateSubject(
            subject.purchase,
            subject.customer,
            subject.agreement_id,
            subject.agreement_key,
            subject.provider_subscription_id,
        )
    tariff = tariff_factory(subject)
    proof = normalize_subscription(
        subject,
        step1_settings(),
        user=user_factory(),
        agreement=agreement_factory(),
        tariff=replace(tariff, value=tariff.value.model_copy(update={"float_period": 0})),
        subscription=subscription_factory().model_copy(
            update={
                "subscription_start_date": f"2026-10-15T12:34:56.123456{offset}",
                "last_tariffication_period_start": f"2026-11-01T00:00:00{offset}",
                "last_tariffication_period_end": f"2026-12-01T00:00:00{offset}",
            }
        ),
    )
    assert proof.complete and proof.financial == "allowed" and proof.calendar_complete
    assert proof.cycle.anchor == f"2026-10-01T00:00:00{offset}"
    assert classify_cycle(proof.cycle, monthly).kind == CycleKind.FIRST
    assert classify_cycle(proof.cycle, monthly, first=proof.cycle, latest=proof.cycle).kind == CycleKind.SAME
    following = proof.cycle.model_copy(
        update={
            "start": f"2026-12-01T00:00:00{offset}",
            "end": f"2027-01-01T00:00:00{offset}",
        }
    )
    assert classify_cycle(following, monthly, first=proof.cycle, latest=proof.cycle).kind == CycleKind.LATER


@pytest.mark.parametrize("offset", [None, "+03:00", "-04:00"])
@pytest.mark.parametrize(
    "start,end,later_start,later_end,length",
    [
        ("2026-11-01", "2027-11-01", "2027-11-01", "2028-11-01", 1),
        ("2027-01-01", "2028-01-01", "2028-01-01", "2029-01-01", 1),
        ("2023-11-01", "2024-11-01", "2024-11-01", "2025-11-01", 1),
        ("2023-11-01", "2025-11-01", "2025-11-01", "2027-11-01", 2),
    ],
)
def test_calendar_month_annual_cycles_keep_activation_phase(
    start: str, end: str, later_start: str, later_end: str, length: int, offset: str | None
) -> None:
    from app.integrations.lbx.calendar import normalize_calendar

    annual = period("year", length, "calendar_month")
    activation = f"{start[:8]}11" + (f"T12:34:56.123456{offset}" if offset else "")

    def evidence(start: str, end: str) -> CalendarEvidence:
        normalized = normalize_calendar(
            {
                "subscription_start_date": activation,
                "last_tariffication_period_start": f"{start}T00:00:00{offset}" if offset else start,
                "last_tariffication_period_end": (
                    f"{end}T00:00:00{offset}" if offset else (date.fromisoformat(end) - timedelta(days=1)).isoformat()
                ),
            },
            annual.anchor,
        )
        assert normalized is not None
        return normalized

    first = evidence(start, end)
    assert first.anchor == (f"{start}T00:00:00{offset}" if offset else start)
    initial = classify_cycle(first, annual)
    assert initial.kind == CycleKind.FIRST
    assert initial.key == f"{first.precision}:{first.start}:{first.end}"
    repeated = classify_cycle(evidence(start, end), annual, first=first, latest=first)
    assert repeated.kind == CycleKind.SAME and repeated.key == initial.key
    later = evidence(later_start, later_end)
    assert later.anchor == first.anchor
    following = classify_cycle(later, annual, first=first, latest=first)
    assert following.kind == CycleKind.LATER and following.key != initial.key


@pytest.mark.parametrize("offset", [None, "+03:00"])
@pytest.mark.parametrize(
    "start,end,anchor,length",
    [
        ("2027-01-01", "2028-01-01", "2026-10-01", 1),  # October activation is not a January phase.
        ("2026-11-02", "2027-11-02", "2026-11-02", 1),  # Calendar anchor must be the first day.
        ("2026-11-01", "2027-10-01", "2026-11-01", 1),  # Too short.
        ("2026-11-01", "2028-11-01", "2026-11-01", 1),  # Two years cannot satisfy one year.
        ("2026-11-01", "2027-11-01", "2026-11-01", 2),  # Accepted multi-year length still applies.
    ],
)
def test_calendar_month_annual_cycles_reject_inconsistent_evidence(
    start: str, end: str, anchor: str, length: int, offset: str | None
) -> None:
    if offset:
        current = calendar(*(f"{value}T00:00:00{offset}" for value in (start, end, anchor)), precision="timestamp")
    else:
        current = calendar(start, (date.fromisoformat(end) - timedelta(days=1)).isoformat(), anchor)
    assert classify_cycle(current, period("year", length, "calendar_month")).kind == CycleKind.AMBIGUOUS


@pytest.mark.parametrize("precision", ["date", "timestamp"])
def test_calendar_month_annual_history_rejects_changed_phase_and_end_precision(precision: str) -> None:
    suffix = "T00:00:00+03:00" if precision == "timestamp" else ""
    first = calendar(
        f"2026-11-01{suffix}",
        f"2027-11-01{suffix}" if suffix else "2027-10-31",
        f"2026-11-01{suffix}",
        precision,
    )
    annual = period("year", anchor="calendar_month")
    changed = calendar(
        f"2028-01-01{suffix}",
        f"2029-01-01{suffix}" if suffix else "2028-12-31",
        f"2027-01-01{suffix}",
        precision,
    )
    assert classify_cycle(changed, annual).kind == CycleKind.FIRST
    assert classify_cycle(changed, annual, first=first, latest=first).kind == CycleKind.AMBIGUOUS
    incorrect_end = first.model_copy(update={"end": f"2027-10-31{suffix}" if suffix else "2027-11-01"})
    assert classify_cycle(incorrect_end, annual).kind == CycleKind.AMBIGUOUS


@pytest.mark.parametrize(
    "activation,start,end",
    [
        ("2026-11-11T12:00:00", "2026-11-01", "2027-10-31"),
        ("2026-11-11T12:00:00", "2026-11-01T00:00:00", "2027-11-01T00:00:00"),
        ("2026-11-11T12:00:00+03:00", "2026-11-01", "2027-11-01T00:00:00+03:00"),
    ],
)
def test_calendar_month_annual_unresolved_precision_never_acquires_a_zone(
    activation: str, start: str, end: str
) -> None:
    from app.integrations.lbx.calendar import normalize_calendar

    current = normalize_calendar(
        {
            "subscription_start_date": activation,
            "last_tariffication_period_start": start,
            "last_tariffication_period_end": end,
        },
        "calendar_month",
    )
    assert current is not None and current.precision == "unresolved"
    assert classify_cycle(current, period("year", anchor="calendar_month")).kind == CycleKind.AMBIGUOUS


@pytest.mark.parametrize(
    "history",
    [
        None,
        calendar("2026-10-01", "2026-10-31", "2026-10-01"),
        calendar("2026-10-01T00:00:00", "2026-11-01T00:00:00", "2026-10-01T00:00:00", "unresolved"),
        calendar("2026-10-01T00:00:00+03:00", "2026-11-01T00:00:00+03:00", None, "timestamp"),
    ],
)
def test_calendar_month_without_proven_historical_offset_keeps_initial_frame(history: CalendarEvidence | None) -> None:
    from app.integrations.lbx.calendar import normalize_calendar

    result = normalize_calendar(
        {
            "subscription_start_date": "2026-09-30T21:30:00Z",
            "last_tariffication_period_start": "2026-10-01T00:00:00Z",
            "last_tariffication_period_end": "2026-11-01T00:00:00Z",
        },
        "calendar_month",
        established_calendar=history,
    )
    assert result.anchor == "2026-09-01T00:00:00+00:00"
    assert result.precision == "timestamp"


@pytest.mark.parametrize("anchor_kind", ["instance_start", "first_instance_start"])
def test_instance_anchors_do_not_use_established_calendar_offset(anchor_kind: str) -> None:
    from app.integrations.lbx.calendar import normalize_calendar

    result = normalize_calendar(
        {
            "subscription_start_date": "2026-09-30T21:30:00Z",
            "subscription_instance_start_date": "2026-10-31T21:30:00Z",
            "last_tariffication_period_start": "2026-10-31T21:30:00Z",
            "last_tariffication_period_end": "2026-11-30T21:30:00Z",
        },
        anchor_kind,
        established_calendar=calendar(
            "2026-10-01T00:00:00+03:00", "2026-11-01T00:00:00+03:00", "2026-10-01T00:00:00+03:00", "timestamp"
        ),
    )
    assert result.anchor == (
        "2026-09-30T21:30:00Z" if anchor_kind == "first_instance_start" else "2026-10-31T21:30:00Z"
    )


def test_paid_access_proof_document_serializes_lossless_cycle_and_finite_end() -> None:
    import json

    now = subject_factory().claimed_at
    cycle = calendar(
        "2026-10-01T12:34:56.123456Z", "2026-11-01T12:34:56.123456Z", "2026-10-01T12:34:56.123456Z", "timestamp"
    )
    proof = SubscriptionProof(
        now,
        now,
        IdentityProof.MATCH,
        CommercialProof.MATCH,
        "active",
        "allowed",
        {},
        True,
        True,
        (),
        (),
        cycle=cycle,
        access_end_at=now,
    )
    decoded = json.loads(json.dumps(proof.document()))
    assert decoded["cycle"] == cycle.model_dump(mode="json")
    assert decoded["access_end_at"] == now.isoformat()
