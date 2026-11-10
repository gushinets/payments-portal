"""Real PostgreSQL queue/outbox races; Kernel HTTP responses are synthetic."""

import asyncio
import json
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier

import httpx
import pytest
from alembic import command
from pydantic import SecretStr
from sqlalchemy import delete, select
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.cli.billing_purchases import _run, parser
from app.composition.billing_worker import billing_worker_resources
from app.core.settings import Settings
from app.domains.billing import access_invalidation as delivery, work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.work_contracts import WorkLane
from app.domains.catalog.contracts import SourceProvenance
from app.integrations.kernel.client import PlatformKernelClient
from app.jobs.billing import BillingWorker
from app.models import AccessInvalidationOutbox, BillingWorkItem, BillingProductAccessScope, PaidAccessState
from apps.api.tests.factories.paid_access import reader_identity
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.postgres import alembic_test_config
from apps.api.tests.test_paid_access_reconciliation_postgres import paid_source as paid_source, reconcile, Scenario

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def pending(migrated_database: Engine, postgres_session_factory: sessionmaker[Session]) -> tuple:
    config = step1_settings(lbx_base_url="", lbx_server_username=SecretStr(""), lbx_server_password=SecretStr(""))
    with postgres_session_factory() as db:
        user, _ = reader_identity("synthetic-delivery")
        db.add(user)
        db.flush()
        identity = user.id
        db.add(
            AccessInvalidationOutbox(
                tenant_id=user.tenant_id,
                region=user.region,
                user_id=identity,
                pending_revision=1,
                delivered_revision=0,
                next_attempt_at=datetime.now(UTC),
            )
        )
        delivery.schedule_delivery(db, identity, datetime.now(UTC))
        db.commit()
    return postgres_session_factory, config, identity


def saved(factory: sessionmaker[Session]) -> tuple[int, int, str, int, str | None]:
    with factory() as db:
        outbox = db.scalar(select(AccessInvalidationOutbox))
        row = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == delivery.KIND))
        return (
            outbox.pending_revision,
            outbox.delivered_revision,
            row.work_state if row else "unscheduled",
            row.enqueue_generation if row else 0,
            row.lease_owner if row else None,
        )


def due(factory: sessionmaker[Session], *, expire: bool = False) -> None:
    with factory() as db:
        row = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == delivery.KIND))
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        if expire:
            row.lease_expires_at = row.next_attempt_at
        db.commit()


def kernel(config: Settings, handler: object) -> PlatformKernelClient:
    return PlatformKernelClient(
        config,
        provenance=SourceProvenance.CONFIGURED_SOURCE,
        transport=httpx.MockTransport(handler),
        max_connections=config.billing_worker_delivery_concurrency,
    )


async def test_exact_sent_n_keeps_concurrent_n_plus_one_without_lbx(pending: tuple) -> None:
    factory, config, identity = pending
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        assert request.url.path == "/internal/v1/access-invalidations"
        assert request.headers["authorization"] == "Bearer " + config.kernel_service_token.get_secret_value()
        assert "origin" not in request.headers
        # Committing a new revision during HTTP proves no User/outbox/queue lock is held.
        if len(requests) == 1:
            with factory() as db:
                user = work.lock_user(db, identity)
                outbox = delivery.paid_access.outbox(db, user.id)
                outbox.pending_revision = 2
                delivery.schedule_delivery(db, identity, datetime.now(UTC))
                db.commit()
        return httpx.Response(204)

    client = kernel(config, respond)
    worker = BillingWorker(config, factory, None, kernel_client=client)
    try:
        assert config.lbx_configuration_error == "lbx_not_configured"
        assert await worker.tick(WorkLane.DELIVERY)
        assert saved(factory)[:3] == (2, 1, "pending")
        assert await worker.tick(WorkLane.DELIVERY)
        assert saved(factory)[:3] == (2, 2, "completed")
        assert [row["access_revision"] for row in requests] == [1, 2]
        assert requests[0] == dict(
            schema_version=1, tenant_id="anytoolai", region="ru", user_id=str(identity), access_revision=1
        )
    finally:
        await worker.aclose()
        await client.aclose()


