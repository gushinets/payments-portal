from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any

import httpx
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.catalog.contracts import (
    CapabilityManifest,
    CapabilityMetric,
    CapabilityProduct,
    SourceProvenance,
)
from app.infrastructure.preflight import PreflightBudget


MANIFEST_PATH = "/internal/v1/capability-manifest"
NonemptyString = Annotated[str, Field(min_length=1)]
_DATE_TIME = re.compile(r"^\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[Zz]|[+-]\d{2}:\d{2})$")


class KernelError(AppError):
    """Safe semantic failure; remote payloads/URLs/headers are never attached."""


class KernelNotConfigured(KernelError):
    def __init__(self) -> None:
        super().__init__("kernel_not_configured")


class KernelAuthenticationFailed(KernelError):
    def __init__(self) -> None:
        super().__init__("kernel_authentication_failed")


class KernelScopeForbidden(KernelError):
    def __init__(self) -> None:
        super().__init__("kernel_scope_forbidden")


class KernelScopeMismatch(KernelError):
    def __init__(self) -> None:
        super().__init__("kernel_scope_mismatch")


class KernelManifestInvalid(KernelError):
    def __init__(self) -> None:
        super().__init__("kernel_manifest_invalid")


class KernelUnavailable(KernelError):
    def __init__(self) -> None:
        super().__init__("kernel_unavailable")


class KernelTimeout(KernelError):
    def __init__(self) -> None:
        super().__init__("kernel_timeout")


class _WireModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


class _ProductV1(_WireModel):
    product_id: NonemptyString
    enabled: bool


class _MetricV1(_WireModel):
    metric_key: NonemptyString
    product_id: NonemptyString
    unit: NonemptyString
    enabled: bool


class _ManifestV1(_WireModel):
    schema_version: Annotated[int, Field(ge=1, le=1)]
    tenant_id: NonemptyString
    region: NonemptyString
    manifest_version: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    generated_at: AwareDatetime
    products: list[_ProductV1]
    usage_metrics: list[_MetricV1]

    @field_validator("generated_at", mode="before")
    @classmethod
    def require_wire_date_time(cls, value: Any) -> datetime:
        if not isinstance(value, str) or not _DATE_TIME.fullmatch(value):
            raise ValueError("generated_at must be a timezone-aware date-time string")
        return datetime.fromisoformat(value.upper().replace("Z", "+00:00"))


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-JSON number")


