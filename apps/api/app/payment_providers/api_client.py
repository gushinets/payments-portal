from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, TypeVar

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.payment_api_limits import (
    PAYMENTS_API_MAX_CONNECT_TIMEOUT_SECONDS,
    PAYMENTS_API_MAX_POOL_TIMEOUT_SECONDS,
    PAYMENTS_API_MAX_READ_TIMEOUT_SECONDS,
    PAYMENTS_API_MAX_RETRIES,
    PAYMENTS_API_MAX_RETRY_BACKOFF_SECONDS,
    PAYMENTS_API_MAX_TIMEOUT_SECONDS,
    PAYMENTS_API_MAX_WRITE_TIMEOUT_SECONDS,
)
from app.core.errors import (
    PaymentsAuthenticationError,
    PaymentsHttpError,
    PaymentsIdempotencyKeyRequiredError,
    PaymentsOperationDeclinedError,
    PaymentsRateLimitError,
    PaymentsResponseDecodeError,
    PaymentsResponseValidationError,
    PaymentsTimeoutError,
    PaymentsTransportError,
    PaymentsUpstreamError,
)
from app.core.observability import record_provider_api_operation, redact, tracer
from app.payment_providers.contracts import RetryDisposition
from app.payment_providers.response_summary import PaymentsApiClientModel, PaymentsApiResponseSummary
from app.payment_providers.timeouts import PaymentsApiRequestBudget, PaymentsApiTimeoutPolicy

logger = logging.getLogger(__name__)

ResponseT = TypeVar("ResponseT", bound=BaseModel)


class PaymentsApiRequestMethod(StrEnum):
    GET = "GET"
    POST = "POST"


class PaymentsApiRequestBodyFormat(StrEnum):
    JSON = "json"
    FORM = "form"


class PaymentsApiOperationOutcome(StrEnum):
    SUCCEEDED = "succeeded"
    TIMEOUT = "timeout"
    TRANSPORT_ERROR = "transport_error"
    AUTHENTICATION_ERROR = "authentication_error"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_ERROR = "upstream_error"
    HTTP_ERROR = "http_error"
    IDEMPOTENCY_KEY_REQUIRED = "idempotency_key_required"
    RESPONSE_DECODE_ERROR = "response_decode_error"
    RESPONSE_VALIDATION_ERROR = "response_validation_error"
    OPERATION_DECLINED = "operation_declined"


