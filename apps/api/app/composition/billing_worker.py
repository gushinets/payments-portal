"""Embedded worker resources, isolated from request and new-sale pools."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import Settings
from app.domains.catalog.publication import SessionFactory
from app.domains.billing.work_contracts import WorkLane
from app.infrastructure.preflight import PreflightCleanupPending
from app.integrations.lbx.client import LbxServerClient
from app.jobs.billing import BillingWorker


@asynccontextmanager
async def billing_worker_resources(
    configuration: Settings,
    *,
    factory: SessionFactory | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[BillingWorker | None]:
    if not configuration.billing_worker_enabled or configuration.lbx_configuration_error is not None:
        yield None
        return
    engine = None
    if factory is None:
        options = {"pool_pre_ping": True}
        if configuration.database_url.startswith("postgresql"):
            options.update(
                pool_size=configuration.billing_worker_urgent_concurrency
                + configuration.billing_worker_normal_concurrency
                + 1,
                max_overflow=0,
                pool_timeout=2,
                connect_args={"options": "-c statement_timeout=10000 -c lock_timeout=2000"},
            )
        engine = create_engine(configuration.database_url, **options)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    client = LbxServerClient(configuration, transport=transport)
    worker = BillingWorker(configuration, factory, client)
    try:
        await worker.start()
        yield worker
    finally:
        # Do not close a client's pool underneath retained source cleanup.
        # A failed drain propagates and remains visible as degraded shutdown.
        await worker.aclose()
        try:
            async with asyncio.timeout(configuration.preflight_cleanup_timeout_seconds):
                await client.aclose()
        except TimeoutError:
            worker.failed = True
            raise PreflightCleanupPending() from None
        if engine is not None:
            await worker.db(WorkLane.LOCAL, engine.dispose)
