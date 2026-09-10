from __future__ import annotations

import logging
import os
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from enum import StrEnum
from functools import partial
from typing import Any
from uuid import UUID, uuid4

import sentry_sdk
from sentry_sdk.integrations.atexit import AtexitIntegration

from app.core.errors import AppError
from app.core.observability import REQUEST_ID_PATTERN, current_trace_ids, request_id_context
from app.core.settings import Settings
from app.payment_providers.errors import (
    PaymentProviderConfigurationError,
    PaymentsError,
    PaymentsIdempotencyKeyRequiredError,
    PaymentsOperationDeclinedError,
    PaymentsTimeoutError,
)


logger = logging.getLogger(__name__)
DEFAULT_SERVICE_NAME = "payment-portal-api"
_TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SPAN_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
_METHOD_PATTERN = re.compile(r"^[A-Z0-9!#$%&'*+.^_`|~-]{1,16}$")
_ERROR_CODE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,127}$")
_INVARIANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_SERVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PYTHON_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,127}$")
_PYTHON_MODULE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]{0,255}$")
_FUNCTION_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_<>.-]{1,128}$")
_MECHANISM_TYPE_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_MECHANISM_SOURCE_PATTERN = re.compile(r"^(?:__cause__|__context__|exceptions\[[0-9]+\])$")
_EVENT_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")
_SDK_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
_SENTRY_PLATFORM = "python"
_SENTRY_LEVEL = "error"
_SENTRY_SDK_NAME = "sentry.python"
_SENTRY_PACKAGE_NAME = "pypi:sentry-sdk"


class FailureCategory(StrEnum):
    INTERNAL_APPLICATION_FAILURE = "internal_application_failure"
    INTEGRATION_FAILURE = "integration_failure"
    UNKNOWN_EXTERNAL_OUTCOME = "unknown_external_outcome"
    UNEXPECTED_EXCEPTION = "unexpected_exception"
    CONSISTENCY_INVARIANT_VIOLATION = "consistency_invariant_violation"


class Operation(StrEnum):
    HTTP_REQUEST = "http_request"
    EXPIRE_SUBSCRIPTIONS = "expire_subscriptions"


def classify_exception(error: Exception) -> FailureCategory | None:
    if isinstance(error, PaymentsOperationDeclinedError):
        return None
    if isinstance(error, PaymentsTimeoutError):
        return FailureCategory.UNKNOWN_EXTERNAL_OUTCOME
    if isinstance(error, (PaymentsIdempotencyKeyRequiredError, PaymentProviderConfigurationError)):
        return FailureCategory.INTERNAL_APPLICATION_FAILURE
    if isinstance(error, PaymentsError):
        return FailureCategory.INTEGRATION_FAILURE
    if isinstance(error, AppError):
        return FailureCategory.INTERNAL_APPLICATION_FAILURE
    return FailureCategory.UNEXPECTED_EXCEPTION


def configure_sentry(settings: Settings) -> None:
    if not settings.sentry_dsn:
        return

    try:
        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            release=settings.sentry_release,
            environment=settings.app_env.value,
            integrations=[AtexitIntegration(callback=_silent_shutdown)],
            default_integrations=False,
            auto_enabling_integrations=False,
            send_default_pii=False,
            include_local_variables=False,
            include_source_context=False,
            max_request_body_size="never",
            traces_sample_rate=0.0,
            profiles_sample_rate=0.0,
            enable_logs=False,
            before_send_metric=_drop_metric,
            propagate_traces=False,
            auto_session_tracking=False,
            sample_rate=1.0,
            debug=False,
            keep_alive=False,
            spotlight=False,
            before_send=partial(
                _before_send,
                release=settings.sentry_release,
                environment=settings.app_env.value,
            ),
        )
    except Exception as error:  # pragma: no cover - exercised through a mocked SDK boundary
        _log_sentry_failure("sentry_initialization_failed", error)


def report_exception(
    error: Exception,
    *,
    operation: Operation,
    failure_category: FailureCategory | None = None,
    run_id: str | None = None,
    method: str | None = None,
    route: str | None = None,
    error_code: str | None = None,
    invariant: str | None = None,
    batch_size: int | None = None,
    failure_location: Mapping[str, object] | None = None,
) -> None:
    try:
        if not isinstance(operation, Operation):
            raise TypeError("operation must be an Operation")
        classified_category = classify_exception(error)
        if classified_category is None:
            return
        category = failure_category or classified_category
        if not isinstance(category, FailureCategory):
            raise TypeError("failure_category must be a FailureCategory")

        context = _payment_portal_context(
            run_id=run_id,
            method=method,
            route=route,
            error_code=error_code,
            invariant=invariant,
            batch_size=batch_size,
            failure_location=failure_location,
        )
        with sentry_sdk.new_scope() as scope:
            scope.set_tag("service", _service_name())
            scope.set_tag("failure_category", category.value)
            scope.set_tag("operation", operation.value)
            if context:
                scope.set_context("payment_portal", context)
            sentry_sdk.capture_exception(error)
    except Exception as reporting_error:
        _log_sentry_failure("sentry_reporting_failed", reporting_error)


