"""Controlled OTLP/ASGI checks in a fresh process, including production dependencies.

Usage: PYTHONPATH=apps/api python security/trivy/verify-api-telemetry.py
Only synthetic data and a disposable loopback collector are used.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.metadata import version

import httpx
from google.protobuf.json_format import MessageToDict
from opentelemetry import metrics, trace
from opentelemetry._logs import get_logger_provider
from opentelemetry.proto.collector.logs.v1.logs_service_pb2 import (
    ExportLogsServiceRequest,
)
from opentelemetry.proto.collector.metrics.v1.metrics_service_pb2 import (
    ExportMetricsServiceRequest,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import (
    ExportTraceServiceRequest,
)
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

TRACE_ID = "1234567890abcdef1234567890abcdef"
PARENT_ID = "1234567890abcdef"
MARKERS = (
    "synthetic-auth-private-743",
    "synthetic-cookie-private-743",
    "synthetic-query-private-743",
    "synthetic-exception-private-743",
)
MESSAGES = {
    "/v1/traces": ExportTraceServiceRequest,
    "/v1/metrics": ExportMetricsServiceRequest,
    "/v1/logs": ExportLogsServiceRequest,
}


def main() -> None:
    received: dict[str, list[dict]] = {path: [] for path in MESSAGES}

    class Collector(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            payload = self.rfile.read(int(self.headers["Content-Length"]))
            message = MESSAGES[self.path]()
            message.ParseFromString(payload)
            received[self.path].append(MessageToDict(message))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:
            pass

    collector = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    thread = threading.Thread(target=collector.serve_forever, daemon=True)
    thread.start()
    os.environ.update(
        {
            "APP_ENV": "test",
            "APP_PUBLIC_BASE_URL": "http://localhost:3000",
            "INSTANCE_TENANT_ID": "anytoolai",
            "INSTANCE_REGION": "ru",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "POSTGRES_DB": "anytoolai_test",
            "POSTGRES_USER": "anytoolai",
            "POSTGRES_PASSWORD": "synthetic",
            "POSTGRES_HOST": "postgres",
            "POSTGRES_PORT": "5432",
            "CORS_ALLOW_ORIGINS": "http://localhost:3000",
            "SKIP_LEGAL_SEED": "true",
            "BILLING_WORKER_ENABLED": "false",
            "OTEL_SDK_DISABLED": "false",
            "OTEL_EXPORTER_OTLP_ENDPOINT": f"http://127.0.0.1:{collector.server_port}",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
            "NO_PROXY": "127.0.0.1,localhost",
            "OTEL_EXPORTER_OTLP_COMPRESSION": "none",
        }
    )
    # Do not inherit header-capture or exporter credentials from the caller.
    for key in tuple(os.environ):
        if key.startswith("OTEL_INSTRUMENTATION_HTTP_CAPTURE_HEADERS") or key.endswith(
            "_HEADERS"
        ):
            if key.startswith("OTEL_"):
                del os.environ[key]
    from app.main import app
    from app.core import observability

    # The in-process HTTPX test driver shares root handlers with the server.
    # Its client-side URL logging is not server telemetry from an inbound request.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    formatted: list[dict] = []

    @app.get("/telemetry-check")
    async def telemetry_check() -> dict[str, str]:
        carrier: dict[str, str] = {}
        TraceContextTextMapPropagator().inject(carrier)
        record = logging.LogRecord(
            "payment_portal.verification",
            logging.INFO,
            __file__,
            1,
            "synthetic_telemetry_check",
            (),
            None,
        )
        formatted.append(json.loads(observability.JsonFormatter().format(record)))
        logging.getLogger("payment_portal.verification").info(
            "synthetic_telemetry_check"
        )
        observability.record_legal_acceptance("synthetic")
        return carrier

    @app.get("/telemetry-failure")
    @observability.traced("verification.failure")
    async def telemetry_failure() -> None:
        raise ValueError(MARKERS[3])

    async def requests() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            for state, expected in (
                ("vendor=value", "vendor=value"),
                ("vendor=value,vendor=duplicate", ""),
                ("vendor=value" + " " * 8192, ""),
                ("\t" * 100_000 + "!", ""),
            ):
                response = await client.get(
                    "/telemetry-check?token=" + MARKERS[2],
                    headers={
                        "traceparent": f"00-{TRACE_ID}-{PARENT_ID}-01",
                        "tracestate": state,
                        "X-Request-ID": "synthetic-request-743",
                        "Authorization": "Bearer " + MARKERS[0],
                        "Cookie": MARKERS[1],
                    },
                )
                assert response.status_code == 200
                assert response.headers["X-Request-ID"] == "synthetic-request-743"
                assert response.json()["traceparent"].split("-")[1] == TRACE_ID
                assert response.json().get("tracestate", "") == expected
            assert (await client.get("/telemetry-failure")).status_code == 500
            assert (await client.get("/api/health/live")).status_code == 200

    try:
        asyncio.run(requests())
        tracer = trace.get_tracer_provider()
        meter = metrics.get_meter_provider()
        logger = get_logger_provider()
        assert tracer.force_flush(timeout_millis=10_000)
        assert meter.force_flush(timeout_millis=10_000)
        assert logger.force_flush(timeout_millis=10_000)
        assert all(received.values()), (
            "all three configured OTLP exporters must deliver"
        )
        for record in formatted:
            assert record["trace_id"] == TRACE_ID
            assert record["request_id"] == "synthetic-request-743"
            assert len(record["span_id"]) == 16
        exported = json.dumps(received)
        assert all(marker not in exported for marker in MARKERS)
        assert "exception.stacktrace" not in exported
        assert "synthetic_telemetry_check" in exported
        print(
            json.dumps(
                {
                    "result": "passed",
                    "exported_signals": sorted(received),
                    "versions": {
                        name: version(name)
                        for name in (
                            "opentelemetry-api",
                            "opentelemetry-sdk",
                            "opentelemetry-exporter-otlp-proto-http",
                            "opentelemetry-instrumentation-fastapi",
                            "opentelemetry-instrumentation-sqlalchemy",
                            "certifi",
                        )
                    },
                }
            )
        )
    finally:
        trace.get_tracer_provider().shutdown()
        metrics.get_meter_provider().shutdown()
        get_logger_provider().shutdown()
        collector.shutdown()
        collector.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    main()
