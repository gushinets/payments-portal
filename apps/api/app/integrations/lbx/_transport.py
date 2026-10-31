"""Internal bounded LBX wire decoding and safe diagnostics; owns no HTTP pool."""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx

from app.core.settings import Settings
from app.core.observability import request_id_context
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.dto import LbxEnvelope
from app.integrations.lbx.errors import (
    LbxAttemptsExhausted,
    LbxCreateNotSent,
    LbxTimeout,
    LbxAuthenticationFailed,
    LbxError,
    LbxRateLimited,
    LbxProviderRejected,
    LbxResponseInvalid,
    LbxScopeForbidden,
    LbxUnavailable,
    LbxResponseFacts,
)

API_PATH = "/api/rest/v1"
T = TypeVar("T")
logger = logging.getLogger("payment_portal.lbx")
_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})
_operation_id: ContextVar[str | None] = ContextVar("lbx_customer_operation_id", default=None)


@contextmanager
def customer_diagnostics(operation_id: str) -> Iterator[None]:
    token = _operation_id.set(operation_id)
    try:
        yield
    finally:
        _operation_id.reset(token)


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


def _decode_json(body: bytes) -> Any:
    try:
        return json.loads(
            body.decode("utf-8"),
            parse_float=Decimal,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except (ValueError, DecimalException, RecursionError):
        raise LbxResponseInvalid() from None


async def _payload(response: httpx.Response, budget: PreflightBudget, maximum: int) -> bytes:
    """The same finite size/encoding rules apply to success and error bodies."""
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
        if not 0 <= declared_size <= maximum:
            raise LbxResponseInvalid()
    payload = bytearray()
    async for fragment in response.aiter_bytes():
        budget.check()
        if len(payload) + len(fragment) > maximum:
            raise LbxResponseInvalid()
        payload.extend(fragment)
    budget.check()
    if length is not None and len(payload) != declared_size:
        raise LbxResponseInvalid()
    return bytes(payload)


def _error_facts(raw: Any) -> tuple[int | None, str, bool]:
    # Never retain or log arbitrary remote text, even after attempted redaction.
    if not isinstance(raw, dict):
        return None, "unknown", False
    code = raw.get("code")
    safe_code = code if type(code) is int and -(2**31) <= code < 2**31 else None
    nested = raw.get("response")
    present = isinstance(nested, dict) and "error" in nested or "error" in raw
    if "code" in raw and safe_code is None:
        return safe_code, "schema_invalid", present
    errors = [container["error"] for container in (nested, raw) if isinstance(container, dict) and "error" in container]
    if any(not isinstance(value, str) or not value.strip() for value in errors):
        return safe_code, "schema_invalid", present
    texts = [raw.get(field) for field in ("response", "error", "message")]
    if isinstance(nested, dict):
        texts.extend(nested.get(field) for field in ("error", "message"))
    for text in texts:
        if isinstance(text, str) and text.startswith("Invalid email ") and text.endswith(". Email must be unique"):
            return safe_code, "email_not_unique", present
        if isinstance(text, str) and (
            text == "Invalid login/pass" or text.startswith("Invalid login/pass. Client login:")
        ):
            return safe_code, "credentials_denied", present
    return safe_code, "provider_rejected" if present else "unknown", present


def response_facts(
    *,
    http_status: int | None,
    lbx_code: int | None = None,
    reason: str,
    provider_error_present: bool = False,
    failure_kind: str,
    retryable_get: bool = False,
    method: str,
    path: str,
) -> LbxResponseFacts:
    # Match only repository-owned templates; never log URLs, query data or IDs.
    templates = (
        "/auth",
        "/client/user",
        "/users",
        "/users/{id}",
        "/tariffs",
        "/tariffs/{id}",
        "/tariffs/{id}/periods",
        "/tariffs/{id}/services",
        "/tariffs/{id}/services/{id}/prices",
        "/agreements",
        "/agreements/{id}",
        "/subscriptions",
        "/subscriptions/{id}",
    )
    endpoint = next(
        (template for template in templates if re.fullmatch(template.replace("{id}", "[0-9]+"), path)),
        "server_api",
    )
    return LbxResponseFacts(
        http_status,
        lbx_code,
        reason,
        provider_error_present,
        failure_kind,
        retryable_get,
        method if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} else "OTHER",
        endpoint,
        request_id_context.get(),
        _operation_id.get(),
    )


def log_http(facts: LbxResponseFacts, *, duration_ms: float) -> None:
    logger.info(
        "lbx_http",
        extra={
            "structured": {
                "stage": "client_readiness"
                if facts.endpoint == "/client/user"
                else "server_auth"
                if facts.endpoint == "/auth"
                else "customer"
                if facts.endpoint.startswith("/users")
                else "source",
                "method": facts.method,
                "duration_ms": duration_ms,
                "endpoint": facts.endpoint,
                "status": facts.http_status,
                "lbx_code": facts.lbx_code,
                "reason": facts.reason,
                "provider_error_present": facts.provider_error_present,
                "failure_kind": facts.failure_kind,
                "retryable_get": facts.retryable_get,
                "request_id": facts.request_id,
                "create_operation_id": facts.create_operation_id,
            }
        },
    )


