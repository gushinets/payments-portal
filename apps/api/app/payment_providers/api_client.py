from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from app.core.errors import (
    PaymentsAuthenticationError,
    PaymentsHttpError,
    PaymentsRateLimitError,
    PaymentsResponseDecodeError,
    PaymentsResponseValidationError,
    PaymentsTimeoutError,
    PaymentsTransportError,
    PaymentsUpstreamError,
)
from app.core.observability import redact
from app.payment_providers.contracts import RetryDisposition

logger = logging.getLogger(__name__)

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class PaymentsApiRequestMethod(StrEnum):
    GET = "GET"
    POST = "POST"


class PaymentsApiRequestBodyFormat(StrEnum):
    JSON = "json"
    FORM = "form"


class PaymentsApiClientModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PaymentsApiClientConfig(PaymentsApiClientModel):
    provider: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    timeout_seconds: float = Field(default=10.0, gt=0)
    connect_timeout_seconds: float = Field(default=3.0, gt=0)
    read_timeout_seconds: float = Field(default=10.0, gt=0)
    write_timeout_seconds: float = Field(default=10.0, gt=0)
    pool_timeout_seconds: float = Field(default=3.0, gt=0)
    max_retries: int = Field(default=2, ge=0)
    retry_backoff_seconds: float = Field(default=0.5, ge=0)


class PaymentsApiRequest(PaymentsApiClientModel):
    operation: str
    path: str
    payload: Mapping[str, Any] = Field(default_factory=dict)
    headers: Mapping[str, str] = Field(default_factory=dict)
    method: PaymentsApiRequestMethod = PaymentsApiRequestMethod.POST
    body_format: PaymentsApiRequestBodyFormat = PaymentsApiRequestBodyFormat.JSON
    idempotency_key: str | None = None
    is_idempotent: bool = False
    is_mutating: bool = False
    timeout_seconds: float | None = Field(default=None, gt=0)

    @field_validator("idempotency_key")
    @classmethod
    def normalize_idempotency_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PaymentsApiClient(Protocol):
    def send(
        self,
        request: PaymentsApiRequest,
        *,
        response_model: type[ResponseT],
    ) -> ResponseT: ...