@pytest.mark.parametrize("crash", ["before_send", "after_apply", "ack_rollback"])
async def test_crash_restart_redelivers_unacknowledged_n(
    pending: tuple, monkeypatch: pytest.MonkeyPatch, crash: str
) -> None:
    factory, config, _ = pending
    claim = work.claim_work(factory, config, WorkLane.DELIVERY)
    sent = delivery.capture_delivery(factory, config, claim)
    applied = []

    def respond(request: httpx.Request) -> httpx.Response:
        applied.append(json.loads(request.content)["access_revision"])
        return httpx.Response(204)

    client = kernel(config, respond)
    worker = BillingWorker(config, factory, None, kernel_client=client)
    if crash != "before_send":
        async with worker.admissions[WorkLane.DELIVERY].operation() as budget:
            await client.send_invalidation(sent, budget=budget)
    if crash == "ack_rollback":

        def fail_commit(db: Session) -> None:
            raise RuntimeError("synthetic ack commit failure")

        with monkeypatch.context() as patch:
            patch.setattr(Session, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="ack commit"):
                delivery.apply_delivery(factory, claim, sent)
    assert saved(factory)[:3] == (1, 0, "running")
    due(factory, expire=True)
    try:
        assert await worker.tick(WorkLane.DELIVERY)
        assert saved(factory)[:3] == (1, 1, "completed")
        assert applied == ([1] if crash == "before_send" else [1, 1])
    finally:
        await worker.aclose()
        await client.aclose()


@pytest.mark.parametrize("outcome", ["transport", "timeout", 429, 500, 503, 401, 403, 404, 409, 422, 302, 200])
async def test_outage_backoff_and_permanent_parking_cli_retry(
    pending: tuple, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, outcome: str | int
) -> None:
    factory, config, identity = pending
    attempts = []

    def respond(request: httpx.Request) -> httpx.Response:
        attempts.append(request)
        if outcome in {"transport", "timeout"}:
            error = httpx.ConnectError if outcome == "transport" else httpx.ReadTimeout
            raise error("synthetic-remote-secret")
        return httpx.Response(outcome, text="synthetic-remote-secret")

    client = kernel(config, respond)
    worker = BillingWorker(config, factory, None, kernel_client=client)
    permanent = isinstance(outcome, int) and outcome not in {429, 500, 503}
    try:
        assert await worker.tick(WorkLane.DELIVERY)
        assert saved(factory)[:3] == (1, 0, "invalid" if permanent else "pending")
        with factory() as db:
            outbox = db.scalar(select(AccessInvalidationOutbox))
            assert outbox.attempt_count == 1 and outbox.last_error_classification.startswith("kernel_invalidation_")
            assert outbox.next_attempt_at > datetime.now(UTC)
        assert not await worker.tick(WorkLane.DELIVERY)
        assert len(attempts) == 1
        assert "synthetic-remote-secret" not in caplog.text
        monkeypatch.setattr("app.core.database.SessionLocal", factory)
        inspected = await _run(
            parser().parse_args(["inspect-invalidation", "--user-id", str(identity)]), config, "test-operator"
        )
        assert inspected["delivered_revision"] == 0
        if permanent:
            assert "parked" in caplog.text
            assert delivery.repair_delivery(factory, config) == 0
            with factory() as db:
                outbox = db.scalar(select(AccessInvalidationOutbox))
                outbox.pending_revision = 2
                delivery.schedule_delivery(db, identity, datetime.now(UTC))
                db.commit()
            assert saved(factory)[:3] == (2, 0, "invalid")
            result = await _run(
                parser().parse_args(["retry-invalidation", "--user-id", str(identity)]), config, "test-operator"
            )
            assert result["work_state"] == "pending"
        else:
            with pytest.raises(BillingRefused, match="invalidation_not_parked"):
                delivery.inspect_delivery(factory, config, identity, retry=True)
    finally:
        await worker.aclose()
        await client.aclose()


def test_stale_lease_cannot_ack_and_late_n_cannot_regress_delivered_n_plus_one(pending: tuple) -> None:
    factory, config, identity = pending
    old = work.claim_work(factory, config, WorkLane.DELIVERY)
    sent = delivery.capture_delivery(factory, config, old)
    due(factory, expire=True)
    successor = work.claim_work(factory, config, WorkLane.DELIVERY)
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        delivery.capture_delivery(factory, config, old)
    with factory() as db:
        outbox = db.scalar(select(AccessInvalidationOutbox))
        outbox.pending_revision = 2
        delivery.schedule_delivery(db, identity, datetime.now(UTC))
        db.commit()
    newer = delivery.capture_delivery(factory, config, successor)
    delivery.apply_delivery(factory, successor, newer)
    before = saved(factory)
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        delivery.apply_delivery(factory, old, sent)
    assert saved(factory) == before and before[:3] == (2, 2, "pending")
    # The unconsumed new generation is completed only by its own claimant.
    last = work.claim_work(factory, config, WorkLane.DELIVERY)
    assert delivery.capture_delivery(factory, config, last) is None
    assert saved(factory)[:3] == (2, 2, "completed")