async def decode_response(
    response: httpx.Response,
    model: type[LbxEnvelope[T]],
    *,
    budget: PreflightBudget,
    maximum_bytes: int,
    maximum_retry_delay: float,
    method: str,
    path: str,
    success_statuses: frozenset[int],
) -> tuple[T, LbxResponseFacts]:
    status = response.status_code
    code, reason, present = None, "unknown", False
    failure_kind = "invalid_response"
    try:
        try:
            raw = _decode_json(await _payload(response, budget, maximum_bytes))
            code, reason, present = _error_facts(raw)
        except LbxResponseInvalid:
            raw = None
            reason = "schema_invalid"
        if status == 401 or code == 401 or reason == "credentials_denied":
            failure_kind = "authorization"
            raise LbxAuthenticationFailed()
        if status == 403 or code == 403:
            failure_kind = "authorization"
            raise LbxScopeForbidden()
        if status == 429 or code == 429:
            failure_kind = "rate_limit"
            raise _Retryable(LbxRateLimited(), retry_after(response.headers.get("retry-after"), maximum_retry_delay))
        if present and reason == "schema_invalid":
            if status in _TRANSIENT_STATUS or code in _TRANSIENT_STATUS:
                raise _Retryable(
                    LbxResponseInvalid(), retry_after(response.headers.get("retry-after"), maximum_retry_delay)
                )
            raise LbxResponseInvalid()
        if reason in {"provider_rejected", "email_not_unique"} or code is not None and code >= 400:
            failure_kind = "provider"
            if reason != "email_not_unique":
                reason = "provider_rejected"
            failure = LbxProviderRejected()
            # A generic error envelope proves a refusal, not its permanence or
            # the absence of side effects. Only GETs may consume this retry hint.
            if reason == "provider_rejected" and (status in _TRANSIENT_STATUS or code in _TRANSIENT_STATUS):
                raise _Retryable(failure, retry_after(response.headers.get("retry-after"), maximum_retry_delay))
            raise failure
        if 500 <= status <= 599:
            failure_kind = "unavailable"
            if status in _TRANSIENT_STATUS:
                raise _Retryable(
                    LbxUnavailable(), retry_after(response.headers.get("retry-after"), maximum_retry_delay)
                )
            raise LbxUnavailable()
        if status not in success_statuses or reason == "schema_invalid":
            raise LbxResponseInvalid()
        try:
            result = model.model_validate(raw).response
        except (ValueError, DecimalException, RecursionError):
            reason = "schema_invalid"
            raise LbxResponseInvalid() from None
        return result, response_facts(
            http_status=status,
            lbx_code=code,
            reason="success",
            failure_kind="success",
            method=method,
            path=path,
        )
    except (LbxError, _Retryable) as error:
        failure = error.failure if isinstance(error, _Retryable) else error
        failure.response_facts = response_facts(
            http_status=status,
            lbx_code=code,
            reason=reason,
            provider_error_present=present,
            failure_kind=failure_kind,
            retryable_get=isinstance(error, _Retryable),
            method=method,
            path=path,
        )
        raise


def retry_after(value: str | None, maximum: float) -> float | None:
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
    pool: httpx.AsyncClient,
    configuration: Settings,
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
    config = configuration
    remaining = budget.remaining_seconds()
    timeout = httpx.Timeout(
        connect=min(remaining, config.lbx_connect_timeout_seconds),
        read=min(remaining, config.lbx_read_timeout_seconds),
        write=min(remaining, config.lbx_connect_timeout_seconds),
        pool=min(remaining, config.lbx_connect_timeout_seconds),
    )
    status: int | None = None
    facts = None
    started = time.perf_counter()
    try:
        try:
            if on_dispatch is not None:
                on_dispatch()
            async with pool.stream(
                method, API_PATH + path, headers=headers, json=body, auth=auth, timeout=timeout
            ) as response:
                status = response.status_code
                assert isinstance(response.stream, httpx.AsyncByteStream)
                response.stream = _CleanupProtectedStream(response.stream, budget)
                budget.check()
                result, facts = await decode_response(
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
        except (httpx.PoolTimeout, httpx.ConnectTimeout, httpx.ConnectError) as error:
            # With trust_env=False/no proxy these failures precede sending the
            # application request. Never generalize to write/read failures.
            failure = LbxTimeout() if isinstance(error, httpx.TimeoutException) else LbxUnavailable()
            if method == "POST" and status is None:
                failure = LbxCreateNotSent()
            kind = "timeout" if isinstance(error, httpx.TimeoutException) else "network"
            retry = not isinstance(failure, LbxCreateNotSent)
        except httpx.TimeoutException:
            failure, kind, retry = LbxTimeout(), "timeout", True
        except (httpx.NetworkError, httpx.RemoteProtocolError):
            failure, kind, retry = LbxUnavailable(), "network", True
        except httpx.TransportError:
            failure, kind, retry = LbxUnavailable(), "network", False
        failure.response_facts = (
            replace(facts, reason=kind, failure_kind=kind, retryable_get=retry)
            if facts
            else response_facts(
                http_status=status,
                reason=kind,
                failure_kind=kind,
                retryable_get=retry,
                method=method,
                path=path,
            )
        )
        if retry:
            raise _Retryable(failure) from None
        raise failure from None
    except (LbxError, _Retryable) as error:
        failure = error.failure if isinstance(error, _Retryable) else error
        facts = failure.response_facts
        raise
    finally:
        if facts is not None:
            log_http(facts, duration_ms=(time.perf_counter() - started) * 1000)
