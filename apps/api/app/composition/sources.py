from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from app.core.settings import Settings
from app.domains.catalog.contracts import SourceProvenance
from app.infrastructure.preflight import PreflightAdmission, PreflightCleanupPending, PreflightPolicy
from app.integrations.kernel.client import KernelNotConfigured, PlatformKernelClient


@dataclass(frozen=True)
class SourceResources:
    preflight: PreflightAdmission
    kernel: PlatformKernelClient | None

    def require_kernel(self) -> PlatformKernelClient:
        if self.kernel is None:
            raise KernelNotConfigured()
        return self.kernel


@asynccontextmanager
async def source_resources(
    configuration: Settings,
    *,
    kernel_transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[SourceResources]:
    """Compose once per process/app lifespan; also reusable by the future CLI.

    Only explicit dev/test configuration permits a provisional counterpart.
    Provenance is assigned here, never derived from its URL or wire response.
    Real conformance/enablement is deferred; even a different URL stays SIMULATED.
    No client/pool is initialized at all for an unconfigured source.
    """
    admission = PreflightAdmission(
        PreflightPolicy(
            total_timeout_seconds=configuration.preflight_total_timeout_seconds,
            cleanup_timeout_seconds=configuration.preflight_cleanup_timeout_seconds,
            max_active=configuration.preflight_max_active,
            max_waiting=configuration.preflight_max_waiting,
        )
    )
    kernel = (
        PlatformKernelClient(configuration, provenance=SourceProvenance.SIMULATED, transport=kernel_transport)
        if configuration.kernel_base_url
        else None
    )
    try:
        yield SourceResources(admission, kernel)
    finally:
        # Pending source cleanup still owns this client's HTTP resources.
        # Propagate the bounded drain failure without closing underneath it.
        await admission.aclose()
        if kernel is not None:
            try:
                async with asyncio.timeout(configuration.preflight_cleanup_timeout_seconds):
                    await kernel.aclose()
            except TimeoutError:
                raise PreflightCleanupPending() from None
