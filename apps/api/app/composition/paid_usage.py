"""Independent bounded cabinet usage: local select → remote I/O → local recheck."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import partial

import httpx
from sqlalchemy.exc import SQLAlchemyError

from app.composition.allowance_usage import usage_backend
from app.composition.paid_reads import PaidReadResources, paid_read_resources
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.paid_usage import UsageAllowance, select_paid_usage
from app.domains.billing.usage_contracts import (
    ObservedPaidUsage, PaidUsageItem, PaidUsageResponse, PaidUsageStatus, UnavailablePaidUsage, UnobservedPaidUsage,
)
from app.domains.catalog.contracts import SourceProvenance
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.preflight import PreflightAdmission, PreflightCleanupPending, PreflightPolicy
from app.integrations.kernel.client import ManifestConnection, PlatformKernelClient
from app.integrations.kernel.usage import ObservedUsage

logger = logging.getLogger(__name__)
USAGE_CONCURRENCY = 2
USAGE_MAX_WAITING = 4
USAGE_BATCH_SIZE = 100


class PaidUsageResources:
    def __init__(
        self, local: PaidReadResources, admission: PreflightAdmission,
        clients: dict[str, PlatformKernelClient],
    ) -> None:
        self.local = local
        self.admission = admission
        self.clients = clients

    async def read(self, configuration: Settings, token: str) -> PaidUsageResponse:
        try:
            async with self.admission.operation(bound_scope=False) as budget:
                select = partial(select_paid_usage, self.local.factory, configuration, token)
                selection = await self.local.run(select)
                budget.check()
                groups: dict[str, list[UsageAllowance]] = {}
                for item in selection.items:
                    consumer = usage_backend(configuration, item.ownership, item.product_id)
                    groups.setdefault(consumer.consumer_id, []).append(item)
                results: dict[str, PaidUsageItem] = {}
                for owner, items in groups.items():
                    for offset in range(0, len(items), USAGE_BATCH_SIZE):
                        batch = items[offset:offset + USAGE_BATCH_SIZE]
                        response = await self.clients[owner].fetch_usage(
                            selection.user_id, tuple(item.allowance_id for item in batch), budget=budget,
                        )
                        for local, remote in zip(batch, response.items, strict=True):
                            fields = dict(
                                allowance_id=str(local.allowance_id), product_id=local.product_id,
                                metric_key=local.metric_key, unit=local.unit, quantity=local.quantity,
                                classification=local.classification,
                            )
                            if not isinstance(remote, ObservedUsage):
                                result = UnobservedPaidUsage(**fields, status=PaidUsageStatus.UNOBSERVED)
                            elif (remote.product_id, remote.metric_key, remote.unit, remote.quantity) != (
                                local.product_id, local.metric_key, local.unit, local.quantity,
                            ):
                                logger.warning("paid_usage_tuple_mismatch", extra={"allowance_id": str(local.allowance_id)})
                                result = UnavailablePaidUsage(**fields, status=PaidUsageStatus.UNAVAILABLE)
                            else:
                                result = ObservedPaidUsage(
                                    **fields, status=PaidUsageStatus.OBSERVED,
                                    successful_used=remote.successful_used, reserved=remote.reserved,
                                    remaining=remote.remaining, available=remote.available, read_at=remote.read_at,
                                )
                            results[str(local.allowance_id)] = result
                # Fresh session authentication also prevents a logout/deactivation
                # during slow I/O from disclosing a completed usage response.
                rechecked = await self.local.run(select)
                if rechecked != selection:
                    raise BillingRefused("paid_usage_state_changed", 503)
                budget.check()
                return PaidUsageResponse(
                    access_revision=selection.revision,
                    items=[results[str(item.allowance_id)] for item in selection.items],
                )
        except BillingRefused:
            raise
        except (AppError, SQLAlchemyError) as error:
            logger.warning("paid_usage_unavailable", extra={"error_code": getattr(error, "code", "storage_unavailable")})
            raise BillingRefused("paid_usage_unavailable", 503) from None


@asynccontextmanager
async def paid_usage_resources(
    configuration: Settings, *, factory: SessionFactory | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[PaidUsageResources]:
    # A separate engine, thread limiter, admission and HTTP pools: never borrow
    # /paid-access capacity or the sale/worker source lanes.
    admission = PreflightAdmission(PreflightPolicy(
        configuration.preflight_total_timeout_seconds, configuration.preflight_cleanup_timeout_seconds,
        USAGE_CONCURRENCY, USAGE_MAX_WAITING,
    ))
    clients = {
        consumer.consumer_id: PlatformKernelClient(
            configuration, provenance=SourceProvenance.CONFIGURED_SOURCE,
            connection=ManifestConnection(consumer.backend_base_url, consumer.portal_to_backend_current_secret),
            max_connections=USAGE_CONCURRENCY, transport=transport,
        )
        for consumer in configuration.backend_consumers
    }
    async with paid_read_resources(configuration, factory=factory) as local:
        try:
            yield PaidUsageResources(local, admission, clients)
        finally:
            # An unfinished transport cleanup keeps its owner/pool alive.
            await admission.aclose()
            try:
                async with asyncio.timeout(configuration.preflight_cleanup_timeout_seconds):
                    for client in clients.values():
                        await client.aclose()
            except TimeoutError:
                raise PreflightCleanupPending() from None
