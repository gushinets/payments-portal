from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from email.utils import parsedate_to_datetime
from typing import Any, Generic, TypeVar

import httpx
from pydantic import SecretStr

from app.core.settings import Settings
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.dto import (
    LbxEnvelope,
    LbxServicePrice,
    LbxSession,
    LbxTariff,
    LbxTariffPeriod,
    LbxTariffService,
)
from app.integrations.lbx.errors import (
    LbxAttemptsExhausted,
    LbxAuthenticationFailed,
    LbxClosed,
    LbxError,
    LbxNotConfigured,
    LbxRateLimited,
    LbxResponseInvalid,
    LbxScopeForbidden,
    LbxScopeMismatch,
    LbxTimeout,
    LbxUnavailable,
)
from app.integrations.lbx.privacy import private_http_diagnostics


API_PATH = "/api/rest/v1"
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
T = TypeVar("T")


@dataclass(frozen=True)
class LbxRead(Generic[T]):
    """Integration-only source DTO and configured/requested identity context.

    Account identity is the deployment's credential binding, not a provider
    attestation: these GET responses contain no billing-account identity.
    Step 4 must normalize this before Application. No atomic snapshot implied.
    """

    external_billing_account_id: str
    tariff_id: int
    tariff_service_id: int | None
    observed_at: datetime
    value: T


@dataclass(frozen=True)
class _Session:
    token: SecretStr = field(repr=False)
    expires_at: float


@dataclass
class _Attempts:
    limit: int
    used: int = 0

    def take(self) -> None:
        if self.used >= self.limit:
            raise LbxAttemptsExhausted()
        self.used += 1


class _Retryable(Exception):
    def __init__(self, failure: LbxError, retry_after_seconds: float | None = None) -> None:
        super().__init__(failure.code)
        self.failure = failure
        self.retry_after_seconds = retry_after_seconds


class _CleanupProtectedStream(httpx.AsyncByteStream):
    """Use Step 2 accounting even when HTTPX automatically closes at EOF."""

    def __init__(self, stream: httpx.AsyncByteStream, budget: PreflightBudget) -> None:
        self._stream = stream
        self._budget = budget

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for fragment in self._stream:
            yield fragment

    async def aclose(self) -> None:
        with self._budget.protect_source_cleanup():
            await self._stream.aclose()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError("non-JSON number")


