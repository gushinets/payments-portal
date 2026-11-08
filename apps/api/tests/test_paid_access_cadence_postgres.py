"""Frozen allowance deadlines drive cadence without deriving access from time."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.reconciliation import reconcile_subscription
from app.domains.billing import background_recovery, work
from app.domains.billing.work_contracts import WorkLane
from app.domains.identity.services.auth import as_utc
from app.infrastructure.queries import billing_reconciliation
from app.integrations.lbx import reconciliation as integration
from app.models import BillingWorkItem, PurchasedAllowance
from apps.api.tests.factories.paid_runtime import timestamp_cycle
from apps.api.tests.factories.paid_runtime import effective, paid_scenario as paid_scenario, paid_source as paid_source

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def source_job(factory: sessionmaker[Session]) -> BillingWorkItem:
    with factory() as db:
        return db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)).one()


async def issue_timestamp(
    paid_scenario: tuple,
    factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    minutes: int,
) -> tuple[dict[str, datetime], datetime]:
    transport, sources, config, sub_id, _ = paid_scenario
    year = datetime.now(UTC).year + 1
    source_end = datetime(year, 11, 30, 9, 34, 56, 123456, tzinfo=UTC)
    effective_end = source_end - timedelta(seconds=config.paid_access_clock_skew_seconds)
    clock = {"now": effective_end - timedelta(minutes=minutes)}
    transport.subscriptions[0].update(timestamp_cycle(year))
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock["now"])
    monkeypatch.setattr(integration, "utc_now", lambda: clock["now"])
    claim = work.claim_work(factory, config, WorkLane.URGENT)
    assert claim is not None
    await reconcile_subscription(
        sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=sub_id, work_claim=claim
    )
    return clock, effective_end


@pytest.mark.parametrize("minutes,urgent", [(120, False), (35, False), (31, False), (30, True), (20, True)])
async def test_paid_allowance_cadence_and_entry_into_urgent_window(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    minutes: int,
    urgent: bool,
) -> None:
    factory = postgres_session_factory
    clock, end = await issue_timestamp(paid_scenario, factory, monkeypatch, minutes)
    row = source_job(factory)
    assert row.priority == int(urgent)
    gap = (as_utc(row.next_attempt_at) - clock["now"]).total_seconds()
    assert gap <= (work.URGENT_SECONDS if urgent else work.NORMAL_SECONDS)
    if not urgent:
        assert as_utc(row.next_attempt_at) <= end - work.URGENT_TRUST_WINDOW
    if minutes == 35:
        before = effective(factory)
        clock["now"] = end - work.URGENT_TRUST_WINDOW
        assert work.claim_work(factory, paid_scenario[2], WorkLane.NORMAL) is None
        assert work.claim_work(factory, paid_scenario[2], WorkLane.URGENT) is not None
        assert effective(factory) == before


@pytest.mark.parametrize("control", ["due", "not_yet_five_minutes", "live_lease"])
async def test_paid_allowance_promotes_existing_normal_queue_without_bypassing_lease_or_spacing(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    control: Literal["due", "not_yet_five_minutes", "live_lease"],
) -> None:
    factory = postgres_session_factory
    clock, _ = await issue_timestamp(paid_scenario, factory, monkeypatch, 20)
    row = source_job(factory)
    with factory() as db:
        queue = db.get(BillingWorkItem, row.work_item_id)
        queue.priority = 0
        queue.next_attempt_at = clock["now"] + timedelta(minutes=12)
        queue.last_attempt_started_at = clock["now"] - timedelta(minutes=4 if control == "not_yet_five_minutes" else 6)
        if control == "live_lease":
            queue.work_state = "running"
            queue.lease_owner = "live-owner"
            queue.lease_expires_at = clock["now"] + timedelta(minutes=1)
        db.commit()
    before = effective(factory)
    assert work.claim_work(factory, paid_scenario[2], WorkLane.NORMAL) is None
    claimed = work.claim_work(factory, paid_scenario[2], WorkLane.URGENT)
    assert (claimed is not None) == (control == "due")
    assert effective(factory) == before


async def test_calendar_only_allowance_does_not_acquire_utc_urgency(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    sources, config, sub_id = paid_scenario[1:4]
    claim = work.claim_work(factory, config, WorkLane.URGENT)
    assert claim is not None
    await reconcile_subscription(
        sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=sub_id, work_claim=claim
    )
    assert source_job(factory).priority == 0
    with factory() as db:
        allowance = db.scalars(select(PurchasedAllowance)).one()
        assert allowance.period_end is None and allowance.cycle_schema_version == "calendar:v1"


async def test_allowance_expiry_stays_urgent_until_proven_next_cycle_without_rewriting_history(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    clock, end = await issue_timestamp(paid_scenario, factory, monkeypatch, 20)
    before = effective(factory)[1]
    identity = before["allowances"][0]["allowance_id"]
    clock["now"] = end + timedelta(seconds=1)
    for _ in range(5):
        claim = work.claim_work(factory, paid_scenario[2], WorkLane.LOCAL)
        assert claim is not None
        if claim.kind == work.EXPIRY:
            work.expire_trust(factory, claim)
            break
        background_recovery.apply_deadline(factory, claim)
    assert effective(factory) == (2, {"grants": before["grants"], "allowances": []})
    clock["now"] += timedelta(minutes=5)
    claim = work.claim_work(factory, paid_scenario[2], WorkLane.URGENT)
    assert claim is not None and claim.kind == work.RECONCILIATION
    await reconcile_subscription(
        paid_scenario[1].require_lbx(),
        paid_scenario[1].billing,
        paid_scenario[2],
        factory=factory,
        subscription_id=paid_scenario[3],
        work_claim=claim,
    )
    row = source_job(factory)
    assert row.priority == 1 and as_utc(row.next_attempt_at) <= clock["now"] + timedelta(seconds=work.URGENT_SECONDS)
    assert effective(factory) == (2, {"grants": before["grants"], "allowances": []})
    with factory() as db:
        allowance = db.scalars(select(PurchasedAllowance)).one()
        assert str(allowance.allowance_id) == identity and allowance.quantity == 100
    source_end = end + timedelta(seconds=paid_scenario[2].paid_access_clock_skew_seconds)
    paid_scenario[0].subscriptions[0].update(
        last_tariffication_period_start=source_end.isoformat(),
        last_tariffication_period_end=source_end.replace(month=12, day=31).isoformat(),
    )
    clock["now"] = as_utc(row.next_attempt_at)
    claim = work.claim_work(factory, paid_scenario[2], WorkLane.URGENT)
    assert claim is not None
    await reconcile_subscription(
        paid_scenario[1].require_lbx(),
        paid_scenario[1].billing,
        paid_scenario[2],
        factory=factory,
        subscription_id=paid_scenario[3],
        work_claim=claim,
    )
    revision, document = effective(factory)
    assert revision == 3 and document["grants"] == before["grants"]
    assert len(document["allowances"]) == 1 and document["allowances"][0]["allowance_id"] != identity
    assert document["allowances"][0]["quantity"] == 100 and source_job(factory).priority == 0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 2
        assert db.get(PurchasedAllowance, UUID(identity)).quantity == 100


async def test_paid_deadline_repair_restores_earlier_metering_due_with_unchanged_payload(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    _, end = await issue_timestamp(paid_scenario, factory, monkeypatch, 20)
    with factory() as db:
        job = db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY)).one()
        payload = job.payload_document
        job.next_attempt_at = end + timedelta(hours=1)
        db.commit()
    assert work.repair_paid_deadlines(factory, paid_scenario[2]) == 1
    with factory() as db:
        job = db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY)).one()
        assert as_utc(job.next_attempt_at) == end and job.payload_document == payload
    assert work.repair_paid_deadlines(factory, paid_scenario[2]) == 0
