"""Disposable PostgreSQL, two competing handlers and synthetic LBX only."""

from __future__ import annotations

import asyncio
import copy
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import _observation
from app.composition.reconciliation import reconcile_subscription
from app.domains.billing import work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.work_contracts import WorkLane
from app.domains.catalog.link_publication import publish_product_link
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase
from app.integrations.lbx.financial import Subscription
from app.jobs.billing import BillingWorker
from app.models import (
    BillingWorkItem,
    ExternalSubscription,
    BillingStateObservation,
    BillingStateObservationKind,
    BillingProductAccessScope,
    PaidAccessState,
    PurchasedAllowance,
    AccessInvalidationOutbox,
    ExternalCreateOperationKind as Kind,
)
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN
from apps.api.tests.test_billing_subscription_reconciliation_postgres import scenario as scenario, activate
from apps.api.tests.factories.billing_worker import work_factory

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def jobs(factory: sessionmaker[Session], kind: str = work.RECONCILIATION) -> list[BillingWorkItem]:
    with factory() as db:
        return list(
            db.scalars(
                select(BillingWorkItem)
                .where(BillingWorkItem.work_kind == kind)
                .order_by(BillingWorkItem.scope_reference)
            )
        )


def subs(factory: sessionmaker[Session]) -> list[ExternalSubscription]:
    with factory() as db:
        return list(db.scalars(select(ExternalSubscription).order_by(ExternalSubscription.product_id)))


def historical_link(
    factory: sessionmaker[Session],
    template: Purchase,
    transport: object,
    product: str,
    number: int,
    *,
    uncertain_subscription: bool = False,
) -> Purchase:
    """Construct accepted historical fixtures via real local acceptance/bind paths.

    Historical eligibility does not consult today's Kernel enablement. The two
    enabled products and three disabled historical products share a supported tariff.
    No external CREATE is executed by this fixture.
    """
    config = step1_settings()
    linked = publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(product_id=product)),
        expected_previous_revision=0,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    )
    linked = linked.stored
    meaning = template.accepted.meaning.model_copy(
        update={"product_id": product, "revision_id": linked.mapping_revision_id}
    )
    purchase = service.pin_purchase(
        factory, config, TOKEN, product, meaning, linked, template.accepted.offer, template.accepted.documents
    )
    agreement_id, subscription_id = 456 + number, 567 + number
    for kind, provider_id in ((Kind.AGREEMENT, agreement_id), (Kind.SUBSCRIPTION, subscription_id)):
        op = next(op for op in purchase.operations if op.kind == kind)
        request = (
            {"user_id": 345, "agreement_number": op.key, "create_date": "2026-10-28"}
            if kind == Kind.AGREEMENT
            else {"agreement_id": agreement_id}
        )
        claimed = financial.claim_financial(factory, purchase, op, request, configuration=config, token=TOKEN)
        if kind == Kind.AGREEMENT:
            agreement = copy.deepcopy(transport.agreements[0])
            agreement.update(agreement_id=agreement_id, agreement_number=op.key)
            transport.agreements.append(agreement)
            financial.bind_financial(factory, purchase, claimed, provider_id)
        else:
            sub = copy.deepcopy(transport.subscriptions[0])
            sub.update(subscription_id=subscription_id, agreement_id=agreement_id, outer_id=op.key)
            transport.subscriptions.append(sub)
            observation = _observation(Subscription.model_validate(sub), purchase)
            if not uncertain_subscription:
                financial.bind_financial(factory, purchase, claimed, provider_id, observation=observation)
        purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    return purchase


