"""Frozen accepted allowances on PostgreSQL, without paid reconciliation wiring."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domains.billing.paid_allowances import materialize_allowance
from app.domains.billing.paid_cycles import CalendarEvidence
from app.models import AccessInvalidationOutbox, ExternalSubscription, PaidAccessState, PurchasedAllowance
from apps.api.tests.factories.paid_access import AcceptedSubscription

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
