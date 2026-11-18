"""Frozen accepted allowances on PostgreSQL, without paid reconciliation wiring."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domains.billing.paid_allowances import materialize_allowance
from app.domains.billing.paid_cycles import CalendarEvidence
from app.domains.billing.reconciliation import claim_reconciliation
from app.models import AccessInvalidationOutbox, ExternalSubscription, PaidAccessState, PurchasedAllowance
from apps.api.tests.factories.paid_access import AcceptedSubscription
from apps.api.tests.support.any709_step1 import step1_settings

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def calendar() -> CalendarEvidence:
    return CalendarEvidence(precision="date", start="2026-10-31", end="2026-11-29", anchor="2026-01-31")


@pytest.mark.parametrize("paid_terms_scenario", ["legacy", "proposal_ai", "brief_decoder"], indirect=True)
async def test_paid_access_accepted_terms_are_the_only_quantity_source(
    paid_terms_scenario: AcceptedSubscription, postgres_session_factory: sessionmaker[Session]
) -> None:
    scenario = paid_terms_scenario
    with postgres_session_factory() as db:
        subscription = db.get(ExternalSubscription, scenario.subscription_id)
        allowance = materialize_allowance(db, subscription, scenario.accepted, calendar(), skew_seconds=10)
        db.commit()
    with postgres_session_factory() as db:
        if scenario.accepted.technical_terms is None:
            assert scenario.accepted.schema_version == "accepted-purchase:v1"
            assert allowance is None
            assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0
        else:
            quantity = 300 if scenario.accepted.meaning.product_id == "brief_decoder" else 100
            assert allowance.quantity == quantity
            assert allowance.product_id == scenario.accepted.meaning.product_id
            assert allowance.period_start is None and allowance.period_end is None
            row = db.scalar(select(PurchasedAllowance))
            assert row.quantity == quantity and row.terms_document[
                "technical_terms"
            ] == scenario.accepted.technical_terms.model_dump(mode="json")
        # Stage 1 does not connect allowance issuance to source apply or grants.
        for model in (PaidAccessState, AccessInvalidationOutbox):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    subject = claim_reconciliation(
        postgres_session_factory, step1_settings(), scenario.subscription_id, io_timeout_seconds=60
    )
    assert subject.established_calendar == (calendar() if scenario.accepted.technical_terms is not None else None)


@pytest.mark.parametrize("paid_terms_scenario", ["proposal_ai"], indirect=True)
async def test_paid_access_cycles_keep_frozen_ids_and_do_not_backfill(
    paid_terms_scenario: AcceptedSubscription, postgres_session_factory: sessionmaker[Session]
) -> None:
    scenario = paid_terms_scenario
    with postgres_session_factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        first = materialize_allowance(db, sub, scenario.accepted, calendar(), skew_seconds=10)
        db.commit()
    with postgres_session_factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        same = materialize_allowance(db, sub, scenario.accepted, calendar(), skew_seconds=20)
        assert same == first
        ambiguous = calendar().model_copy(update={"anchor": "2026-02-28"})
        assert materialize_allowance(db, sub, scenario.accepted, ambiguous, skew_seconds=10) is None
        assert materialize_allowance(db, sub, scenario.accepted, calendar(), skew_seconds=10) == first
        later_cycle = CalendarEvidence(precision="date", start="2027-03-31", end="2027-04-29", anchor=calendar().anchor)
        later = materialize_allowance(db, sub, scenario.accepted, later_cycle, skew_seconds=10)
        assert later.allowance_id != first.allowance_id and later.quantity == first.quantity
        assert materialize_allowance(db, sub, scenario.accepted, later_cycle, skew_seconds=20) == later
        db.commit()
    with postgres_session_factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 2


@pytest.mark.parametrize("paid_terms_scenario", ["proposal_ai"], indirect=True)
async def test_paid_access_zoned_fractional_bounds_freeze_in_utc(
    paid_terms_scenario: AcceptedSubscription, postgres_session_factory: sessionmaker[Session]
) -> None:
    scenario = paid_terms_scenario
    cycle = CalendarEvidence(
        precision="timestamp",
        start="2026-10-31T12:34:56.123456+03:00",
        end="2026-11-30T12:34:56.123456+03:00",
        anchor="2026-01-31T12:34:56.123456+03:00",
    )
    with postgres_session_factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        first = materialize_allowance(db, sub, scenario.accepted, cycle, skew_seconds=10)
        db.commit()
    equivalent = cycle.model_copy(
        update={
            field: datetime.fromisoformat(getattr(cycle, field)).astimezone(UTC).isoformat().replace("+00:00", "Z")
            for field in ("start", "end", "anchor")
        }
    )
    with postgres_session_factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        assert materialize_allowance(db, sub, scenario.accepted, equivalent, skew_seconds=20) == first
        row = db.scalar(select(PurchasedAllowance))
        assert row.cycle_schema_version == "timestamp:v1" and row.cycle_date_start is None
        assert row.period_start.isoformat() == "2026-10-31T09:35:06.123456+00:00"
        assert row.calendar_document["start"] == cycle.start
        assert row.quantity == 100


@pytest.mark.parametrize("paid_terms_scenario", ["proposal_ai"], indirect=True)
@pytest.mark.parametrize("offset", [None, "+03:00"])
@pytest.mark.parametrize(
    "start,end,later_end,length",
    [
        ("2026-11-01", "2027-11-01", "2028-11-01", 1),
        ("2027-01-01", "2028-01-01", "2029-01-01", 1),
        ("2023-11-01", "2024-11-01", "2025-11-01", 1),
        ("2023-11-01", "2025-11-01", "2027-11-01", 2),
    ],
)
async def test_paid_access_annual_calendar_allowance_history_keeps_frozen_identity(
    paid_terms_scenario: AcceptedSubscription,
    postgres_session_factory: sessionmaker[Session],
    start: str,
    end: str,
    later_end: str,
    length: int,
    offset: str | None,
) -> None:
    scenario = paid_terms_scenario
    accepted = scenario.accepted.model_copy(
        update={
            "offer": replace(
                scenario.accepted.offer,
                period=replace(scenario.accepted.offer.period, unit="year", length=length, anchor="calendar_month"),
            )
        }
    )
    original_start = start

    def evidence(start: str, end: str) -> CalendarEvidence:
        return CalendarEvidence(
            precision="timestamp" if offset else "date",
            start=f"{start}T00:00:00{offset}" if offset else start,
            end=f"{end}T00:00:00{offset}" if offset else (date.fromisoformat(end) - timedelta(days=1)).isoformat(),
            anchor=f"{original_start}T00:00:00{offset}" if offset else original_start,
        )

    cycle = evidence(start, end)
    with postgres_session_factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        first = materialize_allowance(db, sub, accepted, cycle, skew_seconds=10)
        assert first is not None and first.quantity == 100
        db.commit()
        frozen = db.execute(select(PurchasedAllowance.__table__)).one()
        assert frozen.provider_cycle_key == f"{cycle.precision}:{cycle.start}:{cycle.end}"
        assert frozen.calendar_document == cycle.model_dump(mode="json")
        if offset:
            assert (
                first.period_start
                == (datetime.fromisoformat(cycle.start).astimezone(UTC) + timedelta(seconds=10)).isoformat()
            )
            assert (
                first.period_end
                == (datetime.fromisoformat(cycle.end).astimezone(UTC) - timedelta(seconds=10)).isoformat()
            )
        else:
            assert frozen.cycle_date_start == date.fromisoformat(cycle.start)
            assert frozen.cycle_date_end == date.fromisoformat(cycle.end)
            assert first.period_start is None and first.period_end is None
    with postgres_session_factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        same = materialize_allowance(db, sub, accepted, cycle, skew_seconds=20)
        assert same == first
        assert db.execute(select(PurchasedAllowance.__table__)).one() == frozen
        later_cycle = evidence(end, later_end)
        changed_phase = later_cycle.model_copy(update={"anchor": later_cycle.start})
        assert materialize_allowance(db, sub, accepted, changed_phase, skew_seconds=10) is None
        later = materialize_allowance(db, sub, accepted, later_cycle, skew_seconds=10)
        assert later is not None and later.allowance_id != first.allowance_id and later.quantity == first.quantity
        assert later.cycle.anchor == first.cycle.anchor
        db.commit()
    with postgres_session_factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        assert materialize_allowance(db, sub, accepted, later_cycle, skew_seconds=20) == later
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 2
        assert (
            db.execute(
                select(PurchasedAllowance.__table__).where(PurchasedAllowance.allowance_id == frozen.allowance_id)
            ).one()
            == frozen
        )
