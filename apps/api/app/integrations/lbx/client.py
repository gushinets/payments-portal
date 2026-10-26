from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Generic, TypeVar

import httpx
from pydantic import SecretStr

from app.core.errors import AppError
from app.core.settings import Settings
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx._transport import _Attempts, _CleanupProtectedStream, _Retryable, decode_response
from app.integrations.lbx.customer import CreatedUserEnvelope, LbxUser, NewCustomer
from app.integrations.lbx.dto import (
    LbxEnvelope,
    LbxServicePrice,
    LbxSession,
    LbxTariff,
    LbxTariffPeriod,
    LbxTariffService,
)
from app.integrations.lbx.errors import (
    LbxAuthenticationFailed,
    LbxClosed,
    LbxCreateNotSent,
    LbxNotConfigured,
    LbxResponseInvalid,
    LbxScopeMismatch,
    LbxTimeout,
    LbxUnavailable,
)
from app.integrations.lbx.privacy import private_http_diagnostics


API_PATH = "/api/rest/v1"
T = TypeVar("T")


@dataclass(frozen=True)
class LbxRead(Generic[T]):
    """Integration-only source DTO and configured/requested identity context.

    Account identity is the deployment's provider-origin binding, not a provider
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


def _require_identity(value: int) -> None:
    if type(value) is not int or value <= 0:
        raise LbxScopeMismatch()


class LbxServerClient:
    """One scoped async Server API client; selected GETs and fenced customer POST.

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
        # Status/customer work keeps pool capacity when offer reads saturate.
        self._account_http = httpx.AsyncClient(
            base_url=configuration.lbx_base_url,
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache, no-store",
            },
            follow_redirects=False,
            trust_env=False,
            verify=True,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=4),
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

    async def get_user(self, *, user_id: int, budget: PreflightBudget) -> LbxUser:
        _require_identity(user_id)
        result = await self._read(f"/users/{user_id}", LbxEnvelope[LbxUser], budget=budget)
        if result.user_id != user_id:
            raise LbxScopeMismatch()
        if result.password is not None and result.password.get_secret_value():
            raise LbxResponseInvalid()
        return result

    async def discover_users(self, *, outer_id: str, budget: PreflightBudget) -> tuple[int, ...]:
        if not outer_id or len(outer_id) > 256 or any(not 33 <= ord(c) <= 126 for c in outer_id):
            raise LbxScopeMismatch()
        rows = await self._read(
            "/users", LbxEnvelope[list[LbxUser]], budget=budget, body={"outer_id": outer_id, "show_passwords": False}
        )
        # A capped/truncated inventory is not evidence of absence or uniqueness.
        if len(rows) >= 100 or len({row.user_id for row in rows}) != len(rows):
            raise LbxResponseInvalid()
        if any(row.outer_id != outer_id for row in rows):
            raise LbxScopeMismatch()
        if any(row.password is not None and row.password.get_secret_value() for row in rows):
            raise LbxResponseInvalid()
        return tuple(row.user_id for row in rows)

    async def prepare_customer_create(self, *, budget: PreflightBudget) -> None:
        async def authenticate() -> None:
            with private_http_diagnostics():
                attempts = _Attempts(self._configuration.lbx_max_get_attempts)
                while True:
                    try:
                        await self._ensure_session(attempts, budget, allow_refresh=True)
                        return
                    except _Retryable as retry:
                        await self._wait_retry(retry, attempts, budget)

        await budget.run(authenticate)

    async def create_user(self, command: NewCustomer, *, budget: PreflightBudget) -> int:
        # Application has durably claimed possible_send. No POST retry or POST
        # reauthentication is allowed, even for 401/5xx/malformed success.
        source_task: asyncio.Task[int] | None = None
        dispatched = False

        def mark_scheduled(task: asyncio.Task[int]) -> None:
            nonlocal source_task
            source_task = task

        def mark_dispatch() -> None:
            nonlocal dispatched
            dispatched = True

        async def send() -> int:
            with private_http_diagnostics():
                session = self._session
                if session is None or time.monotonic() >= session.expires_at:
                    raise LbxCreateNotSent()
                try:
                    receipt = await self._request_once(
                        "/users",
                        CreatedUserEnvelope,
                        _Attempts(1),
                        budget,
                        headers={"Authorization": f"Bearer {session.token.get_secret_value()}"},
                        body=command.request_document(),
                        method="POST",
                        success_statuses=frozenset({200, 201}),
                        on_dispatch=mark_dispatch,
                    )
                    return receipt.user_id
                except _Retryable as error:
                    raise error.failure from None
                except AppError:
                    if not dispatched:
                        raise LbxCreateNotSent() from None
                    raise

        try:
            return await budget.run(send, on_schedule=mark_scheduled)
        except AppError:
            if not dispatched and (source_task is None or source_task.done()):
                raise LbxCreateNotSent() from None
            raise

    async def client_user(self, *, token: SecretStr, budget: PreflightBudget) -> LbxUser:
        async def read() -> LbxUser:
            with private_http_diagnostics():
                try:
                    result = await self._request_once(
                        "/client/user",
                        LbxEnvelope[LbxUser],
                        _Attempts(1),
                        budget,
                        headers={"Authorization": f"Bearer {token.get_secret_value()}"},
                    )
                except _Retryable as error:
                    raise error.failure from None
                if result.password is not None and result.password.get_secret_value():
                    raise LbxResponseInvalid()
                return result

        return await budget.run(read)

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
        body: dict[str, Any] | None = None,
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
        body: dict[str, Any] | None,
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
                await self._wait_retry(retry, attempts, budget)

    async def _wait_retry(self, retry: _Retryable, attempts: _Attempts, budget: PreflightBudget) -> None:
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

    async def _request_once(
        self,
        path: str,
        model: type[LbxEnvelope[T]],
        attempts: _Attempts,
        budget: PreflightBudget,
        *,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        auth: httpx.Auth | None = None,
        method: str = "GET",
        success_statuses: frozenset[int] = frozenset({200}),
        on_dispatch: Callable[[], None] | None = None,
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
            pool = self._account_http if path.startswith(("/users", "/client")) or path == "/auth" else self._http
            if on_dispatch is not None:
                on_dispatch()
            async with pool.stream(
                method, API_PATH + path, headers=headers, json=body, auth=auth, timeout=timeout
            ) as response:
                assert isinstance(response.stream, httpx.AsyncByteStream)
                response.stream = _CleanupProtectedStream(response.stream, budget)
                budget.check()
                result = await decode_response(
                    response,
                    model,
                    budget=budget,
                    maximum_bytes=config.lbx_max_response_bytes,
                    maximum_retry_delay=config.lbx_max_retry_delay_seconds,
                    method=method,
                    path=path,
                    success_statuses=success_statuses,
                )
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
            await self._account_http.aclose()
            await self._http.aclose()