class PaymentsApiClientConfig(PaymentsApiClientModel):
    provider: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    timeout_seconds: float = Field(default=10.0, gt=0, le=PAYMENTS_API_MAX_TIMEOUT_SECONDS)
    connect_timeout_seconds: float = Field(default=3.0, gt=0, le=PAYMENTS_API_MAX_CONNECT_TIMEOUT_SECONDS)
    read_timeout_seconds: float = Field(default=10.0, gt=0, le=PAYMENTS_API_MAX_READ_TIMEOUT_SECONDS)
    write_timeout_seconds: float = Field(default=10.0, gt=0, le=PAYMENTS_API_MAX_WRITE_TIMEOUT_SECONDS)
    pool_timeout_seconds: float = Field(default=3.0, gt=0, le=PAYMENTS_API_MAX_POOL_TIMEOUT_SECONDS)
    max_retries: int = Field(default=2, ge=0, le=PAYMENTS_API_MAX_RETRIES)
    retry_backoff_seconds: float = Field(default=0.5, ge=0, le=PAYMENTS_API_MAX_RETRY_BACKOFF_SECONDS)


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
    timeout_seconds: float | None = Field(default=None, gt=0, le=PAYMENTS_API_MAX_TIMEOUT_SECONDS)

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
        self._timeout_policy = PaymentsApiTimeoutPolicy(
            timeout_seconds=config.timeout_seconds,
            connect_timeout_seconds=config.connect_timeout_seconds,
            read_timeout_seconds=config.read_timeout_seconds,
            write_timeout_seconds=config.write_timeout_seconds,
            pool_timeout_seconds=config.pool_timeout_seconds,
        )
        self._client = httpx.Client(
            base_url=config.base_url,
            timeout=self._timeout_policy.default_timeout(),
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
        operation_tracer = tracer(__name__)
        started = time.perf_counter()
        outcome = PaymentsApiOperationOutcome.TRANSPORT_ERROR
        with operation_tracer.start_as_current_span("payment_provider.api.operation") as span:
            self._set_span_attribute(span, "payment_provider.provider", self.config.provider)
            self._set_span_attribute(span, "payment_provider.operation", request.operation)
            try:
                self._require_mutation_idempotency_key(request)
                response = self._send_with_retries(request, response_model=response_model)
            except Exception as exc:
                outcome = self._outcome_from_exception(exc)
                self._set_span_attribute(span, "payment_provider.outcome", outcome.value)
                raise
            else:
                outcome = self._outcome_from_response(request, response)
                self._set_span_attribute(span, "payment_provider.outcome", outcome.value)
                return response
            finally:
                self._record_operation(request, outcome, duration_seconds=time.perf_counter() - started)
        raise AssertionError("unreachable")

    def _send_with_retries(
        self,
        request: PaymentsApiRequest,
        *,
        response_model: type[ResponseT],
    ) -> ResponseT:
        budget = self._budget_for_request(request)
        for attempt in range(self.config.max_retries + 1):
            try:
                remaining_seconds = budget.remaining_seconds()
                if remaining_seconds <= 0:
                    error = self._request_budget_error(request, attempt=attempt)
                    self._log_failure(error)
                    raise error
                timeout = self._timeout_for_request(
                    request,
                    remaining_seconds=remaining_seconds,
                )
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
                    timeout=timeout,
                )
                if budget.remaining_seconds() <= 0:
                    error = self._request_budget_error(request, attempt=attempt)
                    self._log_failure(error)
                    raise error
            except httpx.TimeoutException as exc:
                error = PaymentsTimeoutError(
                    "payments_api_timeout",
                    retry_disposition=RetryDisposition.RETRYABLE,
                    message_safe="Payment provider request timed out.",
                    details_safe=self._safe_details(request, attempt=attempt, reason="timeout"),
                )
                if self._should_retry(request, attempt, error.retry_disposition):
                    self._sleep_before_retry(request, attempt, budget=budget)
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
                    self._sleep_before_retry(request, attempt, budget=budget)
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
                    retry_disposition=RetryDisposition.RETRYABLE,
                    message_safe="Payment provider rate limit exceeded.",
                    details_safe=self._safe_details(request, attempt=attempt, status_code=response.status_code),
                )
                if self._should_retry(request, attempt, error.retry_disposition):
                    self._sleep_before_retry(request, attempt, budget=budget)
                    continue
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
                    self._sleep_before_retry(request, attempt, budget=budget)
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

    def _outcome_from_response(
        self,
        request: PaymentsApiRequest,
        response: BaseModel,
    ) -> PaymentsApiOperationOutcome:
        return PaymentsApiOperationOutcome.SUCCEEDED

    def _outcome_from_exception(self, exc: Exception) -> PaymentsApiOperationOutcome:
        if isinstance(exc, PaymentsTimeoutError):
            return PaymentsApiOperationOutcome.TIMEOUT
        if isinstance(exc, PaymentsAuthenticationError):
            return PaymentsApiOperationOutcome.AUTHENTICATION_ERROR
        if isinstance(exc, PaymentsRateLimitError):
            return PaymentsApiOperationOutcome.RATE_LIMITED
        if isinstance(exc, PaymentsIdempotencyKeyRequiredError):
            return PaymentsApiOperationOutcome.IDEMPOTENCY_KEY_REQUIRED
        if isinstance(exc, PaymentsUpstreamError):
            return PaymentsApiOperationOutcome.UPSTREAM_ERROR
        if isinstance(exc, PaymentsHttpError):
            return PaymentsApiOperationOutcome.HTTP_ERROR
        if isinstance(exc, PaymentsResponseDecodeError):
            return PaymentsApiOperationOutcome.RESPONSE_DECODE_ERROR
        if isinstance(exc, PaymentsResponseValidationError):
            return PaymentsApiOperationOutcome.RESPONSE_VALIDATION_ERROR
        if isinstance(exc, PaymentsOperationDeclinedError):
            return PaymentsApiOperationOutcome.OPERATION_DECLINED
        if isinstance(exc, PaymentsTransportError):
            return PaymentsApiOperationOutcome.TRANSPORT_ERROR
        return PaymentsApiOperationOutcome.TRANSPORT_ERROR

    def _record_operation(
        self,
        request: PaymentsApiRequest,
        outcome: PaymentsApiOperationOutcome,
        *,
        duration_seconds: float,
    ) -> None:
        record_provider_api_operation(
            provider=self.config.provider,
            operation=request.operation,
            outcome=outcome.value,
            duration_seconds=duration_seconds,
        )

    @staticmethod
    def _set_span_attribute(span: object, key: str, value: str) -> None:
        if hasattr(span, "set_attribute"):
            span.set_attribute(key, value)

    def _build_auth(self) -> httpx.Auth | None:
        return None

    def _require_mutation_idempotency_key(self, request: PaymentsApiRequest) -> None:
        if not request.is_mutating or request.idempotency_key is not None:
            return
        error = PaymentsIdempotencyKeyRequiredError(
            "payments_api_idempotency_key_required",
            message_safe="Payment provider mutation requires an idempotency key.",
            details_safe=self._safe_details(request),
        )
        self._log_failure(error)
        raise error

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

    def _budget_for_request(self, request: PaymentsApiRequest) -> PaymentsApiRequestBudget:
        return self._timeout_policy.budget_for_request(timeout_seconds=request.timeout_seconds)

    def _timeout_for_request(
        self,
        request: PaymentsApiRequest,
        *,
        remaining_seconds: float | None = None,
    ) -> httpx.Timeout:
        return self._timeout_policy.request_timeout(
            timeout_seconds=request.timeout_seconds,
            remaining_seconds=remaining_seconds,
        )

    def _request_budget_error(
        self,
        request: PaymentsApiRequest,
        *,
        attempt: int,
    ) -> PaymentsTimeoutError:
        return PaymentsTimeoutError(
            "payments_api_timeout",
            retry_disposition=RetryDisposition.RETRYABLE,
            message_safe="Payment provider request timed out.",
            details_safe=self._safe_details(request, attempt=attempt, reason="request_budget_exhausted"),
        )

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

    def _sleep_before_retry(
        self,
        request: PaymentsApiRequest,
        attempt: int,
        *,
        budget: PaymentsApiRequestBudget,
    ) -> None:
        delay_seconds = self.config.retry_backoff_seconds * (attempt + 1)
        if delay_seconds >= budget.remaining_seconds():
            error = self._request_budget_error(request, attempt=attempt)
            self._log_failure(error)
            raise error
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
                details_safe=self._safe_details(
                    request,
                    status_code=response.status_code,
                    response_summary=PaymentsApiResponseSummary.invalid_json(
                        body_byte_length=len(response.content),
                    ),
                ),
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
                    response_summary=PaymentsApiResponseSummary.from_payload(payload),
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
        response_summary: PaymentsApiResponseSummary | None = None,
    ) -> dict[str, Any]:
        details: dict[str, Any] = {
            "provider": self.config.provider,
            "operation": request.operation,
            "path": request.path,
            "headers": redact(dict(request.headers)),
            "idempotency_key": redact(request.idempotency_key, "idempotency_key"),
        }
        if attempt is not None:
            details["attempt"] = attempt + 1
        if status_code is not None:
            details["status_code"] = status_code
        if reason is not None:
            details["reason"] = reason
        if response_summary is not None:
            details["response_summary"] = response_summary.model_dump(mode="json", exclude_none=True)
        return details
