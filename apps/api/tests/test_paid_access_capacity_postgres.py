"""Real DB/thread saturation and reader cancellation, with synthetic sources."""

import asyncio
from threading import Event, Lock

import anyio
import httpx
import pytest
from sqlalchemy import create_engine, event, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.composition import paid_reads
from app.core.observability import request_id_context
from app.domains.billing import paid_router, paid_read
from app.domains.purchases import router as purchase_routes
from app.http.dependencies import get_session_factory
from app.infrastructure.preflight import PreflightCleanupPending
from app.main import create_app
from app.models import AuthSession, User
from apps.api.tests.factories.paid_access import reader_identity
from apps.api.tests.factories.paid_runtime import paid_scenario as paid_scenario, paid_source as paid_source, reconcile
from apps.api.tests.test_any709_step2_postgres import TOKEN
from apps.api.tests.test_paid_access_read_postgres import billing_snapshot

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("saturation", ["none", "database", "threads"])
async def test_paid_read_retains_capacity_before_new_purchase_source_admission(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    saturation: str,
) -> None:
    factory = postgres_session_factory
    sources, config = paid_scenario[1:3]
    await reconcile(paid_scenario, factory)
    with factory() as db:
        user, auth = reader_identity("new-buyer-capacity")
        db.add(user)
        db.flush()
        db.add(auth)
        db.commit()
        buyer_session_id = auth.id
    engine = factory.kw["bind"]
    config = config.model_copy(update={"database_url": engine.url.render_as_string(hide_password=False)})
    database_capacity = engine.pool.size() + engine.pool._max_overflow
    shared_threads = anyio.to_thread.current_default_thread_limiter()
    capacity = database_capacity if saturation == "database" else int(shared_threads.total_tokens)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.state.sources = sources
    monkeypatch.setattr(purchase_routes, "settings", config)
    monkeypatch.setattr(paid_router, "settings", config)
    blocker_engine = create_engine(engine.url)
    blocker = blocker_engine.connect()
    transaction = blocker.begin()
    loop = asyncio.get_running_loop()
    blocked_updates = asyncio.Event()
    mutex = Lock()
    entered = 0

    def before_execute(
        conn: object, cursor: object, statement: str, parameters: object, context: object, executemany: bool
    ) -> None:
        nonlocal entered
        if statement.lstrip().startswith("UPDATE auth_sessions"):
            with mutex:
                entered += 1
                if entered == database_capacity:
                    loop.call_soon_threadsafe(blocked_updates.set)

    sale_tasks = []
    before = billing_snapshot(factory)
    try:
        async with (
            paid_reads.paid_read_resources(config) as reads,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://portal.test"
            ) as client,
        ):
            app.state.paid_reads = reads
            assert reads.engine is not engine
            assert reads.engine.pool.size() == paid_reads.PAID_READ_CONCURRENCY
            assert reads.engine.pool._max_overflow == 0
            if saturation != "none":
                blocker.execute(select(AuthSession.id).where(AuthSession.id == buyer_session_id).with_for_update())
                event.listen(engine, "before_cursor_execute", before_execute)
                sale_tasks = [
                    asyncio.create_task(
                        client.post(
                            "/api/purchases/review",
                            headers={"Authorization": "Bearer new-buyer-capacity"},
                            json={"product_id": "proposal_ai"},
                        )
                    )
                    for _ in range(capacity)
                ]
                await asyncio.wait_for(blocked_updates.wait(), 10)
                if saturation == "threads":
                    async with asyncio.timeout(10):
                        while shared_threads.borrowed_tokens < shared_threads.total_tokens:
                            await asyncio.sleep(0.01)
                assert engine.pool.checkedout() == database_capacity
                assert sources.preflight.active_count == sources.billing.active_count == 0
            # The paid user is independent of the new buyer's business-row lock.
            response = await asyncio.wait_for(
                client.get("/api/paid-access", headers={"Authorization": "Bearer " + TOKEN}), 2
            )
            assert response.status_code == 200 and response.json()["access_revision"] == 1
            assert response.headers["cache-control"] == "no-store"
            assert all(not task.done() for task in sale_tasks)
    finally:
        transaction.rollback()
        blocker.close()
        blocker_engine.dispose()
        if saturation != "none":
            event.remove(engine, "before_cursor_execute", before_execute)
        await asyncio.gather(*sale_tasks, return_exceptions=True)
        app.dependency_overrides.clear()
    assert billing_snapshot(factory) == before
    assert reads.closed and reads.engine is None