def _silent_shutdown(_pending: int, _timeout: int) -> None:
    return None


def _drop_metric(_metric: object, _hint: dict[str, Any]) -> None:
    return None


def _log_sentry_failure(event: str, error: Exception) -> None:
    logger.error(event, extra={"structured": {"error_type": type(error).__name__}})


def _service_name() -> str:
    return os.getenv("OTEL_SERVICE_NAME", DEFAULT_SERVICE_NAME)


def _payment_portal_context(
    *,
    run_id: str | None,
    method: str | None,
    route: str | None,
    error_code: str | None,
    invariant: str | None,
    batch_size: int | None,
    failure_location: Mapping[str, object] | None,
) -> dict[str, object]:
    request_id = request_id_context.get()
    trace_id, span_id = current_trace_ids()
    candidate: dict[str, object] = {
        "request_id": request_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "run_id": run_id,
        "method": method,
        "route": route,
        "error_code": error_code,
        "invariant": invariant,
        "batch_size": batch_size,
        "failure_location": failure_location,
    }
    return _sanitize_payment_portal_context(candidate)


def _sanitize_payment_portal_context(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}

    sanitized: dict[str, object] = {}
    validators = {
        "request_id": lambda item: _matching_string(item, REQUEST_ID_PATTERN),
        "trace_id": lambda item: _matching_string(item, _TRACE_ID_PATTERN),
        "span_id": lambda item: _matching_string(item, _SPAN_ID_PATTERN),
        "run_id": _canonical_uuid,
        "method": lambda item: _matching_string(item, _METHOD_PATTERN),
        "route": _matched_route,
        "error_code": lambda item: _matching_string(item, _ERROR_CODE_PATTERN),
        "invariant": lambda item: _matching_string(item, _INVARIANT_PATTERN),
        "batch_size": _batch_size,
        "failure_location": _failure_location,
    }
    for key, validator in validators.items():
        validated = validator(value.get(key))
        if validated is not None:
            sanitized[key] = validated
    return sanitized


def _matching_string(value: object, pattern: re.Pattern[str]) -> str | None:
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _canonical_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = UUID(value)
    except ValueError:
        return None
    return value if str(parsed) == value else None


