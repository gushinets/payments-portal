from __future__ import annotations

import asyncio
import logging
import uuid
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.trace import Event, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode

from app.core import observability
from app.core.observability import JsonFormatter, redact
from app.http_errors import unexpected_failure_middleware


async def _get(
    application: FastAPI,
    path: str,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://testserver",
    ) as client:
        return await client.get(path, headers=headers)


class RecordingMetric:
    def __init__(self) -> None:
        self.labels_seen: list[tuple[object, ...]] = []

    def labels(self, *labels: object) -> RecordingMetric:
        self.labels_seen.append(labels)
        return self

    def observe(self, _: float) -> None:
        return None


def assert_span_does_not_expose(span: object, marker: str) -> None:
    attributes = getattr(span, "attributes")
    events = getattr(span, "events")
    status = getattr(span, "status")

    assert marker not in repr(dict(attributes))
    assert marker not in (status.description or "")
    for event in events:
        event_attributes = event.attributes or {}
        assert marker not in event.name
        assert marker not in repr(dict(event_attributes))
        assert "exception.stacktrace" not in event_attributes


@pytest.mark.parametrize(
    ("marker", "event"),
    [
        ("unique-event-name-marker-437", Event(name="unique-event-name-marker-437")),
        (
            "unique-event-attribute-marker-437",
            Event(name="exception", attributes={"exception.message": "unique-event-attribute-marker-437"}),
        ),
    ],
    ids=["event-name", "exception-message"],
)
def test_assert_span_does_not_expose_rejects_event_markers(marker: str, event: Event) -> None:
    span = SimpleNamespace(
        attributes={},
        events=(event,),
        status=SimpleNamespace(description=None),
    )

    assert "exception.stacktrace" not in (event.attributes or {})
    with pytest.raises(AssertionError):
        assert_span_does_not_expose(span, marker)


def make_tracer_provider(exporter: InMemorySpanExporter) -> TracerProvider:
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    return tracer_provider


def test_redact_preserves_only_the_local_payment_id_exception() -> None:
    local_payment_id = "123e4567-e89b-12d3-a456-426614174000"
    payload = {
        "payment_id": local_payment_id,
        "order_id": "order-local-1",
        "subscription_id": "subscription-local-1",
        "provider_payment_id": "provider-payment-1",
        "PaymentId": "provider-payment-variant-1",
        "invoice_id": "invoice-1",
        "authorization": "Bearer secret",
        "CardFirstSix": "411111",
        "CardLastFour": "1111",
    }

    assert redact(payload) == {
        "payment_id": local_payment_id,
        "order_id": "order-local-1",
        "subscription_id": "subscription-local-1",
        "provider_payment_id": "[redacted]",
        "PaymentId": "[redacted]",
        "invoice_id": "[redacted]",
        "authorization": "[redacted]",
        "CardFirstSix": "[redacted]",
        "CardLastFour": "[redacted]",
    }
    assert redact(uuid.UUID(local_payment_id), "payment_id") == local_payment_id
    assert redact(None, "payment_id") is None
    assert redact("not-a-uuid", "payment_id") == "[redacted]"
    assert redact({"value": local_payment_id}, "payment_id") == "[redacted]"


def test_json_formatter_keeps_request_id_text_searchable() -> None:
    record = logging.LogRecord(
        name="payment_portal.http",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="http_request_complete request_id=%s",
        args=("request.lookup-123",),
        exc_info=None,
    )
    record.structured = {"method": "GET", "route": "/health", "status": 200}

    assert "http_request_complete request_id=request.lookup-123" in JsonFormatter().format(record)


def test_http_server_span_sanitizer_strips_and_clears_query_attributes() -> None:
    class Span:
        def __init__(self) -> None:
            self.attributes = {
                "http.target": "/items/local-item-123?query_secret=unique-query-secret-437#fragment-secret",
                "http.url": "https://example.test/items/local-item-123?query_secret=unique-query-secret-437#fragment-secret",
                "url.full": "https://example.test/items/local-item-123?query_secret=unique-query-secret-437#fragment-secret",
                "url.query": "query_secret=unique-query-secret-437",
            }

        def set_attribute(self, key: str, value: str) -> None:
            self.attributes[key] = value

    span = Span()
    observability._sanitize_http_server_span(span, {})

    assert span.attributes == {
        "http.target": "/items/local-item-123",
        "http.url": "https://example.test/items/local-item-123",
        "url.full": "https://example.test/items/local-item-123",
        "url.query": "",
    }


