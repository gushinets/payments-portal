from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from app.core.settings import Settings
from app.core.errors import AppError
from app.domains.catalog.contracts import SourceProvenance
from app.infrastructure.preflight import PreflightAdmission, PreflightCleanupPending, PreflightPolicy
from app.integrations.kernel.client import KernelNotConfigured, PlatformKernelClient
from app.integrations.lbx.client import LbxServerClient


@dataclass(frozen=True)
class SourceResources:
    preflight: PreflightAdmission
    kernel: PlatformKernelClient | None
    lbx: LbxServerClient | None = None
    lbx_error: str | None = None
    billing: PreflightAdmission | None = None

    def require_kernel(self) -> PlatformKernelClient:
        if self.kernel is None:
            raise KernelNotConfigured()
        return self.kernel

    def require_lbx(self) -> LbxServerClient:
        if self.lbx is None:
            raise AppError(self.lbx_error or "lbx_not_configured")
        return self.lbx


@asynccontextmanager
async def source_resources(
    configuration: Settings,
    *,
    kernel_transport: httpx.AsyncBaseTransport | None = None,
    lbx_transport: httpx.AsyncBaseTransport | None = None,
) -> AsyncIterator[SourceResources]:
    """Compose once per app lifespan or normal operator CLI operation.

    Only explicit dev/test configuration permits a provisional counterpart.
    Provenance is assigned here, never derived from its URL or wire response.
    The explicit development mock remains SIMULATED through URL changes.
    Other configured endpoints are CONFIGURED_SOURCE, never conformance approval.
    No client/pool is initialized at all for an unconfigured source.
    Admission limits are process-local. The operator CLI acquires its shared
    local file lock before entering this resource scope and holds it through DB.
    """
    admission = PreflightAdmission(
        PreflightPolicy(
            total_timeout_seconds=configuration.preflight_total_timeout_seconds,
            cleanup_timeout_seconds=configuration.preflight_cleanup_timeout_seconds,
            max_active=configuration.preflight_max_active,
            max_waiting=configuration.preflight_max_waiting,
        )
    )
    billing = PreflightAdmission(
        PreflightPolicy(
            total_timeout_seconds=configuration.preflight_total_timeout_seconds,
            cleanup_timeout_seconds=configuration.preflight_cleanup_timeout_seconds,
            max_active=2,
            max_waiting=4,
        )
    )
    kernel = (
        PlatformKernelClient(
            configuration,
            provenance=(
                SourceProvenance.SIMULATED if configuration.kernel_mock_enabled else SourceProvenance.CONFIGURED_SOURCE
            ),
            transport=kernel_transport,
        )
        if configuration.kernel_base_url
        else None
    )
    lbx_error = configuration.lbx_configuration_error
    lbx = LbxServerClient(configuration, transport=lbx_transport) if lbx_error is None else None
    try:
        yield SourceResources(admission, kernel, lbx, lbx_error, billing)
    finally:
        # Pending source cleanup still owns this client's HTTP resources.
        # Propagate the bounded drain failure without closing underneath it.
        await billing.aclose()
        await admission.aclose()
        try:
            async with asyncio.timeout(configuration.preflight_cleanup_timeout_seconds):
                results = await asyncio.gather(
                    *(client.aclose() for client in (kernel, lbx) if client is not None),
                    return_exceptions=True,
                )
        except TimeoutError:
            raise PreflightCleanupPending() from None
        if any(isinstance(result, BaseException) for result in results):
            raise PreflightCleanupPending()