async def test_billing_worker_enrolls_three_missing_batches_and_restart_preserves_schedules(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, _, purchase = scenario
    factory = postgres_session_factory
    for number, product in enumerate(
        ("brief_decoder", "acceptance_builder", "client_update_writer", "sales_script"), 1
    ):
        historical_link(factory, purchase, transport, product, number)
    assert len(jobs(factory)) == 5
    # A pre-Step-2 database has canonical subscriptions but no monitoring work.
    with factory() as db:
        db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        db.commit()
    config = step1_settings(billing_worker_scan_batch_size=2)
    assert work.enroll_batch(factory, config) == 2
    # Restart: no in-memory cursor is involved.
    assert work.enroll_batch(factory, config) == 2
    assert work.enroll_batch(factory, config) == 1
    assert work.enroll_batch(factory, config) == 0
    assert len(jobs(factory)) == 5
    future = datetime.now(UTC) + timedelta(minutes=12)
    with factory() as db:
        row = db.get(BillingWorkItem, jobs(factory)[0].work_item_id)
        row.next_attempt_at = future
        row.lease_owner = "expired-owner"
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        row.work_state = "running"
        row.enqueue_generation = 11
        db.commit()
    assert work.enroll_batch(factory, config) == 0
    saved = jobs(factory)[0]
    assert (saved.next_attempt_at, saved.lease_owner, saved.enqueue_generation) == (future, "expired-owner", 11)
    with factory() as db:
        row = db.get(BillingWorkItem, saved.work_item_id)
        row.work_state = "completed"
        row.lease_owner = row.lease_expires_at = None
        db.commit()
    assert work.enroll_batch(factory, config) == 1
    assert jobs(factory)[0].work_state == "pending"


async def test_billing_worker_two_products_link_hint_reconcile_and_restart(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    historical_link(factory, purchase, transport, "brief_decoder", 1)
    before = jobs(factory)
    assert len(before) == 2 and before[0].work_item_id != before[1].work_item_id
    assert all(row.next_attempt_at <= datetime.now(UTC) for row in before)
    for sub in subs(factory):
        with factory() as db:
            for _ in range(3):
                work.enroll_subscription(db, db.get(ExternalSubscription, sub.subscription_id), hint=True)
            db.commit()
    assert len(jobs(factory)) == 2 and all(row.enqueue_generation == 3 for row in jobs(factory))
    activate(transport)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    await worker.tick(WorkLane.URGENT)
    await worker.tick(WorkLane.URGENT)
    facts = subs(factory)
    assert {row.financial_access_status.value for row in facts} == {"allowed", "blocked"}
    assert facts[0].latest_observation_id != facts[1].latest_observation_id
    assert {row.product_id for row in facts} == {"proposal_ai", "brief_decoder"}
    with factory() as db:
        scopes = list(db.scalars(select(BillingProductAccessScope)))
        assert len(scopes) == 2 and all(scope.primary_subscription_id is None for scope in scopes)
        for model in (PaidAccessState, PurchasedAllowance, AccessInvalidationOutbox):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert all(obs.resulting_access_revision is None for obs in db.scalars(select(BillingStateObservation)))
    schedules = [(row.work_item_id, row.next_attempt_at, row.enqueue_generation) for row in jobs(factory)]
    assert work.enroll_batch(factory, step1_settings()) == 0
    restarted = BillingWorker(step1_settings(), factory, sources.require_lbx())
    await restarted.start()
    await restarted.aclose()
    assert [(row.work_item_id, row.next_attempt_at, row.enqueue_generation) for row in jobs(factory)] == schedules
    assert [(row.subscription_id, row.latest_observation_id, row.projection_valid_until) for row in subs(factory)] == [
        (row.subscription_id, row.latest_observation_id, row.projection_valid_until) for row in facts
    ]
    assert not [
        request for request in transport.requests if request.method == "POST" and not request.url.path.endswith("/auth")
    ][3:]


async def test_billing_worker_hint_during_execution_survives_completion_and_competing_claims(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    _, sources, _ = scenario
    factory = postgres_session_factory
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: work.claim_work(factory, step1_settings(), WorkLane.URGENT), range(2)))
    assert sum(claim is not None for claim in claims) == 1
    claim = next(claim for claim in claims if claim)
    with factory() as db:
        work.enroll_subscription(db, db.get(ExternalSubscription, UUID(claim.reference)), hint=True)
        db.commit()
    await reconcile_subscription(
        sources.require_lbx(),
        sources.billing,
        step1_settings(),
        factory=factory,
        subscription_id=UUID(claim.reference),
        work_claim=claim,
    )
    row = jobs(factory)[0]
    assert row.work_state == "pending" and row.lease_owner is None
    assert row.enqueue_generation == 1 and row.next_attempt_at <= datetime.now(UTC)
    assert work.claim_work(factory, step1_settings(), WorkLane.URGENT) is not None


async def test_billing_worker_expired_live_handler_cannot_apply_or_complete_new_owner(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    activate(transport)
    worker_a = BillingWorker(step1_settings(billing_worker_urgent_concurrency=1), factory, sources.require_lbx())
    worker_b = BillingWorker(step1_settings(), factory, sources.require_lbx())
    original_get = sources.require_lbx().get_subscription
    entered, release = asyncio.Event(), asyncio.Event()
    count = 0

    async def paused(**kwargs: object) -> object:
        nonlocal count
        count += 1
        if count == 1:
            entered.set()
            await release.wait()
        return await original_get(**kwargs)

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", paused)
    task_a = asyncio.create_task(worker_a.tick(WorkLane.URGENT))
    await asyncio.wait_for(entered.wait(), 5)
    assert worker_a.admissions[WorkLane.URGENT].active_count == 1
    with factory() as db:
        row = db.get(BillingWorkItem, jobs(factory)[0].work_item_id)
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        sub = db.get(ExternalSubscription, UUID(row.scope_reference))
        sub.reconciliation_lease_expires_at = row.lease_expires_at
        db.commit()
    assert await worker_a.tick(WorkLane.URGENT) is False  # Live GET retains its slot.
    assert await worker_b.tick(WorkLane.URGENT)
    fresh = subs(factory)[0]
    queue = jobs(factory)[0]
    release.set()
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale|billing_work_stale"):
        await task_a
    after = subs(factory)[0]
    assert (after.latest_observation_id, after.projection_valid_until) == (
        fresh.latest_observation_id,
        fresh.projection_valid_until,
    )
    assert jobs(factory)[0].next_attempt_at == queue.next_attempt_at
    assert worker_a.admissions[WorkLane.URGENT].active_count == 0


async def test_billing_worker_local_expiry_is_provider_free_idempotent_and_refresh_wins(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    activate(transport)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    await worker.tick(WorkLane.URGENT)
    trusted = subs(factory)[0]
    with factory() as db:
        sub = db.get(ExternalSubscription, trusted.subscription_id)
        sub.projection_valid_until = datetime.now(UTC) - timedelta(seconds=1)
        sub.last_authoritative_read_at = sub.projection_valid_until - timedelta(hours=6)
        work.schedule_reconciliation(db, sub, None, complete=False)
        db.commit()
    before_requests = len(transport.requests)
    assert await worker.tick(WorkLane.LOCAL)
    assert not await worker.tick(WorkLane.LOCAL)
    assert len(transport.requests) == before_requests
    current = subs(factory)[0]
    assert (
        current.lifecycle_status == trusted.lifecycle_status
        and current.financial_access_status == trusted.financial_access_status
    )
    assert current.latest_observation_id == trusted.latest_observation_id
    with factory() as db:
        evidence = list(
            db.scalars(
                select(BillingStateObservation).where(
                    BillingStateObservation.observation_kind
                    == BillingStateObservationKind.DETERMINISTIC_ACCESS_BOUNDARY
                )
            )
        )
        assert len(evidence) == 1 and evidence[0].basis_observation_id == trusted.latest_observation_id
        assert evidence[0].resulting_access_revision is None
        # Repeat incomplete source attempts do not resurrect the same expiry.
        work.schedule_reconciliation(db, db.get(ExternalSubscription, trusted.subscription_id), None, complete=False)
        db.commit()
    assert jobs(factory, work.EXPIRY)[0].work_state == "completed"
    with factory() as db:
        row = db.get(BillingWorkItem, jobs(factory, work.EXPIRY)[0].work_item_id)
        row.work_state = "pending"
        db.commit()
    old_expiry = work.claim_work(factory, step1_settings(), WorkLane.LOCAL)
    await reconcile_subscription(
        sources.require_lbx(),
        sources.billing,
        step1_settings(),
        factory=factory,
        subscription_id=trusted.subscription_id,
    )
    work.expire_trust(factory, old_expiry)
    assert jobs(factory, work.EXPIRY)[0].next_attempt_at == subs(factory)[0].projection_valid_until
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillingStateObservation)
                .where(
                    BillingStateObservation.observation_kind
                    == BillingStateObservationKind.DETERMINISTIC_ACCESS_BOUNDARY
                )
            )
            == 1
        )