def test_traced_sync_and_async_exceptions_keep_safe_error_spans_and_chaining(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    tracer_provider = make_tracer_provider(exporter)
    monkeypatch.setattr(observability, "tracer", lambda _: tracer_provider.get_tracer("test.traced"))
    marker = "unique-traced-exception-secret-437"

    @observability.traced("test.sync_failure")
    def sync_failure() -> None:
        try:
            raise RuntimeError(marker)
        except RuntimeError as inner:
            raise ValueError("safe outer failure") from inner

    @observability.traced("test.async_failure")
    async def async_failure() -> None:
        try:
            raise RuntimeError(marker)
        except RuntimeError as inner:
            raise ValueError("safe outer failure") from inner

    with pytest.raises(ValueError) as sync_error:
        sync_failure()
    with pytest.raises(ValueError) as async_error:
        asyncio.run(async_failure())

    for error in (sync_error.value, async_error.value):
        assert isinstance(error.__cause__, RuntimeError)
        assert error.__cause__.args == (marker,)
        assert error.__context__ is error.__cause__
        assert error.__traceback__ is not None

    tracer_provider.force_flush()
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {"test.sync_failure", "test.async_failure"}
    for span in spans.values():
        assert span.status.status_code is StatusCode.ERROR
        assert span.status.description is None
        assert dict(span.attributes) == {"error.type": "ValueError"}
        assert span.events == ()
        assert_span_does_not_expose(span, marker)


def test_traced_control_flow_failures_keep_spans_unmarked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    tracer_provider = make_tracer_provider(exporter)
    monkeypatch.setattr(observability, "tracer", lambda _: tracer_provider.get_tracer("test.control_flow"))

    class ControlFlowSignal(BaseException):
        pass

    @observability.traced("test.sync_control_flow")
    def sync_control_flow() -> None:
        raise ControlFlowSignal()

    @observability.traced("test.async_control_flow")
    async def async_control_flow() -> None:
        raise asyncio.CancelledError()

    with pytest.raises(ControlFlowSignal):
        sync_control_flow()
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(async_control_flow())

    tracer_provider.force_flush()
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert set(spans) == {"test.sync_control_flow", "test.async_control_flow"}
    for span in spans.values():
        assert span.status.status_code is StatusCode.UNSET
        assert span.status.description is None
        assert dict(span.attributes) == {}
        assert span.events == ()


def test_http_failure_containing_traced_exception_does_not_leak_chained_secret(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exporter = InMemorySpanExporter()
    tracer_provider = make_tracer_provider(exporter)
    monkeypatch.setattr(observability, "tracer", lambda _: tracer_provider.get_tracer("test.http_failure"))
    marker = "unique-http-exception-secret-437"
    application = FastAPI()
    application.middleware("http")(unexpected_failure_middleware)
    application.middleware("http")(observability.request_context_middleware)

    @observability.traced("test.http_failure_operation")
    async def http_failure() -> None:
        try:
            raise RuntimeError(marker)
        except RuntimeError as inner:
            raise ValueError("safe outer failure") from inner

    application.add_api_route("/test-traced-failure", http_failure, methods=["GET"])
    FastAPIInstrumentor.instrument_app(application, tracer_provider=tracer_provider)
    try:
        with caplog.at_level(logging.ERROR, logger="payment_portal.http"):
            response = asyncio.run(_get(application, "/test-traced-failure?query_secret=query-secret-437"))

        assert response.status_code == 500
        assert response.headers["X-Request-ID"]
        assert marker not in caplog.text
        tracer_provider.force_flush()
        spans = exporter.get_finished_spans()
        assert {span.name for span in spans} >= {
            "test.http_failure_operation",
            "GET /test-traced-failure",
        }
        for span in spans:
            assert_span_does_not_expose(span, marker)
        operation_span = next(span for span in spans if span.name == "test.http_failure_operation")
        assert operation_span.status.status_code is StatusCode.ERROR
        assert operation_span.status.description is None
        assert dict(operation_span.attributes) == {"error.type": "ValueError"}
        assert operation_span.events == ()
        server_span = next(span for span in spans if span.name == "GET /test-traced-failure")
        assert server_span.status.status_code is StatusCode.ERROR
        assert server_span.status.description is None
    finally:
        FastAPIInstrumentor.uninstrument_app(application)


def test_http_server_span_sanitizer_ignores_missing_or_non_mapping_attributes() -> None:
    class SpanWithoutAttributes:
        attributes = "not-a-mapping"

    observability._sanitize_http_server_span(object(), {})
    observability._sanitize_http_server_span(SpanWithoutAttributes(), {})


def test_request_telemetry_uses_unmatched_sentinel_and_bounded_metric_labels(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    metric = RecordingMetric()
    monkeypatch.setattr(observability, "REQUEST_DURATION", metric)
    application = FastAPI()
    application.middleware("http")(observability.request_context_middleware)

    @application.get("/items/{item_id}")
    async def get_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    with caplog.at_level(logging.INFO, logger="payment_portal.http"):
        unmatched_path = "/not-a-route/business-id-123"
        assert asyncio.run(_get(application, unmatched_path)).status_code == 404
        matched_response = asyncio.run(
            _get(application, "/items/business-id-123", headers={"X-Request-ID": "request.lookup-123"})
        )
        assert matched_response.status_code == 200
        assert matched_response.headers["X-Request-ID"] == "request.lookup-123"

    completion = [record for record in caplog.records if record.getMessage().startswith("http_request_complete")]
    assert completion[0].structured["route"] == "unmatched"
    assert unmatched_path not in str(completion[0].structured)
    assert completion[1].structured["route"] == "/items/{item_id}"
    assert completion[1].getMessage() == "http_request_complete request_id=request.lookup-123"
    assert metric.labels_seen == [
        ("GET", "unmatched", "404"),
        ("GET", "/items/{item_id}", "200"),
    ]


def test_http_server_span_query_values_are_sanitized_without_header_capture() -> None:
    exporter = InMemorySpanExporter()
    tracer_provider = TracerProvider()
    tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))
    application = FastAPI()

    @application.get("/items/{item_id}")
    async def get_item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    FastAPIInstrumentor.instrument_app(
        application,
        server_request_hook=observability._sanitize_http_server_span,
        tracer_provider=tracer_provider,
    )
    try:
        query_secret = "unique-query-secret-437"
        fragment_secret = "private-marker"
        header_secret = "unique-header-secret-437"
        malformed_target = "http://testserver//[?custom=review-query-marker-437"
        requests = (
            (f"/items/local-item-123?query_secret={query_secret}", 200),
            (f"/items/local-item-123?query_secret=%23{fragment_secret}", 200),
            (malformed_target, 404),
        )
        for request_target, expected_status in requests:
            assert (
                asyncio.run(
                    _get(
                        application,
                        request_target,
                        headers={"X-Observability-Marker": header_secret},
                    )
                ).status_code
                == expected_status
            )
        tracer_provider.force_flush()

        server_spans = [span for span in exporter.get_finished_spans() if span.kind is SpanKind.SERVER]
        assert len(server_spans) == 3
        for span in server_spans:
            span_attributes = span.attributes
            for marker in (query_secret, fragment_secret, "%23" + fragment_secret, "review-query-marker-437"):
                assert_span_does_not_expose(span, marker)
            assert header_secret not in repr(dict(span_attributes))
            for attribute in observability.HTTP_SERVER_SPAN_ATTRIBUTE_SANITIZERS:
                if attribute in span_attributes:
                    assert "?" not in str(span_attributes[attribute])
                    assert "#" not in str(span_attributes[attribute])
            if "url.query" in span_attributes:
                assert span_attributes["url.query"] == ""
            if span_attributes.get("http.route") == "/items/{item_id}":
                path_bearing_attributes = {
                    attribute: value
                    for attribute, value in span_attributes.items()
                    if attribute in {"http.target", "http.url", "url.full", "url.path"}
                    and "/items/local-item-123" in str(value)
                }
                assert path_bearing_attributes
    finally:
        FastAPIInstrumentor.uninstrument_app(application)