def _decode_envelope(body: bytes, model: type[LbxEnvelope[T]]) -> T:
    try:
        raw = json.loads(
            body.decode("utf-8"),
            parse_float=Decimal,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
        return model.model_validate(raw).response
    except (ValueError, DecimalException, RecursionError):
        raise LbxResponseInvalid() from None


def _require_identity(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise LbxScopeMismatch()


class LbxServerClient:
    """One scoped async Server API pool; only documented selected GETs.

    Construct explicitly for source work, never from a DB-only query/startup
    dependency. There is no construction-time HTTP, external catalog cache or
    account routing. The caller owns PreflightAdmission and passes its SAME
    admitted budget through every Kernel/LBX read and subsequent normalization.
    A logical read is one counted source task, including lock/auth/retry/close.
    """

    def __init__(
        self,
        configuration: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if configuration.lbx_configuration_error is not None:
            raise LbxNotConfigured()
        self._configuration = configuration
        self._session: _Session | None = None
        self._session_lock = asyncio.Lock()
        self._closed = False
        self._http = httpx.AsyncClient(
            base_url=configuration.lbx_base_url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache, no-store",
            },
            follow_redirects=False,
            trust_env=False,
            verify=True,
            limits=httpx.Limits(
                max_connections=configuration.preflight_max_active,
                max_keepalive_connections=configuration.preflight_max_active,
            ),
            transport=transport,
        )

    async def list_tariffs(self, *, tariff_id: int, budget: PreflightBudget) -> LbxRead[list[LbxTariff]]:
        _require_identity(tariff_id)
        result = await self._read(
            "/tariffs", LbxEnvelope[list[LbxTariff]], budget=budget, body={"tariff_id": tariff_id}
        )
        if any(item.tariff_id != tariff_id for item in result) or len(result) > 1:
            raise LbxScopeMismatch()
        return self._scoped(result, tariff_id=tariff_id)

    async def get_tariff(self, *, tariff_id: int, budget: PreflightBudget) -> LbxRead[LbxTariff]:
        _require_identity(tariff_id)
        result = await self._read(f"/tariffs/{tariff_id}", LbxEnvelope[LbxTariff], budget=budget)
        if result.tariff_id != tariff_id:
            raise LbxScopeMismatch()
        return self._scoped(result, tariff_id=tariff_id)

    async def list_tariff_periods(self, *, tariff_id: int, budget: PreflightBudget) -> LbxRead[list[LbxTariffPeriod]]:
        _require_identity(tariff_id)
        result = await self._read(f"/tariffs/{tariff_id}/periods", LbxEnvelope[list[LbxTariffPeriod]], budget=budget)
        if len({item.tariff_period_id for item in result}) != len(result):
            raise LbxResponseInvalid()
        return self._scoped(result, tariff_id=tariff_id)

    async def list_tariff_services(self, *, tariff_id: int, budget: PreflightBudget) -> LbxRead[list[LbxTariffService]]:
        _require_identity(tariff_id)
        result = await self._read(f"/tariffs/{tariff_id}/services", LbxEnvelope[list[LbxTariffService]], budget=budget)
        if any(item.tariff_id != tariff_id for item in result):
            raise LbxScopeMismatch()
        if len({item.tariff_service_id for item in result}) != len(result):
            raise LbxResponseInvalid()
        return self._scoped(result, tariff_id=tariff_id)

    async def list_service_prices(
        self, *, tariff_id: int, tariff_service_id: int, budget: PreflightBudget
    ) -> LbxRead[list[LbxServicePrice]]:
        _require_identity(tariff_id)
        _require_identity(tariff_service_id)
        result = await self._read(
            f"/tariffs/{tariff_id}/services/{tariff_service_id}/prices",
            LbxEnvelope[list[LbxServicePrice]],
            budget=budget,
        )
        if len({item.price_id for item in result}) != len(result):
            raise LbxResponseInvalid()
        return self._scoped(result, tariff_id=tariff_id, tariff_service_id=tariff_service_id)

    def _scoped(self, value: T, *, tariff_id: int, tariff_service_id: int | None = None) -> LbxRead[T]:
        return LbxRead(
            external_billing_account_id=self._configuration.lbx_external_billing_account_id,
            tariff_id=tariff_id,
            tariff_service_id=tariff_service_id,
            observed_at=datetime.now(UTC),
            value=value,
        )

    async def _read(
        self,
        path: str,
        model: type[LbxEnvelope[T]],
        *,
        budget: PreflightBudget,
        body: dict[str, int] | None = None,
    ) -> T:
        if self._closed:
            raise LbxClosed()

        async def read() -> T:
            with private_http_diagnostics():
                return await self._read_with_session(path, model, budget, body)

        return await budget.run(read)

    async def _read_with_session(
        self,
        path: str,
        model: type[LbxEnvelope[T]],
        budget: PreflightBudget,
        body: dict[str, int] | None,
    ) -> T:
        attempts = _Attempts(self._configuration.lbx_max_get_attempts)
        reauthenticated = False
        previous_session: _Session | None = None
        while True:
            budget.check()
            try:
                session = await self._ensure_session(attempts, budget, allow_refresh=not reauthenticated)
                if previous_session is not None and session is not previous_session:
                    if reauthenticated:
                        raise LbxAuthenticationFailed()
                    reauthenticated = True
                previous_session = session
                try:
                    return await self._request_once(
                        path,
                        model,
                        attempts,
                        budget,
                        headers={"Authorization": f"Bearer {session.token.get_secret_value()}"},
                        body=body,
                    )
                except LbxAuthenticationFailed:
                    # A stale 401 must never invalidate another caller's fresh
                    # token. No business GET receives more than one reauth.
                    if self._session is session:
                        self._session = None
                    if reauthenticated:
                        raise
            except _Retryable as retry:
                if attempts.used >= attempts.limit:
                    raise retry.failure from None
                config = self._configuration
                delay = retry.retry_after_seconds
                if delay is None:
                    delay = config.lbx_retry_delay_seconds * (2 ** (attempts.used - 1))
                await asyncio.sleep(min(delay, config.lbx_max_retry_delay_seconds))
                budget.check()

    async def _ensure_session(self, attempts: _Attempts, budget: PreflightBudget, *, allow_refresh: bool) -> _Session:
        current = self._session
        if current is not None and time.monotonic() < current.expires_at:
            return current
        # Lock waiting, auth HTTP and auth body/cleanup are in the SAME source
        # task and absolute deadline as the selected GET. No refresh worker.
        async with self._session_lock:
            budget.check()
            current = self._session
            if current is not None and time.monotonic() < current.expires_at:
                return current
            if not allow_refresh:
                raise LbxAuthenticationFailed()
            self._session = None
            started = time.monotonic()
            config = self._configuration
            credentials = httpx.BasicAuth(
                config.lbx_server_username.get_secret_value(), config.lbx_server_password.get_secret_value()
            )
            wire = await self._request_once("/auth", LbxEnvelope[LbxSession], attempts, budget, auth=credentials)
            # Start BEFORE the auth round trip; never assume another 600s after
            # receiving a delayed response or invent a fixed provider lifetime.
            try:
                expires_at = started + wire.expires_in
            except OverflowError:
                raise LbxResponseInvalid() from None
            if not math.isfinite(expires_at):
                raise LbxResponseInvalid()
            session = _Session(wire.token, expires_at)
            budget.check()
            if time.monotonic() >= session.expires_at:
                raise LbxAuthenticationFailed()
            self._session = session
            return session

    def _retry_after(self, value: str | None) -> float | None:
        if value is None:
            return None
        maximum = self._configuration.lbx_max_retry_delay_seconds
        value = value.strip()
        if value.isascii() and value.isdigit():
            return maximum if len(value) > 10 else min(float(value), maximum)
        try:
            hint = parsedate_to_datetime(value)
            if hint.tzinfo is not None:
                return min(max(0.0, (hint - datetime.now(UTC)).total_seconds()), maximum)
        except (ValueError, OverflowError):
            pass
        return None

    async def _request_once(
        self,
        path: str,
        model: type[LbxEnvelope[T]],
        attempts: _Attempts,
        budget: PreflightBudget,
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, int] | None = None,
        auth: httpx.Auth | None = None,
    ) -> T:
        budget.check()
        attempts.take()
        config = self._configuration
        remaining = budget.remaining_seconds()
        timeout = httpx.Timeout(
            connect=min(remaining, config.lbx_connect_timeout_seconds),
            read=min(remaining, config.lbx_read_timeout_seconds),
            write=min(remaining, config.lbx_connect_timeout_seconds),
            pool=min(remaining, config.lbx_connect_timeout_seconds),
        )
        try:
            async with self._http.stream(
                "GET", API_PATH + path, headers=headers, json=body, auth=auth, timeout=timeout
            ) as response:
                assert isinstance(response.stream, httpx.AsyncByteStream)
                response.stream = _CleanupProtectedStream(response.stream, budget)
                budget.check()
                status = response.status_code
                if status == 401:
                    raise LbxAuthenticationFailed()
                if status == 403:
                    raise LbxScopeForbidden()
                if status in _TRANSIENT_STATUS:
                    failure = LbxRateLimited() if status == 429 else LbxUnavailable()
                    raise _Retryable(failure, self._retry_after(response.headers.get("retry-after")))
                if 500 <= status <= 599:
                    raise LbxUnavailable()
                if status != 200:
                    raise LbxResponseInvalid()
                if response.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
                    raise LbxResponseInvalid()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise LbxResponseInvalid()
                length = response.headers.get("content-length")
                if length is not None:
                    try:
                        declared_size = int(length)
                    except ValueError:
                        raise LbxResponseInvalid() from None
                    if not 0 <= declared_size <= config.lbx_max_response_bytes:
                        raise LbxResponseInvalid()
                payload = bytearray()
                async for fragment in response.aiter_bytes():
                    budget.check()
                    if len(payload) + len(fragment) > config.lbx_max_response_bytes:
                        raise LbxResponseInvalid()
                    payload.extend(fragment)
                budget.check()
                if length is not None and len(payload) != declared_size:
                    raise LbxResponseInvalid()
                result = _decode_envelope(bytes(payload), model)
                budget.check()
            budget.check()
            return result
        except httpx.TimeoutException:
            raise _Retryable(LbxTimeout()) from None
        except (httpx.NetworkError, httpx.RemoteProtocolError):
            raise _Retryable(LbxUnavailable()) from None
        except httpx.TransportError:
            raise LbxUnavailable() from None

    async def aclose(self) -> None:
        """Owner stops/drains its PreflightAdmission BEFORE closing this pool.

        If admission reports cleanup pending, retain this client until that
        counted source task stops; never reuse resources underneath cleanup.
        """
        self._closed = True
        self._session = None
        with private_http_diagnostics():
            await self._http.aclose()
