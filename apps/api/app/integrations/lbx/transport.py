"""One LBX HTTP exchange and strict bounded decoding on the caller's budget.

The caller owns the HTTP pool, auth/session, retry policy and CREATE uncertainty.
This module never creates a client, refreshes credentials or retries a request.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx

from app.core.settings import Settings
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.dto import LbxEnvelope
from app.integrations.lbx.errors import (
    LbxAttemptsExhausted,
    LbxAuthenticationFailed,
    LbxError,
    LbxRateLimited,
    LbxResponseInvalid,
    LbxScopeForbidden,
    LbxTimeout,
    LbxUnavailable,
)
from app.integrations.lbx.preparation_dto import CreateEnvelope


_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
T = TypeVar("T")


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


def _decode_envelope(body: bytes, model: type[LbxEnvelope[T]] | type[CreateEnvelope[T]]) -> T:
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


def retry_after(value: str | None, *, maximum: float) -> float | None:
    if value is None:
        return None
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


async def request_once(
    http: httpx.AsyncClient,
    configuration: Settings,
    path: str,
    model: type[LbxEnvelope[T]] | type[CreateEnvelope[T]],
    attempts: _Attempts,
    budget: PreflightBudget,
    *,
    retry_after: Callable[[str | None], float | None],
    headers: dict[str, str] | None = None,
    body: dict[str, Any] | None = None,
    auth: httpx.Auth | None = None,
    method: str = "GET",
    content: bytes | None = None,
    success_statuses: frozenset[int] = frozenset({200}),
) -> T:
    budget.check()
    attempts.take()
    config = configuration
    remaining = budget.remaining_seconds()
    timeout = httpx.Timeout(
        connect=min(remaining, config.lbx_connect_timeout_seconds),
        read=min(remaining, config.lbx_read_timeout_seconds),
        write=min(remaining, config.lbx_connect_timeout_seconds),
        pool=min(remaining, config.lbx_connect_timeout_seconds),
    )
    try:
        async with http.stream(
            method, path, headers=headers, json=body, content=content, auth=auth, timeout=timeout
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
                raise _Retryable(failure, retry_after(response.headers.get("retry-after")))
            if 500 <= status <= 599:
                raise LbxUnavailable()
            if status not in success_statuses:
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
