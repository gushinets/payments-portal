"""Accepted quantities and zoned storage exercised through ordinary source apply."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.models import BillingStateObservation, ExternalSubscription, PurchasedAllowance
from apps.api.tests.test_paid_access_postgres import reconcile, effective

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("paid_scenario", ["legacy", "brief_decoder"], indirect=True)
async def test_paid_access_accepted_terms_are_the_only_quantity_source(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    await reconcile(paid_scenario, postgres_session_factory)
    revision, document = effective(postgres_session_factory)
    assert revision == 1 and len(document["grants"]) == 1
    if document["grants"][0]["product_id"] == "brief_decoder":
        assert [(item["metric_key"], item["unit"], item["quantity"]) for item in document["allowances"]] == [
            ("brief_decoder.test_analyses", "analysis", 300)
        ]
    else:
        assert document["allowances"] == []  # v1 has no invented technical history.


@pytest.mark.parametrize(
    "end",
    [None, "0000-00-00", "0000-00-00 00:00:00", "1970-01-01 00:00:00", "2030-03-01T12:00:00+03:00"],
)
async def test_paid_access_normalized_subscription_end_preserves_grant_and_audit(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session], end: str | None
) -> None:
    transport, _, _, subscription_id, _ = paid_scenario
    transport.subscriptions[0]["subscription_end_date"] = end
    await reconcile(paid_scenario, postgres_session_factory)
    revision, document = effective(postgres_session_factory)
    expected_end = datetime(2030, 3, 1, 9, tzinfo=UTC) if end and end.startswith("2030") else None
    grant_end = (expected_end - timedelta(seconds=10)).isoformat() if expected_end else None
    assert revision == 1 and document["grants"] == [{"product_id": "proposal_ai", "valid_until": grant_end}]
    assert document["allowances"][0]["quantity"] == 100
    await reconcile(paid_scenario, postgres_session_factory)
    assert effective(postgres_session_factory) == (revision, document)
    with postgres_session_factory() as db:
        subscription = db.get(ExternalSubscription, subscription_id)
        observation = db.get(BillingStateObservation, subscription.latest_observation_id)
        assert observation.evidence_document["calendar"]["subscription_end_date"] == end
        assert observation.evidence_document["access_end_at"] == (expected_end.isoformat() if expected_end else None)


@pytest.mark.parametrize("paid_scenario", ["timestamp"], indirect=True)
async def test_paid_access_zoned_fractional_bounds_freeze_in_utc(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    await reconcile(paid_scenario, postgres_session_factory)
    first = effective(postgres_session_factory)
    await reconcile(paid_scenario, postgres_session_factory)
    assert effective(postgres_session_factory) == first
    point = paid_scenario[0].subscriptions[0]
    for field in (
        "subscription_instance_start_date",
        "last_tariffication_period_start",
        "last_tariffication_period_end",
    ):
        point[field] = datetime.fromisoformat(point[field]).astimezone(UTC).isoformat().replace("+00:00", "Z")
    await reconcile(paid_scenario, postgres_session_factory)
    assert effective(postgres_session_factory) == first
    with postgres_session_factory() as db:
        row = db.scalar(select(PurchasedAllowance))
        source = datetime.fromisoformat("2026-10-31T12:34:56.123456+03:00")
        assert row.cycle_schema_version == "timestamp:v1"
        assert row.cycle_date_start is None and row.cycle_date_end is None
        assert row.period_start == source.astimezone(UTC) + timedelta(seconds=10)
        assert row.calendar_document["start"] == "2026-10-31T12:34:56.123456+03:00"


async def test_paid_access_shared_writer_records_source_of_local_reduction(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    from app.domains.billing.customers import lock_user
    from app.domains.billing.paid_access import commit_paid_state
    from app.models import BillingProductAccessScope, BillingStateObservation

    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    with factory() as db:
        user = lock_user(db, paid_scenario[4])
        scope = db.scalar(select(BillingProductAccessScope))
        source = scope.access_basis_observation_id
        scope.effective_access_until = datetime.now(UTC) - timedelta(seconds=1)
        cause = db.get(BillingStateObservation, source)
        assert commit_paid_state(db, user, cause, datetime.now(UTC)) == 2
        db.commit()
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    with factory() as db:
        audit = db.scalar(
            select(BillingStateObservation).where(
                BillingStateObservation.evidence_schema_version == "paid-access-reduction:v1"
            )
        )
        assert audit.resulting_access_revision == 2 and audit.basis_observation_id == source