class BaseHttpPaymentsApiClient(PaymentsApiClient):
    def __init__(
        self,
        *,
        config: PaymentsApiClientConfig,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=self._default_timeout(),
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def send(
        self,
        request: PaymentsApiRequest,
        *,
        response_model: type[ResponseT],
    ) -> ResponseT:
        for attempt in range(self.config.max_retries + 1):
            try:
                response = self._client.request(
                    method=request.method.value,
                    url=request.path,
                    headers=self._build_headers(request),
                    auth=self._build_auth(),
                    json=self._json_payload(request)
                    if request.body_format == PaymentsApiRequestBodyFormat.JSON
                    else None,
                    data=self._form_payload(request)
                    if request.body_format == PaymentsApiRequestBodyFormat.FORM
                    else None,
                    timeout=self._timeout_for_request(request),
                )
            except httpx.TimeoutException as exc:
                error = PaymentsTimeoutError(
                    "payments_api_timeout",
                    retry_disposition=RetryDisposition.RETRYABLE,
                    message_safe="Payment provider request timed out.",
                    details_safe=self._safe_details(request, attempt=attempt, reason="timeout"),
                )
                if self._should_retry(request, attempt, error.retry_disposition):
                    self._sleep_before_retry(attempt)
                    continue
                self._log_failure(error)
                raise error from exc
            except httpx.TransportError as exc:
                error = PaymentsTransportError(
                    "payments_api_transport_error",
                    retry_disposition=RetryDisposition.RETRYABLE,
                    message_safe="Payment provider transport error.",
                    details_safe=self._safe_details(request, attempt=attempt, reason=type(exc).__name__),
                )
                if self._should_retry(request, attempt, error.retry_disposition):
                    self._sleep_before_retry(attempt)
                    continue
                self._log_failure(error)
                raise error from exc

            if response.status_code == 401:
                error = PaymentsAuthenticationError(
                    "payments_api_authentication_error",
                    message_safe="Payment provider authentication failed.",
                    details_safe=self._safe_details(request, attempt=attempt, status_code=response.status_code),
                )
                self._log_failure(error)
                raise error

            if response.status_code == 429:
                error = PaymentsRateLimitError(
                    "payments_api_rate_limited",
                    retry_disposition=RetryDisposition.NON_RETRYABLE,
                    message_safe="Payment provider rate limit exceeded.",
                    details_safe=self._safe_details(request, attempt=attempt, status_code=response.status_code),
                )
                self._log_failure(error)
                raise error

            if 500 <= response.status_code < 600:
                error = PaymentsUpstreamError(
                    "payments_api_upstream_error",
                    retry_disposition=RetryDisposition.RETRYABLE,
                    message_safe="Payment provider upstream error.",
                    details_safe=self._safe_details(request, attempt=attempt, status_code=response.status_code),
                )
                if self._should_retry(request, attempt, error.retry_disposition):
                    self._sleep_before_retry(attempt)
                    continue
                self._log_failure(error)
                raise error

            if response.is_error:
                error = PaymentsHttpError(
                    "payments_api_http_error",
                    status_code=response.status_code,
                    message_safe="Payment provider HTTP error.",
                    details_safe=self._safe_details(request, attempt=attempt, status_code=response.status_code),
                )
                self._log_failure(error)
                raise error

            return self._validate_response(request, response, response_model=response_model)

        raise AssertionError("unreachable")

    def _build_auth(self) -> httpx.Auth | None:
        return None

    def _build_headers(self, request: PaymentsApiRequest) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "Content-Type": (
                "application/json"
                if request.body_format == PaymentsApiRequestBodyFormat.JSON
                else "application/x-www-form-urlencoded"
            ),
            **dict(request.headers),
        }
        if request.idempotency_key is not None:
            headers["X-Request-ID"] = request.idempotency_key
        return headers

    def _default_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=self.config.timeout_seconds,
            connect=self.config.connect_timeout_seconds,
            read=self.config.read_timeout_seconds,
            write=self.config.write_timeout_seconds,
            pool=self.config.pool_timeout_seconds,
        )

    def _timeout_for_request(self, request: PaymentsApiRequest) -> httpx.Timeout:
        if request.timeout_seconds is not None:
            timeout = request.timeout_seconds
            return httpx.Timeout(
                timeout=timeout,
                connect=min(timeout, self.config.connect_timeout_seconds),
                read=min(timeout, self.config.read_timeout_seconds),
                write=min(timeout, self.config.write_timeout_seconds),
                pool=min(timeout, self.config.pool_timeout_seconds),
            )
        return self._default_timeout()

    def _json_payload(self, request: PaymentsApiRequest) -> dict[str, Any]:
        return self._normalize_payload(dict(request.payload))

    def _form_payload(self, request: PaymentsApiRequest) -> dict[str, Any]:
        return self._normalize_payload(dict(request.payload))

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {key: self._normalize_value(value) for key, value in payload.items()}

    def _normalize_value(self, value: Any) -> Any:
        if isinstance(value, Decimal):
            normalized = value.normalize()
            if normalized == normalized.to_integral():
                return int(normalized)
            return float(value)
        if isinstance(value, Mapping):
            return {str(key): self._normalize_value(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._normalize_value(item) for item in value]
        if isinstance(value, tuple):
            return [self._normalize_value(item) for item in value]
        return value

    def _should_retry(
        self,
        request: PaymentsApiRequest,
        attempt: int,
        retry_disposition: RetryDisposition,
    ) -> bool:
        return (
            request.is_idempotent
            and (not request.is_mutating or request.idempotency_key is not None)
            and retry_disposition == RetryDisposition.RETRYABLE
            and attempt < self.config.max_retries
        )

    def _sleep_before_retry(self, attempt: int) -> None:
        delay_seconds = self.config.retry_backoff_seconds * (attempt + 1)
        logger.warning(
            "Retrying payment provider request.",
            extra={"structured": {"provider": self.config.provider, "delay_seconds": delay_seconds}},
        )
        time.sleep(delay_seconds)

    def _log_failure(self, error: Exception) -> None:
        details = getattr(error, "details_safe", {})
        logger.warning(
            "Payment provider request failed.",
            extra={
                "structured": {
                    "provider": self.config.provider,
                    "error_type": type(error).__name__,
                    "details": details,
                }
            },
        )

    def _validate_response(
        self,
        request: PaymentsApiRequest,
        response: httpx.Response,
        *,
        response_model: type[ResponseT],
    ) -> ResponseT:
        try:
            payload = response.json()
        except ValueError as exc:
            error = PaymentsResponseDecodeError(
                "payments_api_response_decode_error",
                message_safe="Payment provider response is not valid JSON.",
                details_safe=self._safe_details(request, status_code=response.status_code),
            )
            self._log_failure(error)
            raise error from exc

        try:
            return response_model.model_validate(payload)
        except ValidationError as exc:
            error = PaymentsResponseValidationError(
                "payments_api_response_validation_error",
                message_safe="Payment provider response schema mismatch.",
                details_safe=self._safe_details(
                    request,
                    status_code=response.status_code,
                    response_payload=redact(payload),
                ),
            )
            self._log_failure(error)
            raise error from exc

    def _safe_details(
        self,
        request: PaymentsApiRequest,
        *,
        attempt: int | None = None,
        status_code: int | None = None,
        reason: str | None = None,
        response_payload: Any | None = None,
    ) -> dict[str, Any]:
        details: dict[str, Any] = {
            "provider": self.config.provider,
            "operation": request.operation,
            "path": request.path,
            "headers": redact(dict(request.headers)),
            "idempotency_key": request.idempotency_key,
        }
        if attempt is not None:
            details["attempt"] = attempt + 1
        if status_code is not None:
            details["status_code"] = status_code
        if reason is not None:
            details["reason"] = reason
        if response_payload is not None:
            details["response_payload"] = response_payload
        return details
