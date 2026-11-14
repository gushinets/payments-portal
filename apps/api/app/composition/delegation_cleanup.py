"""Small dedicated database pool for session-delegation retention."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import anyio

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.settings import Settings
from app.domains.catalog.publication import SessionFactory
from app.jobs.delegation_cleanup import DelegationCleanup


@asynccontextmanager
async def delegation_cleanup_resources(
    configuration: Settings, *, factory: SessionFactory | None = None
) -> AsyncIterator[DelegationCleanup]:
    engine = None
    if factory is None:
        options = {"pool_pre_ping": True}
        if configuration.database_url.startswith("postgresql"):
            options.update(
                pool_size=1,
                max_overflow=0,
                pool_timeout=2,
                connect_args={"options": "-c statement_timeout=10000 -c lock_timeout=2000"},
            )
        engine = create_engine(configuration.database_url, **options)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    worker = DelegationCleanup(
        factory,
        tenant_id=configuration.instance_tenant_id,
        region=configuration.instance_region,
        cleanup_timeout=configuration.preflight_cleanup_timeout_seconds,
    )
    try:
        worker.start()
        yield worker
    finally:
        await worker.aclose()
        if engine is not None:
            await anyio.to_thread.run_sync(engine.dispose)
