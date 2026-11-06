"""Stage 2: shared reconciliation commits source facts and paid state atomically."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
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
) -> AsyncIterator[Scenario]:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    factory = postgres_session_factory
    config = step1_settings(purchase_test_terms_enabled=True, paid_access_clock_skew_seconds=10)
    transport = setup_purchase(factory)
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