def _matched_route(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("/") or len(value) > 256:
        return None
    if "?" in value or "#" in value or any(character.isspace() for character in value):
        return None
    return value


def _batch_size(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
        return None
    return value


def _failure_location(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping):
        return None
    module = _repository_relative_path(value.get("module"), maximum_length=256)
    function = _matching_string(value.get("function"), _FUNCTION_NAME_PATTERN)
    line = value.get("line")
    if module is None or function is None or isinstance(line, bool) or not isinstance(line, int) or line <= 0:
        return None
    return {"module": module, "function": function, "line": line}


def _repository_relative_path(value: object, *, maximum_length: int) -> str | None:
    if not isinstance(value, str) or not value or len(value) > maximum_length:
        return None
    if value.startswith(("/", "\\")) or "\\" in value or re.match(r"^[A-Za-z]:", value):
        return None
    if any(part in {"", ".", ".."} for part in value.split("/")):
        return None
    if any(character.isspace() or ord(character) < 32 for character in value):
        return None
    return value


def _before_send(
    event: dict[str, Any],
    _hint: dict[str, Any],
    *,
    release: str,
    environment: str,
) -> dict[str, Any]:
    event_id = _matching_string(event.get("event_id"), _EVENT_ID_PATTERN) or uuid4().hex
    sanitized: dict[str, Any] = {
        "event_id": event_id,
        "release": release,
        "environment": environment,
    }
    timestamp = _sdk_timestamp(event.get("timestamp"))
    if timestamp is not None:
        sanitized["timestamp"] = timestamp
    if event.get("platform") == _SENTRY_PLATFORM:
        sanitized["platform"] = _SENTRY_PLATFORM
    if event.get("level") == _SENTRY_LEVEL:
        sanitized["level"] = _SENTRY_LEVEL

    exception = _sanitize_exception(event.get("exception"))
    if exception is not None:
        sanitized["exception"] = exception

    tags = _sanitize_tags(event.get("tags"))
    if tags:
        sanitized["tags"] = tags

    contexts = event.get("contexts")
    if isinstance(contexts, Mapping):
        payment_portal = _sanitize_payment_portal_context(contexts.get("payment_portal"))
        if payment_portal:
            sanitized["contexts"] = {"payment_portal": payment_portal}

    sdk = _sanitize_sdk(event.get("sdk"))
    if sdk:
        sanitized["sdk"] = sdk
    return sanitized


def _sanitize_tags(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    sanitized: dict[str, str] = {}
    service = _matching_string(value.get("service"), _SERVICE_NAME_PATTERN)
    if service is not None:
        sanitized["service"] = service
    category = value.get("failure_category")
    if isinstance(category, str) and category in FailureCategory:
        sanitized["failure_category"] = category
    operation = value.get("operation")
    if isinstance(operation, str) and operation in Operation:
        sanitized["operation"] = operation
    return sanitized


def _sanitize_exception(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("values"), list):
        return None
    values = [item for item in (_sanitize_exception_value(item) for item in value["values"]) if item]
    return {"values": values} if values else None


def _sanitize_exception_value(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    sanitized: dict[str, object] = {}
    exception_type = _matching_string(value.get("type"), _PYTHON_NAME_PATTERN)
    if exception_type is not None:
        sanitized["type"] = exception_type
    module = _matching_string(value.get("module"), _PYTHON_MODULE_PATTERN)
    if module is not None:
        sanitized["module"] = module
    stacktrace = _sanitize_stacktrace(value.get("stacktrace"))
    if stacktrace is not None:
        sanitized["stacktrace"] = stacktrace
    mechanism = _sanitize_mechanism(value.get("mechanism"))
    if mechanism:
        sanitized["mechanism"] = mechanism
    return sanitized


def _sanitize_stacktrace(value: object) -> dict[str, object] | None:
    if not isinstance(value, Mapping) or not isinstance(value.get("frames"), list):
        return None
    frames = [item for item in (_sanitize_frame(item) for item in value["frames"]) if item]
    return {"frames": frames} if frames else None


def _sanitize_frame(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    sanitized: dict[str, object] = {}
    filename = _repository_relative_path(value.get("filename"), maximum_length=512)
    if filename is not None:
        sanitized["filename"] = filename
    module = _matching_string(value.get("module"), _PYTHON_MODULE_PATTERN)
    if module is not None:
        sanitized["module"] = module
    function = _matching_string(value.get("function"), _FUNCTION_NAME_PATTERN)
    if function is not None:
        sanitized["function"] = function
    line = value.get("lineno")
    if isinstance(line, int) and not isinstance(line, bool) and line > 0:
        sanitized["lineno"] = line
    in_app = value.get("in_app")
    if isinstance(in_app, bool):
        sanitized["in_app"] = in_app
    return sanitized


def _sanitize_mechanism(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    sanitized: dict[str, object] = {}
    mechanism_type = _matching_string(value.get("type"), _MECHANISM_TYPE_PATTERN)
    if mechanism_type is not None:
        sanitized["type"] = mechanism_type
    source = _matching_string(value.get("source"), _MECHANISM_SOURCE_PATTERN)
    if source is not None:
        sanitized["source"] = source
    for key in ("handled", "synthetic", "is_exception_group"):
        if isinstance(value.get(key), bool):
            sanitized[key] = value[key]
    for key in ("exception_id", "parent_id"):
        item = value.get(key)
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            sanitized[key] = item
    return sanitized


def _sanitize_sdk(value: object) -> dict[str, object]:
    if not isinstance(value, Mapping):
        return {}
    if value.get("name") != _SENTRY_SDK_NAME or value.get("version") != sentry_sdk.VERSION:
        return {}
    sanitized: dict[str, object] = {
        "name": _SENTRY_SDK_NAME,
        "version": sentry_sdk.VERSION,
    }
    packages = value.get("packages")
    if isinstance(packages, list):
        expected_package = {"name": _SENTRY_PACKAGE_NAME, "version": sentry_sdk.VERSION}
        if expected_package in packages:
            sanitized["packages"] = [expected_package]
    return sanitized


def _sdk_timestamp(value: object) -> str | None:
    if not isinstance(value, str) or _SDK_TIMESTAMP_PATTERN.fullmatch(value) is None:
        return None
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return value if parsed.strftime("%Y-%m-%dT%H:%M:%S.%fZ") == value else None
