from __future__ import annotations

import contextvars
import functools
import inspect
import json
import logging
import os
import re
import time
import uuid
from collections.abc import Mapping
from typing import Any, get_type_hints

from fastapi import FastAPI, Request, Response


request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")
OTEL_CHECKOUTS = None
OTEL_LEGAL_ACCEPTANCES = None
OTEL_WEBHOOKS = None
OTEL_PASSWORD_RESET_EMAILS = None
OTEL_PROVIDER_API_OPERATIONS = None
OTEL_PROVIDER_API_OPERATION_DURATION = None
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
SENSITIVE_KEYS = {
    "authorization",
    "cookie",
    "set-cookie",
    "content-hmac",
    "x-content-hmac",
    "idempotency_key",
    "x-request-id",
    "password",
    "token",
    "api_secret",
    "cardcryptogrampacket",
    "cardfirstsix",
    "cardlastfour",
    "cardmask",
    "cardexpdate",
    "cardexpiration",
    "cardexpirationdate",
    "cardexpiry",
    "cardexpirydate",
    "cardtype",
    "cardholdermessage",
    "cardtoken",
    "expirationdate",
    "expirationdatemonth",
    "expirationdateyear",
    "expdate",
    "expiry",
    "expirydate",
    "pan",
    "paymenttoken",
    "cvv",
    "cvc",
    "cryptogram",
}
NORMALIZED_SENSITIVE_KEYS = {re.sub(r"[^a-z0-9]", "", item.lower()) for item in SENSITIVE_KEYS}
SENSITIVE_KEY_MARKERS = ("secret", "token")
PAYMENT_VALUE_KEY_MARKERS = ("amount", "invoice", "payment")


def redact(value: Any, key: str = "") -> Any:
    """Return a telemetry-safe representation of nested data."""

    normalized_key = re.sub(r"[^a-z0-9]", "", key.lower())
    if normalized_key in NORMALIZED_SENSITIVE_KEYS or any(
        marker in normalized_key for marker in (*SENSITIVE_KEY_MARKERS, *PAYMENT_VALUE_KEY_MARKERS)
    ):
        return "[redacted]"
    if isinstance(value, Mapping):
        return {str(item_key): redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = request_id_context.get()
        if request_id:
            payload["request_id"] = request_id
        trace_id, span_id = current_trace_ids()
        if trace_id:
            payload["trace_id"] = trace_id
            payload["span_id"] = span_id
        extra = getattr(record, "structured", None)
        if extra:
            payload["fields"] = redact(extra)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging() -> None:
    root = logging.getLogger()
    if any(getattr(handler, "_payment_portal_json", False) for handler in root.handlers):
        return
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler._payment_portal_json = True  # type: ignore[attr-defined]
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())


try:
    from prometheus_client import (
        CONTENT_TYPE_LATEST,
        Counter,
        Histogram,
        generate_latest,
    )

    REQUEST_DURATION = Histogram(
        "payment_portal_http_request_duration_seconds",
        "HTTP request duration",
        ("method", "route", "status"),
    )
    CHECKOUTS = Counter("payment_portal_checkouts_total", "Checkout intent outcomes", ("outcome",))
    LEGAL_ACCEPTANCES = Counter(
        "payment_portal_legal_acceptances_total",
        "Legal acceptance outcomes",
        ("outcome",),
    )
    WEBHOOKS = Counter(
        "payment_portal_webhooks_total",
        "CloudPayments webhook outcomes",
        ("endpoint", "outcome"),
    )
    PASSWORD_RESET_EMAILS = Counter(
        "payment_portal_password_reset_emails_total",
        "Password reset email delivery outcomes",
        ("outcome",),
    )
    PROVIDER_API_OPERATIONS = Counter(
        "payment_portal_provider_api_operations_total",
        "Payment provider API operation outcomes",
        ("provider", "operation", "outcome"),
    )
    PROVIDER_API_OPERATION_DURATION = Histogram(
        "payment_portal_provider_api_operation_duration_seconds",
        "Payment provider API operation duration",
        ("provider", "operation", "outcome"),
    )
except ImportError:  # pragma: no cover - production dependencies include the package
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"

    class _DummyMetric:
        def labels(self, *_: object, **__: object) -> "_DummyMetric":
            return self

        def inc(self, *_: object, **__: object) -> None:
            return None

        def observe(self, *_: object, **__: object) -> None:
            return None

    REQUEST_DURATION = CHECKOUTS = LEGAL_ACCEPTANCES = WEBHOOKS = PASSWORD_RESET_EMAILS = _DummyMetric()
    PROVIDER_API_OPERATIONS = PROVIDER_API_OPERATION_DURATION = _DummyMetric()

    def generate_latest() -> bytes:
        return b""


def current_trace_ids() -> tuple[str, str]:
    try:
        from opentelemetry import trace

        context = trace.get_current_span().get_span_context()
        if not context.is_valid:
            return "", ""
        return f"{context.trace_id:032x}", f"{context.span_id:016x}"
    except ImportError:  # pragma: no cover
        return "", ""


def record_checkout(outcome: str) -> None:
    CHECKOUTS.labels(outcome).inc()
    if OTEL_CHECKOUTS is not None:
        OTEL_CHECKOUTS.add(1, {"outcome": outcome})