def test_competing_claims_and_scoped_restart_repair(pending: tuple) -> None:
    factory, config, identity = pending
    barrier = Barrier(2)

    def claim() -> object:
        barrier.wait(timeout=5)
        return work.claim_work(factory, config, WorkLane.DELIVERY)

    with ThreadPoolExecutor(2) as pool:
        a, b = pool.submit(claim), pool.submit(claim)
        assert sum(value is not None for value in (a.result(), b.result())) == 1
    with factory() as db:
        db.execute(delete(BillingWorkItem))
        db.commit()
    foreign = config.model_copy(update={"instance_region": "us"})
    assert delivery.repair_delivery(factory, foreign) == 0
    assert work.claim_work(factory, foreign, WorkLane.DELIVERY) is None
    with pytest.raises(BillingRefused, match="invalidation_not_found"):
        delivery.inspect_delivery(factory, foreign, identity)
    assert delivery.repair_delivery(factory, config) == 1
    assert delivery.repair_delivery(factory, config) == 0
    assert saved(factory)[:3] == (1, 0, "pending")
    assert work.inspect_backlog(factory, config)[0] == 1
    with factory() as db:
        retry_at = datetime.now(UTC) + timedelta(minutes=5)
        db.scalar(select(AccessInvalidationOutbox)).next_attempt_at = retry_at
        db.scalar(select(BillingWorkItem)).work_state = "completed"
        db.commit()
    assert delivery.repair_delivery(factory, config) == 1
    assert work.claim_work(factory, config, WorkLane.DELIVERY) is None
    with factory() as db:
        assert db.scalar(select(BillingWorkItem.next_attempt_at)) == retry_at


async def test_lifespan_repairs_without_lbx_and_owns_independent_pool(pending: tuple) -> None:
    factory, config, _ = pending
    with factory() as db:
        db.execute(delete(BillingWorkItem))
        db.commit()
    config = config.model_copy(
        update={
            "billing_worker_enabled": True,
            "database_url": factory.kw["bind"].url.render_as_string(hide_password=False),
        }
    )
    requests = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    async with billing_worker_resources(config, kernel_transport=httpx.MockTransport(respond)) as worker:
        assert worker.client is None and worker.kernel_client is not None
        engine = worker.factory.kw["bind"]
        assert engine is not factory.kw["bind"]
        assert (
            engine.pool.size()
            == config.billing_worker_urgent_concurrency
            + config.billing_worker_normal_concurrency
            + config.billing_worker_delivery_concurrency
            + 1
        )
        assert engine.pool._max_overflow == 0
        async with asyncio.timeout(5):
            while saved(factory)[:3] != (1, 1, "completed"):
                await asyncio.sleep(0.01)
        assert len(requests) == 1
    assert worker.cleanup_pending == 0 and all(task.done() for task in worker.tasks)


async def test_paid_commit_atomic_and_saturated_delivery_preserves_local_expiry(paid_source: Scenario) -> None:
    scenario = paid_source
    await reconcile(scenario)
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked(request: httpx.Request) -> httpx.Response:
        entered.set()
        await release.wait()
        return httpx.Response(204)

    client = kernel(scenario.config, blocked)
    worker = BillingWorker(scenario.config, scenario.factory, scenario.sources.require_lbx(), kernel_client=client)
    task = asyncio.create_task(worker.tick(WorkLane.DELIVERY))
    await asyncio.wait_for(entered.wait(), 3)
    try:
        with scenario.factory() as db:
            scope = db.scalar(select(BillingProductAccessScope))
            scope.effective_access_until = datetime.now(UTC) - timedelta(seconds=1)
            deadline = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
            deadline.next_attempt_at = scope.effective_access_until
            db.commit()
        assert not await worker.tick(WorkLane.DELIVERY)
        async with (
            worker.admissions[WorkLane.URGENT].operation(),
            worker.admissions[WorkLane.URGENT].operation(),
            worker.admissions[WorkLane.NORMAL].operation(),
        ):
            assert await asyncio.wait_for(worker.tick(WorkLane.LOCAL), 3)
        assert saved(scenario.factory)[:3] == (2, 0, "running")
        release.set()
        assert await task
        assert saved(scenario.factory)[:3] == (2, 1, "pending")
        assert await worker.tick(WorkLane.DELIVERY)
        assert saved(scenario.factory)[:3] == (2, 2, "completed")
    finally:
        release.set()
        await task
        await worker.aclose()
        await client.aclose()


