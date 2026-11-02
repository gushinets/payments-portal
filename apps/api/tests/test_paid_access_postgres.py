"""Ordinary reconciliation with synthetic transports and real PostgreSQL writes."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.composition.reconciliation import reconcile_subscription
from app.core.settings import Settings
from app.domains.billing.customers import lock_user
from app.domains.billing.paid_access import commit_paid_state
from app.domains.billing.reconciliation import claim_reconciliation, apply_reconciliation
from app.domains.billing.contracts import BillingRefused
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    ExternalSubscription,
    ManualReviewCase,
    PaidAccessState,
    PurchasedAllowance,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)
from apps.api.tests.factories.paid_access import grant_document

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


async def reconcile(scenario: tuple, factory: sessionmaker[Session], config: Settings | None = None) -> UUID:
    _, sources, configuration, sub_id, _ = scenario
    return await reconcile_subscription(
        sources.require_lbx(), sources.billing, config or configuration, factory=factory, subscription_id=sub_id
    )


def effective(factory: sessionmaker[Session]) -> tuple[int, dict]:
    with factory() as db:
        state = db.scalar(select(PaidAccessState))
        return (
            (state.access_revision, state.effective_state_document) if state else (0, {"grants": [], "allowances": []})
        )


async def test_paid_access_ordinary_commit_same_cycle_restart_block_and_skipped_recovery(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, _, config, _, _ = paid_scenario
    factory = postgres_session_factory
    await reconcile(paid_scenario, factory, config.model_copy(update={"paid_access_clock_skew_seconds": None}))
    assert effective(factory)[0] == 0
    transport.requests.clear()
    first_cause = await reconcile(paid_scenario, factory)
    assert len(transport.requests) == 10
    revision, first = effective(factory)
    assert revision == 1 and first["grants"] == [{"product_id": "proposal_ai", "valid_until": None}]
    allowance = first["allowances"][0]
    assert allowance["quantity"] == 100 and allowance["unit"] == "generation"
    assert allowance["period_start"] is None and allowance["period_end"] is None
    transport.change_price()
    transport.requests.clear()
    await reconcile(
        paid_scenario,
        factory,
        config.model_copy(update={"purchase_test_terms_enabled": False, "paid_access_clock_skew_seconds": 20}),
    )
    assert effective(factory) == (1, first)
    assert len(transport.requests) == 4
    with factory() as db:
        scope = db.scalar(select(BillingProductAccessScope))
        sub = db.scalar(select(ExternalSubscription))
        assert scope.primary_subscription_id == sub.subscription_id
        assert sub.projection_valid_until - scope.effective_access_until == timedelta(seconds=20)
        outbox = db.scalar(select(AccessInvalidationOutbox))
        outbox.delivered_revision = 1
        outbox.attempt_count = 4
        outbox.last_error_classification = "synthetic-retained"
        db.commit()
    transport.subscriptions[0]["current_blocking"] = 1
    await reconcile(paid_scenario, factory)
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    transport.subscriptions[0]["current_blocking"] = 0
    await reconcile(paid_scenario, factory)
    assert effective(factory) == (3, first)
    transport.subscriptions[0].update(
        last_tariffication_period_start="2027-03-31", last_tariffication_period_end="2027-04-29"
    )
    await reconcile(paid_scenario, factory)
    assert (
        effective(factory)[0] == 4
        and effective(factory)[1]["allowances"][0]["allowance_id"] != allowance["allowance_id"]
    )
    with factory() as db:
        rows = list(db.scalars(select(PurchasedAllowance)))
        assert len(rows) == 2 and {row.quantity for row in rows} == {100}
        assert all(row.period_start is None and row.cycle_schema_version == "calendar:v1" for row in rows)
        assert db.get(BillingStateObservation, first_cause).resulting_access_revision == 1
        outbox = db.scalar(select(AccessInvalidationOutbox))
        assert (
            outbox.pending_revision,
            outbox.delivered_revision,
            outbox.attempt_count,
            outbox.last_error_classification,
        ) == (4, 1, 4, "synthetic-retained")
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillingStateObservation)
                .where(BillingStateObservation.evidence_schema_version == "target-product-discovery:v2")
            )
            == 1
        )


@pytest.mark.parametrize("change", ["anchor", "overlap", "naive", "missing", "mixed"])
async def test_paid_access_ambiguous_cycle_is_metric_local(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session], change: str
) -> None:
    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    transport = paid_scenario[0]
    updates = {
        "anchor": {"subscription_instance_start_date": "2026-10-31"},
        "overlap": {"last_tariffication_period_end": "2026-12-01"},
        "naive": {
            "last_tariffication_period_start": "2026-10-31 00:00:00",
            "last_tariffication_period_end": "2026-11-30 00:00:00",
        },
        "missing": {"last_tariffication_period_end": None},
        "mixed": {"last_tariffication_period_start": "2026-10-31 00:00:00"},
    }
    transport.subscriptions[0].update(updates[change])
    await reconcile(paid_scenario, factory)
    revision, document = effective(factory)
    assert revision == 2 and document["grants"] and document["allowances"] == []
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1
        assert (
            db.scalar(
                select(ManualReviewCase.scope_kind).where(ManualReviewCase.reason_code == "allowance_cycle_conflict")
            )
            == "subscription_metric"
        )


async def test_paid_access_unknown_preserves_original_deadline_and_stale_completion_refused(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    from app.integrations.lbx.reconciliation import read_subscription_proof

    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    transport, sources, config, sub_id, _ = paid_scenario
    before = effective(factory)
    with factory() as db:
        deadline = db.scalar(select(BillingProductAccessScope.effective_access_until))
    transport.subscriptions[0]["total_price"] = None
    await reconcile(paid_scenario, factory)
    assert effective(factory) == before
    with factory() as db:
        assert db.scalar(select(BillingProductAccessScope.effective_access_until)) == deadline
    subject = claim_reconciliation(factory, config, sub_id, io_timeout_seconds=10)
    async with sources.billing.operation() as budget:
        proof = await read_subscription_proof(sources.require_lbx(), subject, config, budget=budget)
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        apply_reconciliation(factory, replace(subject, fence=subject.fence + 1), proof, clock_skew_seconds=10)
    assert effective(factory) == before


@pytest.mark.parametrize("competitor", ["listed", "hidden", "unstable"])
async def test_paid_access_initial_discovery_requires_complete_union(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session], competitor: str
) -> None:
    factory = postgres_session_factory
    transport = paid_scenario[0]
    if competitor in {"listed", "unstable"}:
        transport.subscriptions.append({**transport.subscriptions[0], "subscription_id": 999, "agreement_id": 999})
        transport.agreements.append({**transport.agreements[0], "agreement_id": 999})
    else:
        with factory() as db:
            own = db.get(ExternalSubscription, paid_scenario[3])
            hidden = ExternalSubscription(
                customer_id=own.customer_id,
                user_id=own.user_id,
                product_id=own.product_id,
                external_billing_account_id=own.external_billing_account_id,
                external_subscription_id="999",
                external_agreement_id="999",
                lifecycle_status=Lifecycle.ACTIVE,
                financial_access_status=Financial.UNVERIFIED,
                commercial_access_status=own.commercial_access_status,
                last_authoritative_read_at=datetime.now(UTC),
                projection_valid_until=datetime.now(UTC),
                reconciliation_fencing_token=0,
            )
            db.add(hidden)
            db.commit()
    await reconcile(paid_scenario, factory)
    assert effective(factory)[0] == 0
    with factory() as db:
        assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) is None
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0


async def test_paid_access_terminal_primary_cleared_without_revival(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    await reconcile(paid_scenario, postgres_session_factory)
    paid_scenario[0].subscriptions[0]["state"] = 3
    await reconcile(paid_scenario, postgres_session_factory)
    assert effective(postgres_session_factory)[0] == 2
    with postgres_session_factory() as db:
        scope = db.scalar(select(BillingProductAccessScope))
        assert scope.primary_subscription_id is None and scope.primary_retired_at is not None
    paid_scenario[0].subscriptions[0]["state"] = 2
    await reconcile(paid_scenario, postgres_session_factory)
    assert effective(postgres_session_factory) == (2, {"grants": [], "allowances": []})


async def test_paid_access_atomic_rollback_crash_reopen_and_storage_guards(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    before = effective(factory)
    # An interrupted writer rolls back source state, revision, causal link and outbox.
    with pytest.raises(RuntimeError), factory() as db:
        user = lock_user(db, paid_scenario[4])
        scope = db.scalar(select(BillingProductAccessScope))
        scope.effective_access_document = None
        cause = db.scalar(select(BillingStateObservation).where(BillingStateObservation.resulting_access_revision == 1))
        assert commit_paid_state(db, user, cause, datetime.now(UTC)) == 2
        raise RuntimeError("synthetic crash before commit")
    assert effective(factory) == before
    statements = [
        "UPDATE paid_access_states SET access_revision=0",
        "UPDATE paid_access_states SET effective_state_document='{}'",
        "UPDATE paid_access_states SET access_revision=access_revision+2",
        "DELETE FROM paid_access_states",
        "UPDATE access_invalidation_outbox SET pending_revision=0",
        "UPDATE access_invalidation_outbox SET delivered_revision=-1",
        "DELETE FROM access_invalidation_outbox",
        "UPDATE billing_state_observations SET resulting_access_revision=0 WHERE resulting_access_revision IS NULL",
        "UPDATE purchased_allowances SET quantity=999",
        "UPDATE purchased_allowances SET cycle_date_start=cycle_date_start+1",
    ]
    for statement in statements:
        with pytest.raises(DatabaseError), factory() as db:
            db.execute(text(statement))
            db.commit()
    assert effective(factory) == before  # A new session after commit sees the same durable state.


async def test_paid_access_concurrent_products_and_causal_reuse(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    from threading import Barrier
    from app.domains.billing.paid_contracts import EffectiveState

    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    user_id = paid_scenario[4]
    with factory() as db:
        original = db.get(ExternalSubscription, paid_scenario[3])
        other = ExternalSubscription(
            customer_id=original.customer_id,
            user_id=user_id,
            product_id="brief_decoder",
            external_billing_account_id=original.external_billing_account_id,
            external_subscription_id="998",
            external_agreement_id="998",
            lifecycle_status=original.lifecycle_status,
            financial_access_status=original.financial_access_status,
            commercial_access_status=original.commercial_access_status,
            last_authoritative_read_at=original.last_authoritative_read_at,
            projection_valid_until=original.projection_valid_until,
        )
        db.add(other)
        db.flush()
        db.add(
            BillingProductAccessScope(
                user_id=user_id, product_id="brief_decoder", primary_subscription_id=other.subscription_id
            )
        )
        cause_id = db.scalar(
            select(BillingStateObservation.observation_id).where(BillingStateObservation.resulting_access_revision == 1)
        )
        db.commit()
    gate = Barrier(2)

    def update(product: str) -> int:
        gate.wait(timeout=5)
        with factory() as db:
            user = lock_user(db, user_id)
            scope = db.scalar(select(BillingProductAccessScope).where(BillingProductAccessScope.product_id == product))
            scope.effective_access_document = grant_document(product)
            scope.effective_access_until = datetime.now(UTC) + timedelta(hours=1)
            cause = db.get(BillingStateObservation, cause_id)
            revision = commit_paid_state(db, user, cause, datetime.now(UTC))
            db.commit()
            return revision

    with ThreadPoolExecutor(max_workers=2) as pool:
        revisions = list(pool.map(update, ("proposal_ai", "brief_decoder")))
    assert set(revisions) == {2, 3}
    revision, document = effective(factory)
    assert revision == 3 and {grant["product_id"] for grant in document["grants"]} == {"proposal_ai", "brief_decoder"}
    assert EffectiveState.model_validate(document).allowances == ()
    with factory() as db:
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == 3
        assert (
            len(
                list(
                    db.scalars(
                        select(BillingStateObservation).where(BillingStateObservation.basis_observation_id == cause_id)
                    )
                )
            )
            == 2
        )


async def test_paid_access_logical_identity_race_and_metric_local_duplicate(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    from threading import Barrier

    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    with factory() as db:
        original = db.scalar(select(PurchasedAllowance))
        values = {
            column.name: getattr(original, column.name)
            for column in PurchasedAllowance.__table__.columns
            if column.name not in {"allowance_id", "created_at"}
        }
    gate = Barrier(2)

    def insert(_: int) -> str:
        gate.wait(timeout=5)
        try:
            with factory() as db:
                db.add(PurchasedAllowance(**{**values, "source_component_id": "race-component"}))
                db.commit()
            return "inserted"
        except IntegrityError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(insert, (1, 2)))
    assert sorted(results) == ["duplicate", "inserted"]
    await reconcile(paid_scenario, factory)
    _, document = effective(factory)
    assert document["grants"] and document["allowances"] == []


async def test_paid_access_inventory_newcomer_preserves_primary(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    from app.domains.billing import background_recovery as recovery
    from app.domains.billing.work_contracts import WorkLane
    from app.jobs.billing import BillingWorker
    from apps.api.tests.test_billing_background_recovery_postgres import due

    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    transport, sources, config, sub_id, user_id = paid_scenario
    before = effective(factory)
    transport.subscriptions.append({**transport.subscriptions[0], "subscription_id": 999})
    recovery.repair_batch(factory, config)
    with factory() as db:
        customer_id = db.get(ExternalSubscription, sub_id).customer_id
    worker = BillingWorker(config, factory, sources.require_lbx())
    try:
        for _ in range(2):
            due(factory, recovery.INVENTORY, customer_id)
            transport.requests.clear()
            assert await worker.tick(WorkLane.NORMAL)
            assert sum(r.url.path.endswith("/subscriptions/567") for r in transport.requests) == 1
        assert effective(factory) == before
        with factory() as db:
            scope = db.scalar(select(BillingProductAccessScope))
            assert scope.primary_subscription_id == sub_id
            assert db.get(ExternalSubscription, sub_id).financial_access_status == Financial.ALLOWED
            assert (
                len(
                    list(
                        db.scalars(select(ManualReviewCase).where(ManualReviewCase.scope_kind == "product_competitor"))
                    )
                )
                == 1
            )
        transport.subscriptions[0]["current_blocking"] = 1
        await reconcile(paid_scenario, factory)
        assert effective(factory)[1] == {"grants": [], "allowances": []}
        due(factory, recovery.INVENTORY, customer_id)
        assert await worker.tick(WorkLane.NORMAL)
        transport.subscriptions[0]["current_blocking"] = 0
        await reconcile(paid_scenario, factory)
        assert effective(factory)[1] == before[1]
    finally:
        await worker.aclose()


async def test_paid_access_newer_negative_during_discovery_wins(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory = postgres_session_factory
    client = paid_scenario[1].require_lbx()
    original = client.get_subscription
    reads = 0

    from app.integrations.lbx.financial import Subscription
    from app.infrastructure.preflight import PreflightBudget

    async def changing(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        nonlocal reads
        point = await original(subscription_id=subscription_id, budget=budget)
        reads += 1
        return point.model_copy(update={"state": 3}) if reads >= 2 else point

    monkeypatch.setattr(client, "get_subscription", changing)
    await reconcile(paid_scenario, factory)
    assert effective(factory) == (0, {"grants": [], "allowances": []})
    with factory() as db:
        assert db.get(ExternalSubscription, paid_scenario[3]).lifecycle_status == Lifecycle.ENDED


@pytest.mark.parametrize("history", ["ended", "waiting", "unknown", "wrong_owner"])
async def test_paid_access_external_terminal_history(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session], history: str
) -> None:
    transport = paid_scenario[0]
    transport.agreements.append(
        {
            **transport.agreements[0],
            "agreement_id": 999,
            "agreement_number": "external-history",
            "user_id": 999 if history == "wrong_owner" else 345,
        }
    )
    transport.subscriptions.append(
        {
            **transport.subscriptions[0],
            "subscription_id": 999,
            "agreement_id": 999,
            "state": -2 if history == "waiting" else None if history == "unknown" else 3,
        }
    )
    await reconcile(paid_scenario, postgres_session_factory)
    revision, document = effective(postgres_session_factory)
    assert revision == (1 if history == "ended" else 0)
    assert len(document["allowances"]) == (1 if history == "ended" else 0)


async def test_paid_access_primary_cleared_during_ordinary_read_cannot_reselect(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.infrastructure.preflight import PreflightBudget
    from app.integrations.lbx.financial import Subscription

    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    client = paid_scenario[1].require_lbx()
    original = client.get_subscription

    async def clearing(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        point = await original(subscription_id=subscription_id, budget=budget)
        with factory() as db:
            lock_user(db, paid_scenario[4])
            db.scalar(select(BillingProductAccessScope)).primary_subscription_id = None
            db.commit()
        return point

    monkeypatch.setattr(client, "get_subscription", clearing)
    await reconcile(paid_scenario, factory)
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1
