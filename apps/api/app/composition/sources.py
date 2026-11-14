from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

import httpx

from app.core.settings import Settings
from app.core.errors import AppError
from app.domains.catalog.contracts import SourceProvenance
from app.domains.catalog.technical_source import LEGACY_KERNEL_OWNERSHIP, TechnicalOwnership
from app.infrastructure.preflight import PreflightAdmission, PreflightCleanupPending, PreflightPolicy
from app.integrations.kernel.client import KernelNotConfigured, ManifestConnection, PlatformKernelClient
from app.integrations.lbx.client import LbxServerClient


class TechnicalSourceRefused(AppError):
    def __init__(self) -> None:
        super().__init__("technical_source_ownership_unavailable")


@dataclass(frozen=True)
class TechnicalSource:
    ownership: TechnicalOwnership
    products: frozenset[str] | None
    client: PlatformKernelClient


@dataclass(frozen=True)
class SourceResources:
    preflight: PreflightAdmission
    kernel: PlatformKernelClient | None
    lbx: LbxServerClient | None = None
    lbx_error: str | None = None
    billing: PreflightAdmission | None = None
    technical_sources: tuple[TechnicalSource, ...] = ()

    def technical_source(self, product_id: str, *, expected: TechnicalOwnership | None = None) -> TechnicalSource:
        if self.technical_sources:
            source = next(
                (item for item in self.technical_sources if item.products is None or product_id in item.products), None
            )
            if source is None:
                raise TechnicalSourceRefused()
        else:
            source = TechnicalSource(LEGACY_KERNEL_OWNERSHIP, None, self.require_kernel())
        if expected is not None and source.ownership != expected:
            raise TechnicalSourceRefused()
        return source

    def discovery_sources(self) -> tuple[TechnicalSource, ...]:
        return self.technical_sources or (TechnicalSource(LEGACY_KERNEL_OWNERSHIP, None, self.require_kernel()),)

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
    technical_sources = tuple(
        TechnicalSource(
            TechnicalOwnership(consumer.technical_source_id, consumer.consumer_id),
            consumer.allowed_products,
            PlatformKernelClient(
                configuration,
                provenance=(
                    SourceProvenance.SIMULATED
                    if consumer.consumer_id == "platform-kernel" and configuration.kernel_mock_enabled
                    else SourceProvenance.CONFIGURED_SOURCE
                ),
                connection=ManifestConnection(consumer.backend_base_url, consumer.portal_to_backend_current_secret),
                transport=kernel_transport,
            ),
        )
        for consumer in configuration.backend_consumers
    )
    lbx_error = configuration.lbx_configuration_error
    lbx = LbxServerClient(configuration, transport=lbx_transport) if lbx_error is None else None
    try:
        yield SourceResources(admission, kernel, lbx, lbx_error, billing, technical_sources)
    finally:
        # Pending source cleanup still owns this client's HTTP resources.
        # Propagate the bounded drain failure without closing underneath it.
        await billing.aclose()
        await admission.aclose()
        try:
            async with asyncio.timeout(configuration.preflight_cleanup_timeout_seconds):
                results = await asyncio.gather(
                    *(
                        client.aclose()
                        for client in (kernel, lbx, *(item.client for item in technical_sources))
                        if client is not None
                    ),
                    return_exceptions=True,
                )
        except TimeoutError:
            raise PreflightCleanupPending() from None
        if any(isinstance(result, BaseException) for result in results):
            raise PreflightCleanupPending()
