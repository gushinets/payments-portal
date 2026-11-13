"""Stage 2: shared reconciliation commits source facts and paid state atomically."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import func, null, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import advance_purchase, confirm_purchase, review_purchase
from app.composition.reconciliation import reconcile_subscription
from app.composition.sources import SourceResources, source_resources
from app.core.settings import Settings
from app.domains.billing.reconciliation_contracts import ReconciliationResult
from app.integrations.lbx.errors import LbxUnavailable
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    BillingWorkItem,
    ExternalSubscription,
    ManualReviewCase,
    PaidAccessState,
    PurchasedAllowance,
)
from apps.api.tests.factories.purchase_terms import reviewed_meaning
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_step3_postgres import TOKEN, setup_purchase

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@dataclass(frozen=True)
class Scenario:
    factory: sessionmaker[Session]
    config: Settings
    transport: PurchaseTransport
    sources: SourceResources
    subscription_id: UUID


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def paid_source(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> AsyncIterator[Scenario]:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    factory = postgres_session_factory
    config = step1_settings(purchase_test_terms_enabled=True, paid_access_clock_skew_seconds=10)
    transport = setup_purchase(factory)
    period_kind = getattr(request, "param", None)
    if period_kind in {"calendar_month", "annual_calendar_month"}:
        transport.offer.replace("tariff", '"float_period":1', '"float_period":0')
    if period_kind == "annual_calendar_month":
        transport.offer.replace("periods", '"period_type":3', '"period_type":4')
        transport.offer.replace("prices", '"period_type":3', '"period_type":4')
        transport.period_type = 4
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, documents, terms = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
        purchase = await confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="paid-writer",
            meaning=reviewed_meaning("proposal_ai", link.mapping_revision_id, offer.fingerprint, documents, terms),
        )
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        with factory() as db:
            sub = db.scalar(select(ExternalSubscription))
            # Stage 2 consumes an existing primary. Selection belongs to stage 3.
            db.add(
                BillingProductAccessScope(
                    user_id=sub.user_id, product_id=sub.product_id, primary_subscription_id=sub.subscription_id
                )
            )
            subscription_id = sub.subscription_id
            db.commit()
        transport.subscriptions[0].update(
            state=2,
            subscription_start_date="2026-10-01",
            subscription_instance_start_date="2026-10-01",
            last_tariffication_period_start="2026-10-01",
            last_tariffication_period_end="2026-10-31",
        )
        yield Scenario(factory, config, transport, sources, subscription_id)


async def reconcile(scenario: Scenario, *, config: Settings | None = None) -> ReconciliationResult:
    return await reconcile_subscription(
        scenario.sources.require_lbx(),
        scenario.sources.billing,
        config or scenario.config,
        factory=scenario.factory,
        subscription_id=scenario.subscription_id,
    )


def persisted(factory: sessionmaker[Session]) -> tuple:
    """Compare committed semantics, evidence and queue after a failed transaction."""
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        scope = db.scalar(select(BillingProductAccessScope))
        state = db.scalar(select(PaidAccessState))
        outbox = db.scalar(select(AccessInvalidationOutbox))
        return (
            (
                sub.lifecycle_status,
                sub.financial_access_status,
                sub.commercial_access_status,
                sub.last_authoritative_read_at,
                sub.projection_valid_until,
                sub.latest_observation_id,
            ),
            (
                scope.primary_subscription_id,
                scope.effective_access_document,
                scope.effective_access_until,
                scope.access_basis_observation_id,
            ),
            (state.access_revision, state.effective_state_document) if state else None,
            (outbox.pending_revision, outbox.delivered_revision, outbox.attempt_count) if outbox else None,
            tuple(db.scalars(select(PurchasedAllowance.allowance_id).order_by(PurchasedAllowance.allowance_id))),
            db.scalar(select(func.count()).select_from(BillingStateObservation)),
            tuple(
                db.execute(
                    select(
                        BillingWorkItem.work_item_id, BillingWorkItem.next_attempt_at, BillingWorkItem.payload_document
                    ).order_by(BillingWorkItem.work_item_id)
                ).all()
            ),
        )


async def test_paid_writer_first_noop_empty_and_same_cycle_recovery(paid_source: Scenario) -> None:
    scenario = paid_source
    assert persisted(scenario.factory)[2:5] == (None, None, ())
    first = await reconcile(scenario)
    one = persisted(scenario.factory)
    assert one[2][0] == one[3][0] == 1
    assert one[2][1]["grants"] == [{"product_id": "proposal_ai", "valid_until": None}]
    assert one[2][1]["allowances"][0]["quantity"] == 100
    assert one[2][1]["allowances"][0]["period_end"] is None
    with scenario.factory() as db:
        assert db.get(BillingStateObservation, first.observation_id).resulting_access_revision == 1
        outbox = db.scalar(select(AccessInvalidationOutbox))
        outbox.attempt_count = 3
        outbox.last_error_classification = "unavailable"
        db.commit()
    noop = await reconcile(scenario)
    same = persisted(scenario.factory)
    assert same[2] == one[2] and same[4] == one[4]
    assert same[3] == (1, 0, 3)
    assert same[1][2] > one[1][2]  # A new positive read renews support, not semantic identity.
    with scenario.factory() as db:
        assert db.get(BillingStateObservation, noop.observation_id).resulting_access_revision is None
    scenario.transport.subscriptions[0]["current_blocking"] = 1
    negative = await reconcile(scenario)
    empty = persisted(scenario.factory)
    assert empty[2] == (2, {"grants": [], "allowances": []})
    assert empty[3] == (2, 0, 3) and empty[4] == one[4]
    assert empty[0][3:5] == same[0][3:5]
    with scenario.factory() as db:
        assert db.get(BillingStateObservation, negative.observation_id).resulting_access_revision == 2
    scenario.transport.subscriptions[0]["current_blocking"] = 0
    await reconcile(scenario)
    restored = persisted(scenario.factory)
    assert restored[2] == (3, one[2][1]) and restored[4] == one[4]


@pytest.mark.parametrize("negative", ["block", "ended_3_1", "closed_unavailable", "commercial", "identity"])
async def test_paid_writer_owned_negative_reduces_without_renewing_trust(
    paid_source: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    negative: str,
) -> None:
    scenario = paid_source
    await reconcile(scenario)
    before = persisted(scenario.factory)
    if negative == "block":
        scenario.transport.subscriptions[0]["current_blocking"] = 1
    elif negative == "ended_3_1":
        scenario.transport.subscriptions[0].update(state=3, current_blocking=1)
    elif negative == "closed_unavailable":
        scenario.transport.agreements[0]["close_date"] = "2026-11-05"

        async def unavailable(**kwargs: object) -> None:
            raise LbxUnavailable()

        monkeypatch.setattr(scenario.sources.require_lbx(), "get_subscription", unavailable)
        monkeypatch.setattr(scenario.sources.require_lbx(), "get_tariff", unavailable)
    elif negative == "commercial":
        scenario.transport.subscriptions[0]["total_price"] = 999
    else:
        scenario.transport.agreements[0]["user_id"] = 999
    result = await reconcile(scenario)
    after = persisted(scenario.factory)
    assert after[2] == (2, {"grants": [], "allowances": []})
    assert after[3][0] == 2 and after[0][3:5] == before[0][3:5]
    assert after[4] == before[4]
    with scenario.factory() as db:
        assert db.get(BillingStateObservation, result.observation_id).resulting_access_revision == 2
    if negative in {"ended_3_1", "closed_unavailable"}:
        assert after[0][:2] == ("ended", "blocked") and after[1][0] is None


@pytest.mark.parametrize("missing", ["services_price_drift", "policy", "owner"])
async def test_paid_writer_incomplete_proof_preserves_finite_support(
    paid_source: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    missing: str,
) -> None:
    scenario = paid_source
    await reconcile(scenario)
    before = persisted(scenario.factory)
    if missing == "services_price_drift":
        scenario.transport.subscriptions[0].pop("services")
        scenario.transport.subscriptions[0]["total_price"] = 999
    elif missing == "owner":
        scenario.transport.agreements[0].pop("user_id")
    else:

        async def unavailable(**kwargs: object) -> None:
            raise LbxUnavailable()

        monkeypatch.setattr(scenario.sources.require_lbx(), "get_tariff", unavailable)
    result = await reconcile(scenario)
    assert not result.proof.complete
    assert persisted(scenario.factory)[:5] == before[:5]
    with scenario.factory() as db:
        assert db.get(BillingStateObservation, result.observation_id).resulting_access_revision is None


@pytest.mark.parametrize("calendar", ["missing", "naive", "mixed", "contradictory"])
async def test_paid_writer_calendar_uncertainty_grants_product_without_allowance(
    paid_source: Scenario,
    calendar: str,
) -> None:
    scenario = paid_source
    point = scenario.transport.subscriptions[0]
    if calendar == "missing":
        point.pop("last_tariffication_period_end")
    elif calendar == "naive":
        point.update(
            subscription_instance_start_date="2026-10-01 12:34:56.123456",
            last_tariffication_period_start="2026-10-01 12:34:56.123456",
            last_tariffication_period_end="2026-11-01 12:34:56.123456",
        )
    elif calendar == "mixed":
        point["last_tariffication_period_end"] = "2026-11-01T12:34:56Z"
    else:
        point["last_tariffication_period_end"] = "2026-09-01"
    result = await reconcile(scenario)
    assert result.proof.complete and result.proof.financial == "allowed"
    state = persisted(scenario.factory)
    assert state[2] == (1, {"grants": [{"product_id": "proposal_ai", "valid_until": None}], "allowances": []})
    assert not state[4]


@pytest.mark.parametrize("end_kind", ["date", "naive", "zoned", "past"])
async def test_paid_writer_finite_end_requires_explicit_zone(paid_source: Scenario, end_kind: str) -> None:
    scenario = paid_source
    end = datetime.now(UTC) + timedelta(hours=-1 if end_kind == "past" else 1)
    text = (
        end.date().isoformat()
        if end_kind == "date"
        else end.replace(tzinfo=None).isoformat()
        if end_kind == "naive"
        else end.isoformat()
    )
    scenario.transport.subscriptions[0]["subscription_end_date"] = text
    result = await reconcile(scenario)
    state = persisted(scenario.factory)
    if end_kind == "past":
        assert state[2] is None and state[3] is None and not state[4]
    else:
        grant = state[2][1]["grants"][0]
        assert grant["valid_until"] == ((end - timedelta(seconds=10)).isoformat() if end_kind == "zoned" else None)
        with scenario.factory() as db:
            deadline = db.scalar(
                select(BillingWorkItem).where(BillingWorkItem.work_kind == "subscription_trust_expiry")
            )
            assert deadline.next_attempt_at == state[1][2]
            assert deadline.payload_document["access_basis_observation_id"] == str(result.observation_id)
    assert (result.proof.access_end_at is not None) == (end_kind in {"zoned", "past"})


@pytest.mark.parametrize("gate", ["clock", "primary", "production_metering"])
async def test_paid_writer_does_not_invent_prerequisites(paid_source: Scenario, gate: str) -> None:
    scenario = paid_source
    config = scenario.config
    if gate == "clock":
        config = config.model_copy(update={"paid_access_clock_skew_seconds": None})
    elif gate == "primary":
        with scenario.factory() as db:
            db.scalar(select(BillingProductAccessScope)).primary_subscription_id = None
            db.commit()
    else:
        config = config.model_copy(update={"app_env": "production"})
    await reconcile(scenario, config=config)
    state = persisted(scenario.factory)
    assert state[4] == ()
    if gate == "production_metering":
        assert state[2] == (1, {"grants": [{"product_id": "proposal_ai", "valid_until": None}], "allowances": []})
    else:
        assert state[2] is None and state[3] is None
    if gate == "primary":
        assert state[1][0] is None


@pytest.mark.parametrize("transition", ["first", "renewal", "negative"])
async def test_paid_writer_rollback_includes_facts_allowances_audit_outbox_and_deadline(
    paid_source: Scenario,
    monkeypatch: pytest.MonkeyPatch,
    transition: str,
) -> None:
    from app.domains.billing import paid_access

    scenario = paid_source
    existing = transition != "first"
    if existing:
        await reconcile(scenario)
        if transition == "renewal":
            scenario.transport.subscriptions[0].update(
                last_tariffication_period_start="2026-11-01", last_tariffication_period_end="2026-11-30"
            )
        else:
            scenario.transport.subscriptions[0]["current_blocking"] = 1
    before = persisted(scenario.factory)

    commit = paid_access.commit_paid_state

    def fail_after_flush(db: Session, *args: object, **kwargs: object) -> int:
        commit(db, *args, **kwargs)
        # Source facts, allowance, causal revision, outbox and deadline are flushed.
        state = db.scalar(select(PaidAccessState))
        assert state.access_revision == (2 if existing else 1)
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == (2 if transition == "renewal" else 1)
        raise RuntimeError("injected failure after paid writes")

    monkeypatch.setattr(paid_access, "commit_paid_state", fail_after_flush)
    monkeypatch.setattr("app.domains.billing.reconciliation.commit_paid_state", fail_after_flush)
    with pytest.raises(RuntimeError, match="injected failure"):
        await reconcile(scenario)
    assert persisted(scenario.factory) == before


async def test_paid_writer_stale_active_cannot_restore_committed_negative(paid_source: Scenario) -> None:
    from app.domains.billing.contracts import BillingRefused
    from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation
    from app.integrations.lbx.reconciliation import read_subscription_proof

    scenario = paid_source
    await reconcile(scenario)
    subject = claim_reconciliation(scenario.factory, scenario.config, scenario.subscription_id, io_timeout_seconds=60)
    async with scenario.sources.billing.operation() as budget:
        active = await read_subscription_proof(scenario.sources.require_lbx(), subject, scenario.config, budget=budget)
    assert active.complete and active.financial == "allowed"
    with scenario.factory() as db:
        db.get(ExternalSubscription, scenario.subscription_id).reconciliation_lease_expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        db.commit()
    scenario.transport.subscriptions[0]["current_blocking"] = 1
    await reconcile(scenario)
    negative = persisted(scenario.factory)
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        apply_reconciliation(scenario.factory, subject, active, clock_skew_seconds=10)
    assert persisted(scenario.factory) == negative
    assert negative[2] == (2, {"grants": [], "allowances": []})


@pytest.mark.parametrize(
    "paid_source,activation,offset",
    [
        ("annual_calendar_month", "2026-11-11T12:34:56+03:00", "+03:00"),
        ("annual_calendar_month", "2026-11-11T12:34:56-04:00", "-04:00"),
        ("annual_calendar_month", "2026-11-01T00:30:00+03:00", "+03:00"),
        ("annual_calendar_month", "2026-11-30T23:30:00-04:00", "-04:00"),
        ("annual_calendar_month", "2026-11-01T00:00:00+03:00", "+03:00"),
        ("annual_calendar_month", "2026-11-11", None),
        ("calendar_month", "2026-11-11T12:34:56+03:00", "+03:00"),
    ],
    indirect=["paid_source"],
)
async def test_paid_writer_first_calendar_cycle_through_http_and_annual_acceptance(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch, activation: str, offset: str | None
) -> None:
    from app.infrastructure.queries import billing_reconciliation
    from app.integrations.lbx import reconciliation as integration

    scenario = paid_source
    annual = scenario.transport.period_type == 4
    clock = {"now": datetime(2026, 12 if activation.startswith("2026-11-30") else 11, 30, 12, tzinfo=UTC)}
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock["now"])
    monkeypatch.setattr(integration, "utc_now", lambda: clock["now"])
    start = f"2026-11-01T00:00:00{offset}" if offset else "2026-11-01"
    end = (f"2027-11-01T00:00:00{offset}" if annual else f"2026-12-01T00:00:00{offset}") if offset else "2027-10-31"
    point = scenario.transport.subscriptions[0]
    point.update(
        subscription_start_date=activation,
        subscription_instance_start_date=activation,
        last_tariffication_period_start=start,
        last_tariffication_period_end=end,
    )
    first = await reconcile(scenario)
    period = first.subject.purchase.accepted.offer.period
    assert (period.unit, period.length, period.anchor) == ("year" if annual else "month", 1, "calendar_month")
    assert first.subject.purchase.accepted.technical_terms.offer.quantity == 100
    assert first.subject.established_calendar is None
    assert first.proof.complete and first.proof.calendar_complete and first.proof.cycle is not None
    precision = "timestamp" if offset else "date"
    assert first.proof.cycle.precision == precision
    assert first.proof.cycle.anchor == start
    before = persisted(scenario.factory)
    assert len(before[2][1]["allowances"]) == 1
    with scenario.factory() as db:
        frozen = db.execute(select(PurchasedAllowance.__table__)).one()
        frozen_outbox = db.execute(select(AccessInvalidationOutbox.__table__)).one()
        assert frozen.quantity == 100 and frozen.provider_cycle_key == f"{precision}:{start}:{end}"
        if offset:
            assert frozen.period_start == datetime.fromisoformat(start) + timedelta(seconds=10)
            assert frozen.period_end == datetime.fromisoformat(end) - timedelta(seconds=10)
        else:
            assert frozen.period_start is None and frozen.period_end is None
            assert frozen.provider_cycle_start is None and frozen.provider_cycle_end is None

    # Each reconciliation reclaims in fresh sessions. Equivalent UTC spellings
    # must use the issued frame even when activation crosses a month in UTC.
    fields = (
        "subscription_start_date",
        "subscription_instance_start_date",
        "last_tariffication_period_start",
        "last_tariffication_period_end",
    )
    if offset:
        for field in fields:
            point[field] = datetime.fromisoformat(point[field]).astimezone(UTC).isoformat().replace("+00:00", "Z")
    clock["now"] += timedelta(minutes=1)
    same = await reconcile(scenario)
    assert same.subject.established_calendar == first.proof.cycle
    assert same.proof.cycle.anchor == start
    after = persisted(scenario.factory)
    assert after[2:5] == before[2:5]
    assert after[0][3] > before[0][3] and after[0][5] != before[0][5]
    with scenario.factory() as db:
        assert db.execute(select(PurchasedAllowance.__table__)).one() == frozen
        assert db.execute(select(AccessInvalidationOutbox.__table__)).one() == frozen_outbox
        observation = db.get(BillingStateObservation, same.observation_id)
        assert observation.resulting_access_revision is None
        assert all(observation.evidence_document["calendar"][field] == point[field] for field in fields)

    next_start = end if offset else "2027-11-01"
    next_end = (
        (f"2028-11-01T00:00:00{offset}" if annual else f"2027-01-01T00:00:00{offset}") if offset else "2028-10-31"
    )
    clock["now"] = datetime(2027 if annual else 2026, 11 if annual else 12, 12, tzinfo=UTC)
    point.update(last_tariffication_period_start=next_start, last_tariffication_period_end=next_end)
    if offset:
        for field in fields:
            point[field] = datetime.fromisoformat(point[field]).astimezone(UTC).isoformat().replace("+00:00", "Z")
    later = await reconcile(scenario)
    assert later.subject.established_calendar == first.proof.cycle
    assert later.proof.cycle.anchor == start
    with scenario.factory() as db:
        rows = db.execute(select(PurchasedAllowance.__table__).order_by(PurchasedAllowance.provider_cycle_key)).all()
        assert len(rows) == 2 and rows[0] == frozen
        assert rows[1].allowance_id != frozen.allowance_id and rows[1].quantity == frozen.quantity
        assert rows[1].calendar_document["anchor"] == start
        assert rows[1].provider_cycle_key == f"{precision}:{next_start}:{next_end}"
    await reconcile(scenario)
    with scenario.factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 2


@pytest.mark.parametrize("paid_source", ["annual_calendar_month"], indirect=True)
@pytest.mark.parametrize("change", ["boundary", "duration", "phase", "naive_dates"])
async def test_paid_writer_first_annual_calendar_conflicts_never_rewrite_history(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    from app.infrastructure.queries import billing_reconciliation
    from app.integrations.lbx import reconciliation as integration

    scenario = paid_source
    clock = {"now": datetime(2026, 11, 30, 12, tzinfo=UTC)}
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock["now"])
    monkeypatch.setattr(integration, "utc_now", lambda: clock["now"])
    point = scenario.transport.subscriptions[0]
    point.update(
        subscription_start_date="2026-11-11T12:34:56+03:00",
        subscription_instance_start_date="2026-11-11T12:34:56+03:00",
        last_tariffication_period_start="2026-11-01T00:00:00+03:00",
        last_tariffication_period_end="2027-11-01T00:00:00+03:00",
    )
    first = await reconcile(scenario)
    with scenario.factory() as db:
        frozen = db.execute(select(PurchasedAllowance.__table__)).one()
    if change == "boundary":
        point["last_tariffication_period_start"] = "2026-11-02T00:00:00+03:00"
    elif change == "duration":
        point["last_tariffication_period_end"] = "2028-11-01T00:00:00+03:00"
    elif change == "phase":
        point.update(
            last_tariffication_period_start="2027-01-01T00:00:00+03:00",
            last_tariffication_period_end="2028-01-01T00:00:00+03:00",
        )
    else:
        point.update(
            subscription_start_date="2026-11-11T12:34:56",
            subscription_instance_start_date="2026-11-11T12:34:56",
            last_tariffication_period_start="2026-11-01",
            last_tariffication_period_end="2027-10-31",
        )
    clock["now"] += timedelta(minutes=1)
    result = await reconcile(scenario)
    assert result.subject.established_calendar == first.proof.cycle
    assert result.proof.complete and result.proof.financial == "allowed"
    if change in {"boundary", "naive_dates"}:
        assert not result.proof.calendar_complete and result.proof.cycle is None
    else:
        assert result.proof.calendar_complete and result.proof.cycle is not None
    assert persisted(scenario.factory)[2][1]["allowances"] == []
    with scenario.factory() as db:
        assert db.execute(select(PurchasedAllowance.__table__)).one() == frozen
        review = db.scalar(select(ManualReviewCase).where(ManualReviewCase.scope_kind == "subscription_metric"))
        assert review.reason_code == "allowance_cycle_conflict" and review.case_state == "open"


@pytest.mark.parametrize("paid_source", ["annual_calendar_month"], indirect=True)
@pytest.mark.parametrize("activation", ["2026-10-11T12:34:56", "2026-11-11T12:34:56"])
async def test_paid_writer_first_naive_activation_with_dates_never_acquires_utc_bounds(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch, activation: str
) -> None:
    from app.infrastructure.queries import billing_reconciliation
    from app.integrations.lbx import reconciliation as integration

    now = datetime(2026, 11, 30, 12, tzinfo=UTC)
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: now)
    monkeypatch.setattr(integration, "utc_now", lambda: now)
    paid_source.transport.subscriptions[0].update(
        subscription_start_date=activation,
        subscription_instance_start_date=activation,
        last_tariffication_period_start="2026-11-01",
        last_tariffication_period_end="2027-10-31",
    )
    result = await reconcile(paid_source)
    assert result.subject.established_calendar is None
    assert result.proof.complete and result.proof.financial == "allowed"
    assert result.proof.cycle is None or result.proof.cycle.precision == "unresolved"
    assert persisted(paid_source.factory)[2][1]["allowances"] == []
    with paid_source.factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0


@pytest.mark.parametrize("paid_source", ["calendar_month"], indirect=True)
@pytest.mark.parametrize(
    "activation,offset,reread_utc",
    [
        ("2026-10-01T00:30:00+03:00", "+03:00", True),
        ("2026-10-31T23:30:00-04:00", "-04:00", True),
        ("2026-10-15T12:34:56.123456+03:00", "+03:00", True),
        ("2026-10-15T12:34:56.123456-04:00", "-04:00", True),
        ("2026-10-01T00:30:00+03:00", "+03:00", False),
        ("2026-10-15T12:00:00Z", "+00:00", True),
    ],
)
async def test_paid_writer_calendar_frame_survives_equivalent_source_reread(
    paid_source: Scenario, activation: str, offset: str, reread_utc: bool
) -> None:
    scenario = paid_source
    point = scenario.transport.subscriptions[0]
    point.update(
        subscription_start_date=activation,
        subscription_instance_start_date=activation,
        last_tariffication_period_start=f"2026-11-01T00:00:00{offset}",
        last_tariffication_period_end=f"2026-12-01T00:00:00{offset}",
    )
    first = await reconcile(scenario)
    assert first.proof.complete and first.proof.cycle.precision == "timestamp"
    assert first.subject.established_calendar is None
    before = persisted(scenario.factory)
    assert len(before[2][1]["allowances"]) == 1
    with scenario.factory() as db:
        frozen = db.execute(select(PurchasedAllowance.__table__)).one()
        frozen_outbox = db.execute(select(AccessInvalidationOutbox.__table__)).one()
        assert frozen.quantity == 100
    fields = (
        "subscription_start_date",
        "subscription_instance_start_date",
        "last_tariffication_period_start",
        "last_tariffication_period_end",
    )
    if reread_utc:
        for field in fields:
            point[field] = datetime.fromisoformat(point[field]).astimezone(UTC).isoformat().replace("+00:00", "Z")
    repeated = await reconcile(scenario)
    after = persisted(scenario.factory)
    # A new observation may renew finite trust; semantic access and outbox stay fixed.
    assert after[2:5] == before[2:5]
    assert after[0][3] >= before[0][3] and after[0][5] != before[0][5]
    assert repeated.proof.cycle.anchor == first.proof.cycle.anchor
    assert repeated.subject.established_calendar == first.proof.cycle
    with scenario.factory() as db:
        assert db.execute(select(PurchasedAllowance.__table__)).one() == frozen
        assert db.execute(select(AccessInvalidationOutbox.__table__)).one() == frozen_outbox
        observation = db.get(BillingStateObservation, repeated.observation_id)
        assert observation.resulting_access_revision is None
        assert observation.evidence_document["cycle"] == repeated.proof.cycle.model_dump(mode="json")
        assert all(observation.evidence_document["calendar"][field] == point[field] for field in fields)

    # A proven next cycle creates one new ID and still retains the original frame.
    point.update(
        last_tariffication_period_start=f"2026-12-01T00:00:00{offset}",
        last_tariffication_period_end=f"2027-01-01T00:00:00{offset}",
    )
    if reread_utc:
        for field in fields:
            point[field] = datetime.fromisoformat(point[field]).astimezone(UTC).isoformat().replace("+00:00", "Z")
    later = await reconcile(scenario)
    assert later.proof.cycle.anchor == first.proof.cycle.anchor
    with scenario.factory() as db:
        rows = list(db.scalars(select(PurchasedAllowance).order_by(PurchasedAllowance.created_at)))
        assert len(rows) == 2 and rows[0].allowance_id != rows[1].allowance_id
        assert rows[1].quantity == frozen.quantity
        assert rows[1].calendar_document["anchor"] == frozen.calendar_document["anchor"]
        assert rows[1].provider_cycle_key == f"timestamp:2026-12-01T00:00:00{offset}:2027-01-01T00:00:00{offset}"
        assert (
            db.execute(
                select(PurchasedAllowance.__table__).where(PurchasedAllowance.allowance_id == frozen.allowance_id)
            ).one()
            == frozen
        )


@pytest.mark.parametrize("paid_source", ["calendar_month"], indirect=True)
@pytest.mark.parametrize("offset", ["+03:00", "-04:00"])
@pytest.mark.parametrize("change", ["activation_month", "cycle_start", "cycle_end", "naive", "mixed"])
async def test_paid_writer_established_frame_does_not_hide_calendar_changes(
    paid_source: Scenario, offset: str, change: str
) -> None:
    scenario = paid_source
    point = scenario.transport.subscriptions[0]
    point.update(
        subscription_start_date=f"2026-10-15T12:00:00{offset}",
        subscription_instance_start_date=f"2026-10-15T12:00:00{offset}",
        last_tariffication_period_start=f"2026-11-01T00:00:00{offset}",
        last_tariffication_period_end=f"2026-12-01T00:00:00{offset}",
    )
    first = await reconcile(scenario)
    with scenario.factory() as db:
        frozen = db.execute(select(PurchasedAllowance.__table__)).one()
    if change == "activation_month":
        point["subscription_start_date"] = f"2026-09-15T12:00:00{offset}"
    elif change == "naive":
        point["subscription_start_date"] = "2026-10-15T12:00:00"
    elif change == "mixed":
        point["last_tariffication_period_end"] = "2026-11-30"
    else:
        field = "last_tariffication_period_start" if change == "cycle_start" else "last_tariffication_period_end"
        point[field] = (datetime.fromisoformat(point[field]) + timedelta(hours=1)).isoformat()
    result = await reconcile(scenario)
    assert result.subject.established_calendar == first.proof.cycle
    assert result.proof.complete and result.proof.financial == "allowed"
    if change == "naive":
        assert not result.proof.calendar_complete and result.proof.cycle is None
    elif change == "mixed":
        assert result.proof.cycle.precision == "unresolved"
    elif change == "activation_month":
        assert result.proof.cycle.anchor == f"2026-09-01T00:00:00{offset}"
    assert persisted(scenario.factory)[2][1]["allowances"] == []
    with scenario.factory() as db:
        assert db.execute(select(PurchasedAllowance.__table__)).one() == frozen
        review = db.scalar(select(ManualReviewCase).where(ManualReviewCase.scope_kind == "subscription_metric"))
        assert review.reason_code == "allowance_cycle_conflict" and review.case_state == "open"


@pytest.mark.parametrize("paid_source", ["calendar_month"], indirect=True)
@pytest.mark.parametrize("history_kind", ["other_subscription", "other_component", "other_metric", "legacy"])
async def test_paid_writer_uses_only_exact_supported_calendar_history(paid_source: Scenario, history_kind: str) -> None:
    from app.integrations.lbx.calendar import normalize_calendar

    scenario = paid_source
    # A foreign +03:00 history must not change the initial UTC calendar frame.
    calendar = normalize_calendar(
        {
            "subscription_start_date": "2026-10-01T00:30:00+03:00",
            "last_tariffication_period_start": "2026-11-01T00:00:00+03:00",
            "last_tariffication_period_end": "2026-12-01T00:00:00+03:00",
        },
        "calendar_month",
    )
    with scenario.factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        history_subscription_id = sub.subscription_id
        if history_kind == "other_subscription":
            other = ExternalSubscription(
                external_billing_account_id=sub.external_billing_account_id,
                customer_id=sub.customer_id,
                user_id=sub.user_id,
                product_id=sub.product_id,
                external_subscription_id="999",
                external_agreement_id="998",
                lifecycle_status=sub.lifecycle_status,
                financial_access_status=sub.financial_access_status,
                commercial_access_status=sub.commercial_access_status,
                last_authoritative_read_at=sub.last_authoritative_read_at,
                projection_valid_until=sub.projection_valid_until,
            )
            db.add(other)
            db.flush()
            history_subscription_id = other.subscription_id
        # Synthetic retained history, with real normalized source-calendar evidence.
        db.add(
            PurchasedAllowance(
                allowance_id=uuid4(),
                subscription_id=history_subscription_id,
                product_id=sub.product_id,
                source_component_id="1002" if history_kind == "other_component" else "1001",
                metric_key="other_metric" if history_kind == "other_metric" else "proposal_ai.test_generations",
                quantity=100,
                provider_cycle_key="retained-history",
                cycle_schema_version="legacy-utc:v1" if history_kind == "legacy" else "timestamp:v1",
                calendar_document=null() if history_kind == "legacy" else calendar.model_dump(mode="json"),
                terms_document=null() if history_kind == "legacy" else {},
                unit=None if history_kind == "legacy" else "generation",
                provider_cycle_start=None if history_kind == "legacy" else datetime.fromisoformat(calendar.start),
                provider_cycle_end=None if history_kind == "legacy" else datetime.fromisoformat(calendar.end),
                period_start=datetime.fromisoformat(calendar.start) + timedelta(seconds=10),
                period_end=datetime.fromisoformat(calendar.end) - timedelta(seconds=10),
            )
        )
        db.commit()
        retained = db.execute(select(PurchasedAllowance.__table__)).one()
    scenario.transport.subscriptions[0].update(
        subscription_start_date="2026-09-30T21:30:00Z",
        subscription_instance_start_date="2026-09-30T21:30:00Z",
        last_tariffication_period_start="2026-11-01T00:00:00Z",
        last_tariffication_period_end="2026-12-01T00:00:00Z",
    )
    result = await reconcile(scenario)
    assert result.subject.established_calendar is None
    assert result.proof.cycle.anchor == "2026-09-01T00:00:00+00:00"
    state = persisted(scenario.factory)[2][1]
    assert len(state["allowances"]) == (0 if history_kind == "legacy" else 1)
    with scenario.factory() as db:
        assert (
            db.execute(
                select(PurchasedAllowance.__table__).where(PurchasedAllowance.allowance_id == retained.allowance_id)
            ).one()
            == retained
        )
