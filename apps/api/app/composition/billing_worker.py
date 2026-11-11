"""Embedded worker resources, isolated from request and new-sale pools."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.backend_consumers import BackendPermission
from app.core.settings import Settings
from app.domains.catalog.publication import SessionFactory
from app.domains.catalog.contracts import SourceProvenance
from app.domains.billing.work_contracts import WorkLane
from app.infrastructure.preflight import PreflightCleanupPending
from app.integrations.lbx.client import LbxServerClient
from app.integrations.kernel.client import ManifestConnection, PlatformKernelClient
from app.jobs.billing import BillingWorker


@asynccontextmanager
async def billing_worker_resources(
    configuration: Settings,
    *,
    factory: SessionFactory | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
    invalidation_transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[BillingWorker | None]:
    if not configuration.billing_worker_enabled:
        yield None
        return
    source_concurrency = (
        configuration.billing_worker_urgent_concurrency + configuration.billing_worker_normal_concurrency
    )
    recipients = tuple(
        consumer
        for consumer in configuration.backend_consumers
        if BackendPermission.READ_SNAPSHOT in consumer.permissions
    )
    delivery_concurrency = len(recipients) * configuration.billing_worker_delivery_concurrency
    engine = None
    if factory is None:
        options = {"pool_pre_ping": True}
        if configuration.database_url.startswith("postgresql"):
            options.update(
                pool_size=source_concurrency + delivery_concurrency + 1,
                max_overflow=0,
                pool_timeout=2,
                connect_args={"options": "-c statement_timeout=10000 -c lock_timeout=2000"},
            )
        engine = create_engine(configuration.database_url, **options)
        factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    # Each admitted source owner makes one HTTP call at a time. Both HTTP pools
    # must fit all normal and urgent owners, including retained cleanup slots.
    client = (
        LbxServerClient(configuration, transport=transport, max_connections=source_concurrency)
        if configuration.lbx_configuration_error is None
        else None
    )
    delivery_clients = {
        consumer.consumer_id: PlatformKernelClient(
            configuration,
            provenance=SourceProvenance.CONFIGURED_SOURCE,
            transport=invalidation_transport,
            max_connections=configuration.billing_worker_delivery_concurrency,
            connection=ManifestConnection(consumer.backend_base_url, consumer.portal_to_backend_current_secret),
        )
        for consumer in recipients
    }
    worker = BillingWorker(configuration, factory, client, delivery_clients=delivery_clients)
    try:
        await worker.start()
        yield worker
    finally:
        # Do not close a client's pool underneath retained source cleanup.
        # A failed drain propagates and remains visible as degraded shutdown.
        await worker.aclose()
        if client is not None:
            try:
                async with asyncio.timeout(configuration.preflight_cleanup_timeout_seconds):
                    await client.aclose()
            except TimeoutError:
                worker.failed = True
                raise PreflightCleanupPending() from None
        for delivery_client in delivery_clients.values():
            try:
                async with asyncio.timeout(configuration.preflight_cleanup_timeout_seconds):
                    await delivery_client.aclose()
            except TimeoutError:
                worker.failed = True
                raise PreflightCleanupPending() from None
        if engine is not None:
            await worker.db(WorkLane.LOCAL, engine.dispose)
