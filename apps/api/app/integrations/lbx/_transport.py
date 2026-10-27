"""Internal bounded LBX wire decoding and safe diagnostics; owns no HTTP pool."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, DecimalException
from email.utils import parsedate_to_datetime
from typing import Any, TypeVar

import httpx

from app.core.observability import request_id_context
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.dto import LbxEnvelope
from app.integrations.lbx.errors import (
    LbxAttemptsExhausted,
    LbxAuthenticationFailed,
    LbxError,
    LbxRateLimited,
    LbxProviderRejected,
    LbxResponseInvalid,
    LbxScopeForbidden,
    LbxUnavailable,
    LbxResponseFacts,
)

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


def _error_facts(raw: Any) -> tuple[int | None, str]:
    # Never retain or log arbitrary remote text, even after attempted redaction.
    if not isinstance(raw, dict):
        return None, "unknown"
    code = raw.get("code")
    safe_code = code if type(code) is int and -(2**31) <= code < 2**31 else None
    nested = raw.get("response")
    texts = [raw.get(field) for field in ("response", "error", "message")]
    if isinstance(nested, dict):
        texts.extend(nested.get(field) for field in ("error", "message"))
    for text in texts:
        if isinstance(text, str) and text.startswith("Invalid email ") and text.endswith(". Email must be unique"):
            return safe_code, "email_not_unique"
        if isinstance(text, str) and (
            text == "Invalid login/pass" or text.startswith("Invalid login/pass. Client login:")
        ):
            return safe_code, "credentials_denied"
    if isinstance(nested, dict) and isinstance(nested.get("error"), str):
        return safe_code, "provider_rejected"
    if isinstance(raw.get("error"), str):
        return safe_code, "provider_rejected"
    return safe_code, "unknown"


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
) -> T:
    status = response.status_code
    code, reason = (None, "unknown")
    try:
        try:
            raw = _decode_json(await _payload(response, budget, maximum_bytes))
            code, reason = _error_facts(raw)
        except LbxResponseInvalid:
            raw = None
            reason = "schema_invalid"
            if status in success_statuses:
                raise
        if status == 401 or reason == "credentials_denied":
            raise LbxAuthenticationFailed()
        if status == 403:
            raise LbxScopeForbidden()
        if status in _TRANSIENT_STATUS:
            failure = LbxRateLimited() if status == 429 else LbxUnavailable()
            raise _Retryable(failure, retry_after(response.headers.get("retry-after"), maximum_retry_delay))
        if 500 <= status <= 599:
            raise LbxUnavailable()
        if reason in {"provider_rejected", "email_not_unique"} or code is not None and code >= 400:
            if reason != "email_not_unique":
                reason = "provider_rejected"
            raise LbxProviderRejected()
        if status not in success_statuses:
            raise LbxResponseInvalid()
        try:
            result = model.model_validate(raw).response
        except (ValueError, DecimalException, RecursionError):
            reason = "schema_invalid"
            raise LbxResponseInvalid() from None
        reason = "success"
        return result
    except (LbxError, _Retryable) as error:
        failure = error.failure if isinstance(error, _Retryable) else error
        failure.response_facts = LbxResponseFacts(status, code, reason)
        raise
    finally:
        logger.info(
            "lbx_http",
            extra={
                "structured": {
                    "stage": "client_readiness"
                    if path == "/client/user"
                    else "server_auth"
                    if path == "/auth"
                    else "customer"
                    if path.startswith("/users")
                    else "source",
                    "method": method,
                    "endpoint": "/users/{id}"
                    if path.startswith("/users/")
                    else path
                    if path in {"/users", "/client/user", "/auth"}
                    else "selected_offer",
                    "status": status,
                    "lbx_code": code,
                    "reason": reason,
                    "request_id": request_id_context.get(),
                    "create_operation_id": _operation_id.get(),
                }
            },
        )


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