async def test_paid_read_overload_and_cancelled_waiter_retain_capacity_until_cleanup(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    engine = factory.kw["bind"]
    config = paid_scenario[2].model_copy(
        update={
            "database_url": engine.url.render_as_string(hide_password=False),
            "preflight_cleanup_timeout_seconds": 0.03,
        }
    )
    app = create_app()
    monkeypatch.setattr(paid_router, "settings", config)
    original_read = paid_reads.read_paid_access
    started = asyncio.Event()
    release = Event()
    mutex = Lock()
    loop = asyncio.get_running_loop()
    entered = 0

    def held_read(*args: object, **kwargs: object) -> object:
        nonlocal entered
        assert request_id_context.get() == "synthetic-paid-capacity"
        with mutex:
            entered += 1
            if entered == paid_reads.PAID_READ_CONCURRENCY:
                loop.call_soon_threadsafe(started.set)
        assert release.wait(10)
        return original_read(*args, **kwargs)

    monkeypatch.setattr(paid_reads, "read_paid_access", held_read)
    headers = {"Authorization": "Bearer " + TOKEN, "X-Request-ID": "synthetic-paid-capacity"}
    tasks = []
    async with (
        paid_reads.paid_read_resources(config) as reads,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client,
    ):
        app.state.paid_reads = reads
        try:
            maximum = paid_reads.PAID_READ_CONCURRENCY + paid_reads.PAID_READ_MAX_WAITING
            tasks = [asyncio.create_task(client.get("/api/paid-access", headers=headers)) for _ in range(maximum)]
            await asyncio.wait_for(started.wait(), 5)
            async with asyncio.timeout(5):
                while len(reads.tasks) < maximum:
                    await asyncio.sleep(0.01)
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
            assert len(reads.tasks) == maximum and entered == paid_reads.PAID_READ_CONCURRENCY
            refused = await client.get("/api/paid-access", headers=headers)
            assert refused.status_code == 503 and refused.json()["detail"]["code"] == "paid_access_busy"
            assert refused.headers["cache-control"] == "no-store"
            with pytest.raises(PreflightCleanupPending):
                await reads.aclose()
            assert reads.closed and reads.engine is not None
            release.set()
            responses = await asyncio.gather(*tasks[1:])
            assert all(response.status_code == 200 for response in responses)
            await reads.aclose()
            assert not reads.tasks and reads.engine is None
            assert (await client.get("/api/paid-access", headers=headers)).status_code == 503
        finally:
            release.set()
            await asyncio.gather(*tasks, return_exceptions=True)


@pytest.mark.parametrize("failure", ["session", "user", "statement", "query_error"])
async def test_paid_read_local_db_failures_are_bounded_and_do_not_poison_next_read(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    engine = factory.kw["bind"]
    config = paid_scenario[2].model_copy(update={"database_url": engine.url.render_as_string(hide_password=False)})
    user_id = paid_scenario[4]
    app = create_app()
    monkeypatch.setattr(paid_router, "settings", config)
    blocker_engine = create_engine(engine.url)
    before = billing_snapshot(factory)
    try:
        async with (
            paid_reads.paid_read_resources(config) as reads,
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://portal.test"
            ) as client,
        ):
            app.state.paid_reads = reads
            with blocker_engine.connect() as blocker, monkeypatch.context() as patch:
                transaction = blocker.begin()
                if failure in {"session", "user"}:
                    row = (
                        select(AuthSession.id).where(AuthSession.user_id == user_id)
                        if failure == "session"
                        else select(User.id).where(User.id == user_id)
                    )
                    blocker.execute(row.with_for_update())
                else:

                    def query_failure(db: Session, identities: object) -> list:
                        if failure == "statement":
                            db.execute(text("SET LOCAL statement_timeout='20ms'"))
                            db.execute(text("SELECT pg_sleep(0.1)"))
                        else:
                            db.execute(text("SELECT 1 / 0"))
                        raise AssertionError("the real PostgreSQL query must fail")

                    patch.setattr(paid_read.queries, "allowances", query_failure)
                response = await asyncio.wait_for(
                    client.get("/api/paid-access", headers={"Authorization": "Bearer " + TOKEN}), 4
                )
                transaction.rollback()
            status, code = (500, "internal_server_error") if failure == "query_error" else (503, "paid_access_busy")
            assert response.status_code == status and response.json()["detail"]["code"] == code
            assert response.headers["cache-control"] == "no-store"
            recovered = await client.get("/api/paid-access", headers={"Authorization": "Bearer " + TOKEN})
            assert recovered.status_code == 200 and recovered.json()["access_revision"] == 1
    finally:
        blocker_engine.dispose()
    assert billing_snapshot(factory) == before