def _decode_manifest(
    body: bytes,
    *,
    tenant_id: str,
    region: str,
    provenance: SourceProvenance,
) -> CapabilityManifest:
    try:
        raw = json.loads(body.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_constant)
        wire = _ManifestV1.model_validate(raw)
    except (ValueError, RecursionError):
        raise KernelManifestInvalid() from None
    if (wire.tenant_id, wire.region) != (tenant_id, region):
        raise KernelScopeMismatch()
    products = {item.product_id for item in wire.products}
    metrics = {item.metric_key for item in wire.usage_metrics}
    if (
        len(products) != len(wire.products)
        or len(metrics) != len(wire.usage_metrics)
        or any(item.product_id not in products for item in wire.usage_metrics)
    ):
        raise KernelManifestInvalid()
    # Provisional serialization, independently pinned by Step 1's literal hash.
    semantic = {
        "schema_version": wire.schema_version,
        "tenant_id": wire.tenant_id,
        "region": wire.region,
        "products": [item.model_dump() for item in sorted(wire.products, key=lambda item: item.product_id)],
        "usage_metrics": [item.model_dump() for item in sorted(wire.usage_metrics, key=lambda item: item.metric_key)],
    }
    try:
        canonical = json.dumps(semantic, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    except UnicodeError:
        raise KernelManifestInvalid() from None
    if wire.manifest_version != "sha256:" + hashlib.sha256(canonical).hexdigest():
        raise KernelManifestInvalid()
    return CapabilityManifest(
        schema_version=wire.schema_version,
        tenant_id=wire.tenant_id,
        region=wire.region,
        manifest_version=wire.manifest_version,
        generated_at=wire.generated_at,
        products=tuple(CapabilityProduct(item.product_id, item.enabled) for item in wire.products),
        usage_metrics=tuple(
            CapabilityMetric(item.metric_key, item.product_id, item.unit, item.enabled) for item in wire.usage_metrics
        ),
        provenance=provenance,
    )


class _CleanupProtectedStream(httpx.AsyncByteStream):
    """Protect actual stream cleanup, including HTTPX's automatic close at EOF."""

    def __init__(self, stream: httpx.AsyncByteStream, budget: PreflightBudget) -> None:
        self._stream = stream
        self._budget = budget

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for fragment in self._stream:
            yield fragment

    async def aclose(self) -> None:
        with self._budget.protect_source_cleanup():
            await self._stream.aclose()


class PlatformKernelClient:
    """One lifespan-owned async HTTP pool; no construction/startup fetch or LKG.

    Only genuine outer HTTP I/O is async. Application admission and all DB work
    remain synchronous, outside this client's operation. Inject a transport for
    isolated HTTP tests, never an alternate parser or mock business path.
    """

    def __init__(
        self,
        configuration: Settings,
        *,
        provenance: SourceProvenance,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not configuration.kernel_base_url:
            raise KernelNotConfigured()
        self._configuration = configuration
        self._provenance = provenance
        self._http = httpx.AsyncClient(
            base_url=configuration.kernel_base_url,
            headers={
                "Authorization": f"Bearer {configuration.kernel_service_token.get_secret_value()}",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache, no-store",
            },
            follow_redirects=False,
            trust_env=False,
            limits=httpx.Limits(
                max_connections=configuration.preflight_max_active,
                max_keepalive_connections=configuration.preflight_max_active,
            ),
            transport=transport,
        )

    async def fetch_manifest(self, *, budget: PreflightBudget) -> CapabilityManifest:
        config = self._configuration
        for attempt in range(config.kernel_max_retries + 1):
            try:
                return await budget.run(lambda: self._read_once(budget))
            except (KernelUnavailable, KernelTimeout):
                if attempt == config.kernel_max_retries:
                    raise
                await budget.run(lambda: asyncio.sleep(config.kernel_retry_delay_seconds))
        raise AssertionError("unreachable retry bound")

    async def _read_once(self, budget: PreflightBudget) -> CapabilityManifest:
        config = self._configuration
        remaining = budget.remaining_seconds()
        timeout = httpx.Timeout(
            connect=min(remaining, config.kernel_connect_timeout_seconds),
            read=min(remaining, config.kernel_read_timeout_seconds),
            write=min(remaining, config.kernel_connect_timeout_seconds),
            pool=min(remaining, config.kernel_connect_timeout_seconds),
        )
        try:
            async with self._http.stream(
                "GET",
                MANIFEST_PATH,
                params={"tenant_id": config.instance_tenant_id, "region": config.instance_region},
                timeout=timeout,
            ) as response:
                # aiter_bytes() also closes at EOF, before the context manager's
                # exit. Protect that first close in the already-counted source
                # task; retrying Response.aclose() after cancellation is unsafe.
                assert isinstance(response.stream, httpx.AsyncByteStream)
                response.stream = _CleanupProtectedStream(response.stream, budget)
                budget.check()
                if response.status_code == 401:
                    raise KernelAuthenticationFailed()
                if response.status_code == 403:
                    raise KernelScopeForbidden()
                if 500 <= response.status_code <= 599:
                    raise KernelUnavailable()
                if response.status_code != 200:
                    raise KernelManifestInvalid()
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise KernelManifestInvalid()
                # Reject compression so the byte ceiling also bounds decoding.
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise KernelManifestInvalid()
                length = response.headers.get("content-length")
                if length is not None:
                    try:
                        declared_size = int(length)
                    except ValueError:
                        raise KernelManifestInvalid() from None
                    if not 0 <= declared_size <= config.kernel_max_response_bytes:
                        raise KernelManifestInvalid()
                body = bytearray()
                async for fragment in response.aiter_bytes():
                    budget.check()
                    if len(body) + len(fragment) > config.kernel_max_response_bytes:
                        raise KernelManifestInvalid()
                    body.extend(fragment)
                budget.check()
                manifest = _decode_manifest(
                    bytes(body),
                    tenant_id=config.instance_tenant_id,
                    region=config.instance_region,
                    provenance=self._provenance,
                )
                budget.check()
            budget.check()
            return manifest
        except httpx.TimeoutException:
            raise KernelTimeout() from None
        except httpx.TransportError:
            raise KernelUnavailable() from None

    async def aclose(self) -> None:
        await self._http.aclose()
