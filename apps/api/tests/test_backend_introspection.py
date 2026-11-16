"""Bounded identity admission and ownership across HTTP cancellation/timeouts."""

import asyncio
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

import anyio
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.engine import Connection, Engine, ExecutionContext
from sqlalchemy.orm import Session, sessionmaker

from app.composition import backend_introspection as composition
from app.composition.backend_consumers import initialize_backend_consumers
from app.core.backend_consumers import BackendConsumer
from app.core.database import Base
from app.core.settings import Settings
from app.domains.identity.services import backend_delegation as delegation
from app.infrastructure.preflight import PreflightCleanupPending
from app.models import AuthSession, User, UserStatus
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.backend_consumers import backend_consumer

pytestmark = pytest.mark.anyio
type IntrospectionCase = tuple[Settings, BackendConsumer, Engine, sessionmaker[Session], str]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def identity(tmp_path: Path) -> Iterator[IntrospectionCase]:
    consumer = backend_consumer()
    config = step1_settings(backend_consumers=(consumer,), paid_access_clock_skew_seconds=5)
    engine = create_engine(f"sqlite+pysqlite:///{tmp_path / 'identity.db'}")
    factory = sessionmaker(bind=engine, autoflush=False)
    try:
        Base.metadata.create_all(engine)
        initialize_backend_consumers(config, factory)
        with factory() as db:
            user = User(
                tenant_id="anytoolai",
                region="ru",
                email="capacity@example.invalid",
                email_normalized="capacity@example.invalid",
                status=UserStatus.ACTIVE,
                email_verified_at=datetime.now(UTC),
            )
            db.add(user)
            db.flush()
            db.add(
                AuthSession(
                    user_id=user.id,
                    tenant_id=user.tenant_id,
                    region=user.region,
                    token_hash=delegation.credential_hash("p" * 43),
                    expires_at=datetime.now(UTC) + timedelta(hours=1),
                )
            )
            db.commit()
            code = delegation.issue_code(
                db,
                token="p" * 43,
                tenant_id="anytoolai",
                region="ru",
                code_challenge=delegation.pkce_challenge("v" * 43),
                consumer_id=consumer.consumer_id,
            )
            token = delegation.exchange_code(
                db,
                code=code.code,
                verifier="v" * 43,
                tenant_id="anytoolai",
                region="ru",
                consumer_id=consumer.consumer_id,
            ).access_token
        yield config, consumer, engine, factory, token
    finally:
        engine.dispose()


def hold_policy_reads(engine: Engine, release: Event, *, fail: bool = False) -> None:
    def before_cursor_execute(
        connection: Connection,
        cursor: object,
        statement: str,
        parameters: object,
        context: ExecutionContext,
        executemany: bool,
    ) -> None:
        if "FROM backend_consumer_policies" in statement:
            assert release.wait(5), "Test did not release the database owner"
            if fail:
                raise RuntimeError("Synthetic owner failure after HTTP ended")

    event.listen(engine, "before_cursor_execute", before_cursor_execute)


@pytest.mark.parametrize("finish", ["cancel", "timeout"])
@pytest.mark.parametrize("fail", [False, True])
async def test_http_waiter_cannot_release_running_capacity_or_dispose_pool(
    identity: IntrospectionCase,
    monkeypatch: pytest.MonkeyPatch,
    finish: str,
    fail: bool,
) -> None:
    config, consumer, engine, factory, token = identity
    release = Event()
    hold_policy_reads(engine, release, fail=fail)
    reports: list[Exception] = []
    monkeypatch.setattr(composition, "report_exception", lambda error, **kwargs: reports.append(error))
    disposed: list[Engine] = []
    event.listen(engine, "engine_disposed", disposed.append)
    monkeypatch.setattr(composition, "INTROSPECTION_TIMEOUT_SECONDS", 0.1 if finish == "timeout" else 3)
    reads = composition.BackendIntrospectionResources(factory, cleanup_timeout_seconds=0.01, engine=engine)
    callers = [asyncio.create_task(reads.introspect(config, consumer, token)) for _ in range(2)]
    try:
        async with asyncio.timeout(3):
            while reads.limiter.borrowed_tokens != 2 or engine.pool.checkedout() != 2:
                await asyncio.sleep(0.001)
        if finish == "cancel":
            for caller in callers:
                caller.cancel()
            for caller in callers:
                with pytest.raises(asyncio.CancelledError):
                    await caller
        else:
            for caller in callers:
                with pytest.raises(delegation.DelegationUnavailableError):
                    await caller
        assert len(reads.tasks) == 2 and reads.limiter.borrowed_tokens == 2
        with pytest.raises(PreflightCleanupPending):
            await reads.aclose()
        assert not disposed and reads.engine is engine
        with pytest.raises(delegation.DelegationUnavailableError):
            await reads.introspect(config, consumer, token)
    finally:
        release.set()
        await asyncio.gather(*callers, return_exceptions=True)
        reads.cleanup_timeout_seconds = 3
        await reads.aclose()
    assert not reads.tasks and reads.engine is None
    assert disposed == [engine]
    assert len(reports) == 2 * int(fail)