def record_legal_acceptance(outcome: str) -> None:
    LEGAL_ACCEPTANCES.labels(outcome).inc()
    if OTEL_LEGAL_ACCEPTANCES is not None:
        OTEL_LEGAL_ACCEPTANCES.add(1, {"outcome": outcome})


def record_webhook(endpoint: str, outcome: str) -> None:
    WEBHOOKS.labels(endpoint, outcome).inc()
    if OTEL_WEBHOOKS is not None:
        OTEL_WEBHOOKS.add(1, {"endpoint": endpoint, "outcome": outcome})


def record_password_reset_email(outcome: str) -> None:
    PASSWORD_RESET_EMAILS.labels(outcome).inc()
    if OTEL_PASSWORD_RESET_EMAILS is not None:
        OTEL_PASSWORD_RESET_EMAILS.add(1, {"outcome": outcome})


def record_provider_api_operation(
    *,
    provider: str,
    operation: str,
    outcome: str,
    duration_seconds: float,
) -> None:
    PROVIDER_API_OPERATIONS.labels(provider, operation, outcome).inc()
    PROVIDER_API_OPERATION_DURATION.labels(provider, operation, outcome).observe(duration_seconds)
    attributes = {"provider": provider, "operation": operation, "outcome": outcome}
    if OTEL_PROVIDER_API_OPERATIONS is not None:
        OTEL_PROVIDER_API_OPERATIONS.add(1, attributes)
    if OTEL_PROVIDER_API_OPERATION_DURATION is not None:
        OTEL_PROVIDER_API_OPERATION_DURATION.record(duration_seconds, attributes)


def tracer(name: str):
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:  # pragma: no cover
        from contextlib import nullcontext

        class _DummyTracer:
            def start_as_current_span(self, *_: object, **__: object):
                return nullcontext()

        return _DummyTracer()


def traced(span_name: str):
    """Decorate a sync or async application operation with a named span."""

    def decorator(function):
        operation_tracer = tracer(function.__module__)
        signature = inspect.signature(function)
        resolved_hints = get_type_hints(function)
        resolved_signature = signature.replace(
            parameters=[
                parameter.replace(annotation=resolved_hints.get(name, parameter.annotation))
                for name, parameter in signature.parameters.items()
            ],
            return_annotation=resolved_hints.get("return", signature.return_annotation),
        )
        if inspect.iscoroutinefunction(function):

            @functools.wraps(function)
            async def async_wrapper(*args, **kwargs):
                with operation_tracer.start_as_current_span(span_name):
                    return await function(*args, **kwargs)

            setattr(async_wrapper, "__signature__", resolved_signature)
            return async_wrapper

        @functools.wraps(function)
        def sync_wrapper(*args, **kwargs):
            with operation_tracer.start_as_current_span(span_name):
                return function(*args, **kwargs)

        setattr(sync_wrapper, "__signature__", resolved_signature)
        return sync_wrapper

    return decorator


def configure_observability(app: FastAPI, engine: object) -> None:
    global OTEL_CHECKOUTS, OTEL_LEGAL_ACCEPTANCES, OTEL_WEBHOOKS, OTEL_PASSWORD_RESET_EMAILS
    global OTEL_PROVIDER_API_OPERATIONS, OTEL_PROVIDER_API_OPERATION_DURATION
    configure_logging()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
    if not endpoint:
        return
    try:
        from opentelemetry import metrics, trace
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create({"service.name": os.getenv("OTEL_SERVICE_NAME", "payment-portal-api")})
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")))
        trace.set_tracer_provider(provider)

        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=f"{endpoint}/v1/metrics"),
            export_interval_millis=5_000,
        )
        metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))
        meter = metrics.get_meter("payment-portal.business")
        OTEL_CHECKOUTS = meter.create_counter("payment_portal_checkouts")
        OTEL_LEGAL_ACCEPTANCES = meter.create_counter("payment_portal_legal_acceptances")
        OTEL_WEBHOOKS = meter.create_counter("payment_portal_webhooks")
        OTEL_PASSWORD_RESET_EMAILS = meter.create_counter("payment_portal_password_reset_emails")
        OTEL_PROVIDER_API_OPERATIONS = meter.create_counter("payment_portal_provider_api_operations")
        OTEL_PROVIDER_API_OPERATION_DURATION = meter.create_histogram(
            "payment_portal_provider_api_operation_duration_seconds"
        )

        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{endpoint}/v1/logs"))
        )
        set_logger_provider(logger_provider)
        logging.getLogger().addHandler(LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider))
        FastAPIInstrumentor.instrument_app(app)
        SQLAlchemyInstrumentor().instrument(engine=engine)
    except (ImportError, RuntimeError):
        logging.getLogger(__name__).exception("observability_initialization_failed")


async def request_context_middleware(request: Request, call_next):
    supplied = request.headers.get("x-request-id", "")
    request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid.uuid4().hex
    token = request_id_context.set(request_id)
    started = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = request_id
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", request.url.path)
        REQUEST_DURATION.labels(request.method, route_path, str(status)).observe(time.perf_counter() - started)
        logging.getLogger("payment_portal.http").info(
            "http_request_complete request_id=%s",
            request_id,
            extra={
                "structured": {
                    "method": request.method,
                    "route": route_path,
                    "status": status,
                }
            },
        )
        request_id_context.reset(token)


def metrics_response() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
