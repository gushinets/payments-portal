"""Reserved read-only identity capacity, independent of purchase and cabinet work."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

import anyio
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from app.core.backend_consumers import BackendConsumer
from app.core.settings import Settings
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.backend_delegation import (
    DelegatedIdentity,
    DelegationUnavailableError,
    InvalidDelegationError,
    read_delegated_identity,
)
from app.infrastructure.preflight import PreflightCleanupPending
from app.infrastructure.sentry import Operation, report_exception

INTROSPECTION_CONCURRENCY = 2
INTROSPECTION_MAX_WAITING = 8
# Leave transport time within Kernel's existing two-second identity timeout.
INTROSPECTION_TIMEOUT_SECONDS = 1.5


class BackendIntrospectionResources:
    def __init__(self, factory: SessionFactory, cleanup_timeout_seconds: float, engine: Engine | None = None) -> None:
        self.factory = factory
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self.engine = engine
        self.limiter = anyio.CapacityLimiter(INTROSPECTION_CONCURRENCY)
        self.tasks: set[asyncio.Task[DelegatedIdentity]] = set()
        self.closed = False

    async def introspect(self, configuration: Settings, consumer: BackendConsumer, token: str) -> DelegatedIdentity:
        clock_skew_seconds = configuration.paid_access_clock_skew_seconds
        if (
            clock_skew_seconds is None
            or self.closed
            or len(self.tasks) >= INTROSPECTION_CONCURRENCY + INTROSPECTION_MAX_WAITING
        ):
            raise DelegationUnavailableError()
        task = asyncio.create_task(
            anyio.to_thread.run_sync(
                partial(read_delegated_identity, self.factory, consumer, token, clock_skew_seconds),
                limiter=self.limiter,
            )
        )
        self.tasks.add(task)
        detached = False
        reported = False

        def completed(owner: asyncio.Task[DelegatedIdentity]) -> None:
            nonlocal reported
            self.tasks.discard(owner)
            if not owner.cancelled():
                error = owner.exception()
                if (
                    detached
                    and not reported
                    and error is not None
                    and not isinstance(error, (InvalidDelegationError, DelegationUnavailableError))
                ):
                    # The HTTP boundary can no longer report a later owner failure.
                    reported = True
                    report_exception(error, operation=Operation.BACKEND_INTROSPECTION)

        task.add_done_callback(completed)
        try:
            async with asyncio.timeout(INTROSPECTION_TIMEOUT_SECONDS):
                # Cancellation/timeout of HTTP cannot free an executing DB owner
                # or permit shutdown to dispose its connection prematurely.
                return await asyncio.shield(task)
        except TimeoutError:
            detached = True
            raise DelegationUnavailableError() from None
        except asyncio.CancelledError:
            detached = True
            raise
        finally:
            if detached and task.done():
                # Completion may precede detachment; a scheduled callback may
                # also still run afterward. Both paths share the reporting guard.
                completed(task)

    async def aclose(self) -> None:
        self.closed = True
        if self.tasks:
            _, pending = await asyncio.wait(self.tasks, timeout=self.cleanup_timeout_seconds)
            if pending:
                raise PreflightCleanupPending()
        if self.engine is not None:
            await anyio.to_thread.run_sync(self.engine.dispose, limiter=self.limiter)
            self.engine = None


@asynccontextmanager
async def backend_introspection_resources(
    configuration: Settings, *, factory: SessionFactory | None = None
) -> AsyncIterator[BackendIntrospectionResources]:
    engine = None
    if factory is None:
        options = {"pool_pre_ping": True}
        if configuration.database_url.startswith("postgresql"):
            options.update(
                pool_size=INTROSPECTION_CONCURRENCY,
                max_overflow=0,
                pool_timeout=0.25,
                connect_args={"connect_timeout": 1, "options": "-c statement_timeout=500 -c lock_timeout=250"},
            )
        engine = create_engine(configuration.database_url, **options)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    reads = BackendIntrospectionResources(factory, configuration.preflight_cleanup_timeout_seconds, engine)
    try:
        yield reads
    finally:
        await reads.aclose()