@pytest.mark.parametrize("cancel_before_callback", [False, True])
async def test_cancellation_at_owner_completion_reports_failure_once(
    identity: IntrospectionCase,
    monkeypatch: pytest.MonkeyPatch,
    cancel_before_callback: bool,
) -> None:
    config, consumer, engine, factory, token = identity
    release = Event()
    hold_policy_reads(engine, release, fail=True)
    reports: list[Exception] = []
    monkeypatch.setattr(composition, "report_exception", lambda error, **kwargs: reports.append(error))
    monkeypatch.setattr(composition, "INTROSPECTION_TIMEOUT_SECONDS", 5)
    if cancel_before_callback:
        run_sync = anyio.to_thread.run_sync

        async def cancel_at_worker_return(
            operation: Callable[[], delegation.DelegatedIdentity], *, limiter: anyio.CapacityLimiter
        ) -> delegation.DelegatedIdentity:
            try:
                return await run_sync(operation, limiter=limiter)
            finally:
                # The real SQL unit has finished; wake cancellation before its
                # completion callback gets a turn on the event loop.
                caller.cancel()

        monkeypatch.setattr(anyio.to_thread, "run_sync", cancel_at_worker_return)
    reads = composition.BackendIntrospectionResources(factory, cleanup_timeout_seconds=3)
    caller = asyncio.create_task(reads.introspect(config, consumer, token))
    try:
        async with asyncio.timeout(3):
            while engine.pool.checkedout() != 1:
                await asyncio.sleep(0.001)
        owner = next(iter(reads.tasks))
        if not cancel_before_callback:
            # Cancel after the owner's completion handler, before the waiter can
            # receive its exception. The HTTP boundary cannot report this failure.
            owner.add_done_callback(lambda _: caller.cancel())
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await caller
        await reads.aclose()
        assert isinstance(owner.exception(), RuntimeError)
        assert reports == [owner.exception()]
    finally:
        release.set()
        await asyncio.gather(caller, return_exceptions=True)
        await reads.aclose()


async def test_identity_queue_is_bounded_and_recovers(
    identity: IntrospectionCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, consumer, engine, factory, token = identity
    release = Event()
    hold_policy_reads(engine, release)
    monkeypatch.setattr(composition, "INTROSPECTION_TIMEOUT_SECONDS", 3)
    reads = composition.BackendIntrospectionResources(factory, cleanup_timeout_seconds=3)
    callers = [asyncio.create_task(reads.introspect(config, consumer, token)) for _ in range(10)]
    try:
        async with asyncio.timeout(3):
            while len(reads.tasks) != 10 or engine.pool.checkedout() != 2:
                await asyncio.sleep(0.001)
        with pytest.raises(delegation.DelegationUnavailableError):
            await reads.introspect(config, consumer, token)
    finally:
        release.set()
        results = await asyncio.gather(*callers)
        await reads.aclose()
    assert all(result.tenant_id == "anytoolai" and result.region == "ru" for result in results)
    assert len({result.user_id for result in results}) == 1