def test_forward_index_migration_preserves_pending_history(pending: tuple, database_test_url: URL) -> None:
    factory, _, _ = pending
    before = saved(factory)
    with alembic_test_config(database_test_url) as config:
        command.downgrade(config, "20261110_0007")
        command.upgrade(config, "head")
    assert saved(factory) == before
    with pytest.raises(IntegrityError), factory() as db:
        row = db.scalar(select(BillingWorkItem))
        db.add(
            BillingWorkItem(
                work_kind=row.work_kind,
                scope_kind=row.scope_kind,
                scope_reference=row.scope_reference,
                coalescing_key=row.coalescing_key,
                payload_schema_version="billing-work:v1",
                payload_document={},
                next_attempt_at=datetime.now(UTC),
                work_state="pending",
            )
        )
        db.flush()


async def test_overdue_refresh_schedules_only_final_causal_revision(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.infrastructure.queries import billing_reconciliation

    scenario = paid_source
    await reconcile(scenario)
    scheduled = []
    original = delivery.schedule_delivery

    def record(db: Session, user_id: object, now: datetime) -> None:
        scheduled.append(db.scalar(select(PaidAccessState.access_revision)))
        original(db, user_id, now)

    with scenario.factory() as db:
        boundary = db.scalar(select(BillingProductAccessScope.effective_access_until))
        clock = billing_reconciliation.database_now
        delta = boundary + timedelta(seconds=1) - clock(db)
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock(db) + delta)
    monkeypatch.setattr(delivery, "schedule_delivery", record)
    await reconcile(scenario)
    assert scheduled == [3]  # Revision 2 is audited, without premature queue locking.
    assert saved(scenario.factory)[:3] == (3, 0, "pending")


async def test_semantic_noop_preserves_delivery_backoff(paid_source: Scenario) -> None:
    scenario = paid_source
    await reconcile(scenario)
    claim = work.claim_work(scenario.factory, scenario.config, WorkLane.DELIVERY)
    sent = delivery.capture_delivery(scenario.factory, scenario.config, claim)
    delivery.apply_delivery(scenario.factory, claim, sent, error="kernel_invalidation_unavailable")
    with scenario.factory() as db:
        before = db.execute(
            select(BillingWorkItem.next_attempt_at, BillingWorkItem.enqueue_generation).where(
                BillingWorkItem.work_kind == delivery.KIND
            )
        ).one()
    await reconcile(scenario)
    with scenario.factory() as db:
        after = db.execute(
            select(BillingWorkItem.next_attempt_at, BillingWorkItem.enqueue_generation).where(
                BillingWorkItem.work_kind == delivery.KIND
            )
        ).one()
    assert after == before


async def test_failed_claim_commit_sends_nothing(pending: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    factory, config, _ = pending
    requests = []

    def fail_commit(db: Session) -> None:
        raise RuntimeError("synthetic uncertain claim commit")

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(204)

    client = kernel(config, respond)
    worker = BillingWorker(config, factory, None, kernel_client=client)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(Session, "commit", fail_commit)
            with pytest.raises(RuntimeError, match="uncertain claim"):
                await worker.tick(WorkLane.DELIVERY)
        assert requests == [] and saved(factory)[:3] == (1, 0, "pending")
    finally:
        await worker.aclose()
        await client.aclose()


@pytest.mark.parametrize("cancel", [False, True])
async def test_timeout_or_cancellation_retains_actual_http_cleanup_slot(pending: tuple, cancel: bool) -> None:
    factory, config, _ = pending
    config = config.model_copy(
        update={"billing_worker_io_timeout_seconds": 0.2, "preflight_cleanup_timeout_seconds": 0.02}
    )
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowClose(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b""

        async def aclose(self) -> None:
            entered.set()
            await release.wait()

    client = kernel(config, lambda request: httpx.Response(204, stream=SlowClose()))
    worker = BillingWorker(config, factory, None, kernel_client=client)
    task = asyncio.create_task(worker.tick(WorkLane.DELIVERY))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        if cancel:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            assert await task
        assert worker.admissions[WorkLane.DELIVERY].active_count == 1
        assert worker.cleanup_pending == 1
        assert not await worker.tick(WorkLane.DELIVERY)
        assert saved(factory)[1] == 0
    finally:
        release.set()
        await worker.aclose()
        await client.aclose()