async def test_billing_worker_atomic_link_enrollment_and_concurrent_sweeps(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    with factory() as db:
        db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        db.commit()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: work.enroll_batch(factory, step1_settings()), range(2)))
    assert len(jobs(factory)) == 1
    row = jobs(factory)[0]
    with factory() as db:
        row = db.get(BillingWorkItem, row.work_item_id)
        future = row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=10)
        db.commit()
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.bind_financial(
        factory,
        purchase,
        op,
        567,
        observation=_observation(Subscription.model_validate(transport.effective_subscription()), purchase),
    )
    assert jobs(factory)[0].next_attempt_at == future

    # Creation and enrollment share one commit: inject enqueue failure.
    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected enqueue failure")

    monkeypatch.setattr(financial, "enroll_subscription", fail)
    with pytest.raises(RuntimeError, match="enqueue failure"):
        historical_link(factory, purchase, transport, "brief_decoder", 1)
    assert len(subs(factory)) == 1 and len(jobs(factory)) == 1


async def test_billing_worker_lost_claim_ack_starts_no_http_and_customer_send_is_excluded(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    with factory() as db:
        db.add(
            work_factory(
                kind="external_create_recovery",
                key=str(uuid4()),
                reference=str(uuid4()),
                due=datetime.now(UTC),
                owner="customer-send:test",
                expires=datetime.now(UTC) + timedelta(minutes=2),
            )
        )
        db.commit()
    original = work.claim_work

    def lose(*args: object, **kwargs: object) -> None:
        assert original(*args, **kwargs) is not None
        raise RuntimeError("lost claim acknowledgement")

    monkeypatch.setattr(work, "claim_work", lose)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    before = len(transport.requests)
    with pytest.raises(RuntimeError, match="lost claim"):
        await worker.tick(WorkLane.URGENT)
    assert len(transport.requests) == before
    assert jobs(factory)[0].lease_owner is not None
    assert any(row.lease_owner == "customer-send:test" for row in jobs(factory, "external_create_recovery"))


async def test_billing_worker_embedded_lifespan_smoke_and_reserved_local_progress(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import asynccontextmanager
    from collections.abc import AsyncIterator
    from app.core.settings import Settings
    import httpx
    from app import main
    from app.composition.billing_worker import billing_worker_resources

    transport, _, _ = scenario
    factory = postgres_session_factory
    transport.pool = None  # Independent local scans may hold their own DB units.
    config = step1_settings(billing_worker_enabled=True)

    @asynccontextmanager
    async def resources(configuration: Settings) -> AsyncIterator[BillingWorker | None]:
        async with billing_worker_resources(
            config, factory=factory, transport=httpx.MockTransport(transport.respond)
        ) as worker:
            yield worker

    monkeypatch.setattr(main, "billing_worker_resources", resources)
    monkeypatch.setattr(main, "settings", config)
    app = main.create_app()
    before = len(transport.requests)
    async with main.lifespan(app):
        worker = app.state.billing_worker
        async with asyncio.timeout(8):
            while not worker.healthy or not jobs(factory, work.EXPIRY):
                await asyncio.sleep(0.02)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://portal.test") as client:
            assert (await client.get("/api/health/ready")).status_code == 200
            result = (await client.get("/api/health/billing")).json()
            assert result["status"] == "running" and result["last_scan_at"]
        assert worker.client is not app.state.sources.require_lbx()
    assert all(request.method == "GET" for request in transport.requests[before:])
    assert all(task.done() for task in worker.tasks)
    assert worker.cleanup_pending == 0


@pytest.mark.parametrize(
    "remaining,expected_lane",
    [
        (timedelta(minutes=30, seconds=1), WorkLane.NORMAL),
        (timedelta(minutes=30), WorkLane.URGENT),
        (timedelta(minutes=20), WorkLane.URGENT),
        (timedelta(seconds=-1), WorkLane.URGENT),
    ],
)
async def test_billing_worker_claims_by_current_trust_deadline_without_reenrollment(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    remaining: timedelta,
    expected_lane: WorkLane,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    config = step1_settings()
    activate(transport)
    worker = BillingWorker(config, factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    job = jobs(factory)[0]
    assert job.priority == 0

    now = datetime.now(UTC)
    monkeypatch.setattr(work.billing_reconciliation, "database_now", lambda db: now)
    with factory() as db:
        sub = db.get(ExternalSubscription, UUID(job.scope_reference))
        sub.projection_valid_until = now + remaining
        sub.last_authoritative_read_at = sub.projection_valid_until - timedelta(hours=6)
        row = db.get(BillingWorkItem, job.work_item_id)
        row.next_attempt_at = now + timedelta(seconds=1)
        db.commit()

    # Urgency does not bypass the due time or an existing execution lease.
    assert work.claim_work(factory, config, WorkLane.URGENT) is None
    assert work.claim_work(factory, config, WorkLane.NORMAL) is None
    with factory() as db:
        row = db.get(BillingWorkItem, job.work_item_id)
        row.next_attempt_at = now - timedelta(seconds=1)
        db.commit()
    assert work.enroll_batch(factory, config) == 0
    pending = jobs(factory)[0]
    assert pending.priority == 0 and pending.enqueue_generation == job.enqueue_generation

    other_lane = WorkLane.NORMAL if expected_lane == WorkLane.URGENT else WorkLane.URGENT
    assert work.claim_work(factory, config, other_lane) is None
    claim = work.claim_work(factory, config, expected_lane)
    assert claim is not None and claim.id == job.work_item_id
    assert work.claim_work(factory, config, WorkLane.URGENT) is None
    assert work.claim_work(factory, config, WorkLane.NORMAL) is None


async def test_billing_worker_normal_and_urgent_have_reserved_capacity_for_local_expiry(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    historical_link(factory, purchase, transport, "brief_decoder", 1)
    worker = BillingWorker(step1_settings(billing_worker_urgent_concurrency=1), factory, sources.require_lbx())
    activate(transport)
    await worker.tick(WorkLane.URGENT)
    await worker.tick(WorkLane.URGENT)
    items = jobs(factory)
    normal = next(row for row in items if row.priority == 0)
    urgent = next(row for row in items if row.priority > 0)
    with factory() as db:
        now = datetime.now(UTC)
        for item in items:
            db.get(BillingWorkItem, item.work_item_id).next_attempt_at = now - timedelta(seconds=1)
        db.get(BillingWorkItem, normal.work_item_id).next_attempt_at = now - timedelta(seconds=2)
        sub = db.get(ExternalSubscription, UUID(normal.scope_reference))
        sub.projection_valid_until = now - timedelta(seconds=1)
        sub.last_authoritative_read_at = sub.projection_valid_until - timedelta(hours=6)
        work.schedule_reconciliation(db, sub, None, complete=False)
        db.commit()
    # Occupy source lanes independently. Local expiry still completes without HTTP.
    before = len(transport.requests)
    async with worker.admissions[WorkLane.NORMAL].operation():
        async with worker.admissions[WorkLane.URGENT].operation():
            assert not await worker.tick(WorkLane.URGENT)
            assert not await worker.tick(WorkLane.NORMAL)
            assert await worker.tick(WorkLane.LOCAL)
            assert worker.admissions[WorkLane.URGENT].active_count == 1
        assert len(transport.requests) == before
        # Expired trust makes the previously normal job eligible for the free
        # urgent slot even while normal source capacity remains occupied.
        assert await worker.tick(WorkLane.URGENT)
        assert worker.admissions[WorkLane.NORMAL].active_count == 1
    assert jobs(factory)[0].work_item_id != jobs(factory)[1].work_item_id
    assert work.claim_work(factory, step1_settings(), WorkLane.URGENT).id == urgent.work_item_id


@pytest.mark.parametrize("cancel", [False, True])
async def test_billing_worker_timeout_or_cancel_restart_preserves_facts_and_reclaims(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    cancel: bool,
) -> None:
    from app.infrastructure.preflight import PreflightDeadlineExceeded

    transport, sources, _ = scenario
    factory = postgres_session_factory
    activate(transport)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    await worker.tick(WorkLane.URGENT)
    original = subs(factory)[0]
    with factory() as db:
        work.enroll_subscription(db, db.get(ExternalSubscription, original.subscription_id), hint=True)
        db.commit()
    original_get = sources.require_lbx().get_user
    entered = asyncio.Event()

    async def slow(*, budget: object, **kwargs: object) -> None:
        async def wait() -> None:
            entered.set()
            await asyncio.sleep(10)

        return await budget.run(wait)

    monkeypatch.setattr(sources.require_lbx(), "get_user", slow)
    configuration = step1_settings(billing_worker_io_timeout_seconds=0.1, preflight_cleanup_timeout_seconds=0.01)
    interrupted = BillingWorker(configuration, factory, sources.require_lbx())
    task = asyncio.create_task(interrupted.tick(WorkLane.URGENT))
    await asyncio.wait_for(entered.wait(), 2)
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else PreflightDeadlineExceeded):
        await task
    assert interrupted.admissions[WorkLane.URGENT].active_count == 0
    current = subs(factory)[0]
    assert current.projection_valid_until == original.projection_valid_until
    assert current.latest_observation_id == original.latest_observation_id
    with factory() as db:
        row = db.get(BillingWorkItem, jobs(factory)[0].work_item_id)
        assert row.work_state == "running" and row.lease_owner
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.get(ExternalSubscription, original.subscription_id).reconciliation_lease_expires_at = row.lease_expires_at
        db.commit()
    monkeypatch.setattr(sources.require_lbx(), "get_user", original_get)
    restarted = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await restarted.tick(WorkLane.URGENT)
    assert subs(factory)[0].latest_observation_id != original.latest_observation_id
    assert jobs(factory)[0].work_state == "pending" and jobs(factory)[0].lease_owner is None


async def test_billing_worker_link_and_sweep_interleave_without_partial_enrollment(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from threading import Event
    from starlette.concurrency import run_in_threadpool

    transport, _, purchase = scenario
    factory = postgres_session_factory
    entered, release = Event(), Event()
    original = financial.enroll_subscription

    def pause(db: Session, subscription: ExternalSubscription) -> None:
        entered.set()
        assert release.wait(5)
        original(db, subscription)

    monkeypatch.setattr(financial, "enroll_subscription", pause)
    task = asyncio.create_task(run_in_threadpool(historical_link, factory, purchase, transport, "brief_decoder", 1))
    try:
        assert await run_in_threadpool(entered.wait, 5)
        assert len(subs(factory)) == len(jobs(factory)) == 1
        assert work.enroll_batch(factory, step1_settings()) == 0
    finally:
        release.set()
    await task
    assert len(subs(factory)) == len(jobs(factory)) == 2
    assert work.enroll_batch(factory, step1_settings()) == 0


async def test_billing_worker_quarantines_malformed_history_without_hot_loop(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.models import ExternalBillingCustomer

    _, _, purchase = scenario
    factory = postgres_session_factory
    with factory() as db:
        db.get(ExternalBillingCustomer, purchase.customer_id).provider_origin = None
        db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        db.commit()
    assert work.enroll_batch(factory, step1_settings()) == 1
    assert work.enroll_batch(factory, step1_settings()) == 0
    assert jobs(factory)[0].work_state == "invalid"
    assert work.inspect_backlog(factory, step1_settings())[2] == 1
    assert work.claim_work(factory, step1_settings(), WorkLane.URGENT) is None


async def test_billing_worker_current_subscription_fence_still_requires_queue_owner(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation
    from app.integrations.lbx.reconciliation import read_subscription_proof

    _, sources, _ = scenario
    factory = postgres_session_factory
    config = step1_settings()
    claim = work.claim_work(factory, config, WorkLane.URGENT)
    subject = claim_reconciliation(factory, config, UUID(claim.reference), io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        proof = await read_subscription_proof(sources.require_lbx(), subject, config, budget=budget)
    with factory() as db:
        # Only the queue lease expires: the old subscription fence is current.
        db.get(BillingWorkItem, claim.id).lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    successor = work.claim_work(factory, config, WorkLane.URGENT)
    assert successor.owner != claim.owner
    before = subs(factory)[0].latest_observation_id
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        apply_reconciliation(factory, subject, proof, work_claim=claim)
    assert subs(factory)[0].latest_observation_id == before
    assert jobs(factory)[0].lease_owner == successor.owner


async def test_billing_worker_incomplete_first_read_cannot_expire_preparation_evidence(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.lbx.errors import LbxUnavailable

    _, sources, _ = scenario
    factory = postgres_session_factory
    original = subs(factory)[0]
    original_get = sources.require_lbx().get_user

    async def unavailable(**kwargs: object) -> None:
        raise LbxUnavailable()

    monkeypatch.setattr(sources.require_lbx(), "get_user", unavailable)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    assert jobs(factory, work.EXPIRY) == []
    assert work.enroll_batch(factory, step1_settings()) == 0
    assert not await worker.tick(WorkLane.LOCAL)
    current = subs(factory)[0]
    assert current.latest_observation_id == original.latest_observation_id
    assert current.projection_valid_until == original.projection_valid_until
    with factory() as db:
        evidence = db.get(BillingStateObservation, current.latest_observation_id)
        assert evidence.access_scope_id is None and evidence.evidence_schema_version == "prepared-subscription:v1"
        work.enroll_subscription(db, db.get(ExternalSubscription, current.subscription_id), hint=True)
        db.commit()
    monkeypatch.setattr(sources.require_lbx(), "get_user", original_get)
    assert await worker.tick(WorkLane.URGENT)
    assert len(jobs(factory, work.EXPIRY)) == 1
    with factory() as db:
        current = db.get(ExternalSubscription, current.subscription_id)
        evidence = db.get(BillingStateObservation, current.latest_observation_id)
        assert evidence.access_scope_id is not None
