"""Reserved local cabinet capacity, independent of sale/source DB and threads."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

import anyio
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.paid_read import PaidRead, read_paid_access
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.preflight import PreflightCleanupPending

PAID_READ_CONCURRENCY = 2
PAID_READ_MAX_WAITING = 8


class PaidReadResources:
    def __init__(self, factory: SessionFactory, cleanup_timeout_seconds: float, engine: Engine | None = None) -> None:
        self.factory = factory
        self.cleanup_timeout_seconds = cleanup_timeout_seconds
        self.engine = engine
        self.limiter = anyio.CapacityLimiter(PAID_READ_CONCURRENCY)
        self.tasks: set[asyncio.Task[PaidRead]] = set()
        self.closed = False

    async def read(self, configuration: Settings, token: str) -> PaidRead:
        if self.closed or len(self.tasks) >= PAID_READ_CONCURRENCY + PAID_READ_MAX_WAITING:
            raise BillingRefused("paid_access_busy", 503)
        task = asyncio.create_task(
            anyio.to_thread.run_sync(
                partial(read_paid_access, self.factory, configuration, token), limiter=self.limiter
            )
        )
        self.tasks.add(task)

        def completed(owner: asyncio.Task[PaidRead]) -> None:
            self.tasks.discard(owner)
            if not owner.cancelled():
                owner.exception()

        task.add_done_callback(completed)
        # A cancelled HTTP waiter cannot release capacity or close the pool
        # while its resource-owning authentication/read unit is still running.
        try:
            return await asyncio.shield(task)
        except DBAPIError as error:
            # PostgreSQL lock/statement timeouts are bounded read contention.
            if getattr(error.orig, "sqlstate", None) in {"55P03", "57014"}:
                raise BillingRefused("paid_access_busy", 503) from None
            raise

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
async def paid_read_resources(
    configuration: Settings, *, factory: SessionFactory | None = None
) -> AsyncIterator[PaidReadResources]:
    engine = None
    if factory is None:
        options = {"pool_pre_ping": True}
        if configuration.database_url.startswith("postgresql"):
            options.update(
                pool_size=PAID_READ_CONCURRENCY,
                max_overflow=0,
                pool_timeout=2,
                connect_args={"options": "-c statement_timeout=10000 -c lock_timeout=2000"},
            )
        engine = create_engine(configuration.database_url, **options)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    reads = PaidReadResources(factory, configuration.preflight_cleanup_timeout_seconds, engine)
    try:
        yield reads
    finally:
        await reads.aclose()
