from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from unittest.mock import patch

import pytest
import sentry_sdk
from opentelemetry import trace
from opentelemetry.trace import NonRecordingSpan, SpanContext, TraceFlags
from pydantic import ValidationError
from sentry_sdk.client import Client
from sentry_sdk.integrations.atexit import AtexitIntegration
from sentry_sdk.transport import Transport

from app.core.errors import AppError
from app.core.observability import request_id_context
from app.core.settings import AppEnv, Settings
from app.infrastructure import sentry as sentry_reporting
from app.infrastructure.sentry import (
    FailureCategory,
    Operation,
    classify_exception,
    configure_sentry,
    report_exception,
)
from app.payment_providers.contracts import RetryDisposition
from app.payment_providers.errors import (
    PaymentProviderConfigurationError,
    PaymentsError,
    PaymentsIdempotencyKeyRequiredError,
    PaymentsOperationDeclinedError,
    PaymentsTimeoutError,
    PaymentsUpstreamError,
)
from apps.api.tests.support.settings import DEFAULT_API_TEST_ENV


TEST_DSN = "http://public@example.test/1"
HTTPS_TEST_DSN = "https://public@example.test/1"
TEST_RELEASE = "payments-portal-api@458"
TRACE_ID = "0123456789abcdef0123456789abcdef"
SPAN_ID = "0123456789abcdef"
RUN_ID = "123e4567-e89b-12d3-a456-426614174000"


class RecordingTransport(Transport):
    def __init__(self) -> None:
        super().__init__()
        self.items: list[tuple[str, dict[str, object]]] = []

    def capture_envelope(self, envelope: object) -> None:
        for item in envelope.items:  # type: ignore[attr-defined]
            payload = item.payload.json
            if isinstance(payload, dict):
                self.items.append((item.headers["type"], payload))


def make_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "app_env": AppEnv.TEST,
        "app_public_base_url": "http://localhost:3000",
        "database_url": "sqlite+pysqlite:///:memory:",
        "cloudpayments_enabled": False,
        "cors_allow_origins": ("http://localhost:3000",),
        "postgres_db": "anytoolai_test",
        "postgres_user": "anytoolai",
        "postgres_password": "anytoolai",
        "postgres_host": "postgres",
        "postgres_port": 5432,
        "sentry_dsn": TEST_DSN,
        "sentry_release": TEST_RELEASE,
    }
    return Settings(**(values | overrides))


def make_production_settings(**overrides: object) -> Settings:
    return make_settings(
        app_env=AppEnv.PRODUCTION,
        app_public_base_url="https://payments.example.com",
        cors_allow_origins=("https://payments.example.com",),
        **overrides,
    )


def sentry_options() -> dict[str, object]:
    with patch.object(sentry_reporting.sentry_sdk, "init") as init:
        configure_sentry(make_settings())
    return dict(init.call_args.kwargs)


@contextmanager
def capture_events() -> Iterator[tuple[RecordingTransport, sentry_sdk.Scope]]:
    transport = RecordingTransport()
    client = Client(**sentry_options(), transport=transport)
    with sentry_sdk.isolation_scope() as scope:
        scope.set_client(client)
        yield transport, scope
    client.close()


def event_payload(transport: RecordingTransport) -> dict[str, object]:
    assert [item_type for item_type, _payload in transport.items] == ["event"]
    return transport.items[0][1]


def test_canonical_pytest_environment_disables_real_sentry() -> None:
    assert os.environ["SENTRY_DSN"] == ""
    assert os.environ["SENTRY_RELEASE"] == ""


def test_empty_dsn_is_a_real_noop() -> None:
    with patch.object(sentry_reporting.sentry_sdk, "init") as init:
        configure_sentry(make_settings(sentry_dsn="", sentry_release=""))

    init.assert_not_called()


def test_settings_own_and_normalize_sentry_environment_configuration() -> None:
    environment = {
        **DEFAULT_API_TEST_ENV,
        "SENTRY_DSN": f"  {TEST_DSN}  ",
        "SENTRY_RELEASE": f"  {TEST_RELEASE}  ",
    }
    with patch.dict(os.environ, environment, clear=True):
        settings = Settings(_env_file=None)

    assert settings.sentry_dsn == TEST_DSN
    assert settings.sentry_release == TEST_RELEASE

    with (
        patch.object(sentry_reporting.os, "getenv", side_effect=AssertionError("direct environment lookup")),
        patch.object(sentry_reporting.sentry_sdk, "init") as init,
    ):
        configure_sentry(settings)

    assert init.call_args.kwargs["dsn"] == TEST_DSN
    assert init.call_args.kwargs["release"] == TEST_RELEASE
    assert init.call_args.kwargs["environment"] == "test"


def test_settings_require_release_when_sentry_is_enabled() -> None:
    with pytest.raises(ValidationError) as error:
        make_settings(sentry_release="   ")

    assert "SENTRY_RELEASE is required when SENTRY_DSN is configured" in str(error.value)


def test_settings_reject_http_sentry_dsn_in_production() -> None:
    with pytest.raises(ValidationError) as error:
        make_production_settings(sentry_dsn=TEST_DSN)

    assert "SENTRY_DSN must use https in production" in str(error.value)


def test_settings_accept_https_sentry_dsn_in_production() -> None:
    settings = make_production_settings(sentry_dsn=HTTPS_TEST_DSN)

    assert settings.sentry_dsn == HTTPS_TEST_DSN


@pytest.mark.parametrize("app_env", [AppEnv.DEVELOPMENT, AppEnv.TEST])
def test_settings_allow_http_sentry_dsn_outside_production(app_env: AppEnv) -> None:
    settings = make_settings(app_env=app_env, sentry_dsn=TEST_DSN)

    assert settings.sentry_dsn == TEST_DSN


def test_settings_allow_empty_sentry_dsn_in_production() -> None:
    settings = make_production_settings(sentry_dsn="", sentry_release="")

    assert settings.sentry_dsn == ""
    assert settings.sentry_release == ""


def test_enabled_configuration_allows_only_safe_shutdown_integration(
    capsys: pytest.CaptureFixture[str],
) -> None:
    options = sentry_options()

    assert options["default_integrations"] is False
    assert options["auto_enabling_integrations"] is False
    assert options["send_default_pii"] is False
    assert options["include_local_variables"] is False
    assert options["include_source_context"] is False
    assert options["max_request_body_size"] == "never"
    assert options["traces_sample_rate"] == 0.0
    assert options["profiles_sample_rate"] == 0.0
    assert options["enable_logs"] is False
    assert "enable_metrics" not in options
    assert options["before_send_metric"]({"name": "must-not-send"}, {}) is None
    assert options["propagate_traces"] is False
    assert options["auto_session_tracking"] is False
    assert options["sample_rate"] == 1.0
    assert options["debug"] is False
    assert options["keep_alive"] is False
    assert options["spotlight"] is False
    assert len(options["integrations"]) == 1
    integration = options["integrations"][0]
    assert isinstance(integration, AtexitIntegration)
    assert integration.callback(1, 2) is None
    assert capsys.readouterr() == ("", "")

    client = Client(**options, transport=RecordingTransport())
    try:
        assert set(client.integrations) == {"atexit"}
        assert client.options["traces_sample_rate"] == 0.0
        assert client.options["profiles_sample_rate"] == 0.0
    finally:
        client.close()


def test_metric_telemetry_is_dropped_before_batching() -> None:
    with capture_events() as (transport, _scope):
        sentry_sdk.metrics.count("must.not.be.sent", 1)
        sentry_sdk.get_client().metrics_batcher.flush()

    assert transport.items == []


def test_spotlight_environment_variable_cannot_enable_spotlight() -> None:
    with patch.dict(os.environ, {"SENTRY_SPOTLIGHT": "true"}):
        options = sentry_options()
        client = Client(**options, transport=RecordingTransport())

    try:
        assert client.options["spotlight"] is False
        assert client.spotlight is None
    finally:
        client.close()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (
            PaymentsOperationDeclinedError("declined", provider="cloudpayments", operation="charge"),
            None,
        ),
        (
            PaymentsTimeoutError("timeout", retry_disposition=RetryDisposition.RETRYABLE),
            FailureCategory.UNKNOWN_EXTERNAL_OUTCOME,
        ),
        (
            PaymentsIdempotencyKeyRequiredError("idempotency_required"),
            FailureCategory.INTERNAL_APPLICATION_FAILURE,
        ),
        (
            PaymentProviderConfigurationError("provider_configuration"),
            FailureCategory.INTERNAL_APPLICATION_FAILURE,
        ),
        (
            PaymentsUpstreamError("upstream", retry_disposition=RetryDisposition.RETRYABLE),
            FailureCategory.INTEGRATION_FAILURE,
        ),
        (PaymentsError("provider"), FailureCategory.INTEGRATION_FAILURE),
        (AppError("application"), FailureCategory.INTERNAL_APPLICATION_FAILURE),
        (RuntimeError("unexpected"), FailureCategory.UNEXPECTED_EXCEPTION),
    ],
)
def test_exception_classification_is_semantic(
    error: Exception,
    expected: FailureCategory | None,
) -> None:
    assert classify_exception(error) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (r"app\payment_providers\registry.py", "app/payment_providers/registry.py"),
        (r"tests\test_sentry_reporting.py", "tests/test_sentry_reporting.py"),
    ],
)
def test_repository_relative_path_normalizes_safe_windows_paths(value: str, expected: str) -> None:
    assert sentry_reporting._repository_relative_path(value, maximum_length=512) == expected


@pytest.mark.parametrize(
    "value",
    [
        r"C:\secret\file.py",
        r"C:secret\file.py",
        r"\\server\share\file.py",
        r"\rooted\file.py",
        "/absolute/file.py",
        "../secret.py",
        r"app\..\secret.py",
        r"app\\file.py",
    ],
)
def test_repository_relative_path_rejects_unsafe_paths(value: str) -> None:
    assert sentry_reporting._repository_relative_path(value, maximum_length=512) is None


def capture_correlated_failure(
    *,
    request_id: str = "request.safe-458",
    run_id: str = RUN_ID,
) -> dict[str, object]:
    span_context = SpanContext(
        trace_id=int(TRACE_ID, 16),
        span_id=int(SPAN_ID, 16),
        is_remote=False,
        trace_flags=TraceFlags(TraceFlags.SAMPLED),
    )
    request_token = request_id_context.set(request_id)
    try:
        with capture_events() as (transport, _scope), trace.use_span(NonRecordingSpan(span_context)):
            try:
                try:
                    _local_secret = "local-secret-458"
                    raise ValueError("inner-message-secret-458")
                except ValueError as error:
                    raise RuntimeError("outer-message-secret-458") from error
            except RuntimeError as error:
                report_exception(
                    error,
                    operation=Operation.HTTP_REQUEST,
                    run_id=run_id,
                    method="POST",
                    route="/api/orders/{order_id}",
                    error_code="provider.timeout",
                    invariant="subscription.state",
                    batch_size=1000,
                    failure_location={
                        "module": "apps/api/app/payment_providers/registry.py",
                        "function": "get",
                        "line": 42,
                    },
                )
        return event_payload(transport)
    finally:
        request_id_context.reset(request_token)


def test_captured_exception_is_one_allowlisted_privacy_safe_error_event() -> None:
    event = capture_correlated_failure()

    assert set(event) == {
        "event_id",
        "timestamp",
        "platform",
        "level",
        "exception",
        "tags",
        "contexts",
        "release",
        "environment",
        "sdk",
    }
    assert event["tags"] == {
        "service": "payment-portal-api",
        "failure_category": "unexpected_exception",
        "operation": "http_request",
    }
    assert event["contexts"] == {
        "payment_portal": {
            "request_id": "request.safe-458",
            "trace_id": TRACE_ID,
            "span_id": SPAN_ID,
            "run_id": RUN_ID,
            "method": "POST",
            "route": "/api/orders/{order_id}",
            "error_code": "provider.timeout",
            "invariant": "subscription.state",
            "batch_size": 1000,
            "failure_location": {
                "module": "apps/api/app/payment_providers/registry.py",
                "function": "get",
                "line": 42,
            },
        }
    }
    assert event["release"] == TEST_RELEASE
    assert event["environment"] == "test"
    assert len(event["event_id"]) == 32
    assert event["event_id"] == event["event_id"].lower()
    assert event["sdk"] == {
        "name": "sentry.python",
        "version": sentry_sdk.VERSION,
        "packages": [{"name": "pypi:sentry-sdk", "version": sentry_sdk.VERSION}],
    }

    exception_values = event["exception"]["values"]
    assert [value["type"] for value in exception_values] == ["ValueError", "RuntimeError"]
    assert all("value" not in value for value in exception_values)
    assert all(set(value) <= {"type", "module", "stacktrace", "mechanism"} for value in exception_values)
    assert any(
        frame.get("filename") == "tests/test_sentry_reporting.py"
        for value in exception_values
        for frame in value["stacktrace"]["frames"]
    )
    assert all(
        set(frame) <= {"filename", "module", "function", "lineno", "in_app"}
        for value in exception_values
        for frame in value["stacktrace"]["frames"]
    )
    assert all(value["mechanism"] == {"type": "generic", "handled": True} for value in exception_values)

    serialized = json.dumps(event, sort_keys=True)
    for secret in ("inner-message-secret-458", "outer-message-secret-458", "local-secret-458"):
        assert secret not in serialized
    assert "fingerprint" not in event


def test_final_event_drops_hostile_sdk_and_scope_payloads() -> None:
    marker = "hostile secret 458"

    def inject_hostile_data(event: dict[str, object], _hint: dict[str, object]) -> dict[str, object]:
        event.update(
            {
                "request": {"headers": {"authorization": marker}, "query_string": marker},
                "user": {"email": marker},
                "extra": {"secret": marker},
                "breadcrumbs": {"values": [{"message": marker}]},
                "message": marker,
                "logentry": {"message": marker},
                "transaction": marker,
                "modules": {marker: marker},
                "threads": {"values": [{"name": marker}]},
                "server_name": marker,
                "fingerprint": [marker],
                "event_id": marker,
                "timestamp": marker,
                "release": marker,
                "environment": marker,
                "platform": marker,
                "level": marker,
                "sdk": {"name": marker, "version": marker, "packages": [{"name": marker, "version": marker}]},
            }
        )
        event.setdefault("tags", {})[marker] = marker
        event.setdefault("contexts", {})[marker] = {marker: marker}
        event["contexts"]["payment_portal"] = {
            "request_id": marker,
            "trace_id": marker,
            "span_id": marker,
        }
        for value in event["exception"]["values"]:
            value["value"] = marker
            for frame in value["stacktrace"]["frames"]:
                frame.update(
                    {
                        "abs_path": marker,
                        "vars": {marker: marker},
                        "pre_context": [marker],
                        "context_line": marker,
                        "post_context": [marker],
                    }
                )
        return event

    with capture_events() as (transport, scope):
        scope.add_event_processor(inject_hostile_data)
        try:
            raise RuntimeError(marker)
        except RuntimeError as error:
            report_exception(error, operation=Operation.HTTP_REQUEST)

    event = event_payload(transport)
    assert marker not in json.dumps(event, sort_keys=True)
    assert len(event["event_id"]) == 32
    assert event["release"] == TEST_RELEASE
    assert event["environment"] == "test"
    assert "timestamp" not in event
    assert "platform" not in event
    assert "level" not in event
    assert "sdk" not in event
    assert set(event) <= {
        "event_id",
        "timestamp",
        "platform",
        "level",
        "exception",
        "tags",
        "contexts",
        "release",
        "environment",
        "sdk",
    }


def test_malformed_context_values_are_dropped_from_the_final_event() -> None:
    request_token = request_id_context.set("invalid request id")
    try:
        with capture_events() as (transport, _scope):
            try:
                raise RuntimeError("not retained")
            except RuntimeError as error:
                report_exception(
                    error,
                    operation=Operation.EXPIRE_SUBSCRIPTIONS,
                    failure_category=FailureCategory.CONSISTENCY_INVARIANT_VIOLATION,
                    run_id="123E4567-E89B-12D3-A456-426614174000",
                    method="post",
                    route="/orders/{id}?secret=value",
                    error_code="UPPERCASE",
                    invariant="x" * 65,
                    batch_size=True,
                    failure_location={
                        "module": "/absolute/secret.py",
                        "function": "function name with spaces",
                        "line": 0,
                    },
                )
        event = event_payload(transport)
    finally:
        request_id_context.reset(request_token)

    assert "contexts" not in event
    assert event["tags"]["failure_category"] == "consistency_invariant_violation"


def test_correlation_values_do_not_change_grouping_inputs() -> None:
    first = capture_correlated_failure(request_id="request.first", run_id=RUN_ID)
    second = capture_correlated_failure(
        request_id="request.second",
        run_id="123e4567-e89b-12d3-a456-426614174001",
    )

    assert first["exception"] == second["exception"]
    assert first["tags"] == second["tags"]
    assert first["contexts"] != second["contexts"]
    assert "fingerprint" not in first
    assert "fingerprint" not in second


def test_declined_operation_cannot_be_forced_into_reporting() -> None:
    with capture_events() as (transport, _scope):
        report_exception(
            PaymentsOperationDeclinedError("declined", provider="cloudpayments", operation="charge"),
            operation=Operation.HTTP_REQUEST,
            failure_category=FailureCategory.INTEGRATION_FAILURE,
        )

    assert transport.items == []


def test_service_tag_reuses_the_existing_otel_service_name() -> None:
    with patch.dict(os.environ, {"OTEL_SERVICE_NAME": "payment-portal-custom"}):
        with capture_events() as (transport, _scope):
            try:
                raise RuntimeError("not retained")
            except RuntimeError as error:
                report_exception(error, operation=Operation.HTTP_REQUEST)

    assert event_payload(transport)["tags"]["service"] == "payment-portal-custom"


def test_invalid_service_tag_is_dropped_without_substituting_a_different_identity() -> None:
    with patch.dict(os.environ, {"OTEL_SERVICE_NAME": "invalid service identity"}):
        with capture_events() as (transport, _scope):
            try:
                raise RuntimeError("not retained")
            except RuntimeError as error:
                report_exception(error, operation=Operation.HTTP_REQUEST)

    assert event_payload(transport)["tags"] == {
        "failure_category": "unexpected_exception",
        "operation": "http_request",
    }


def test_reporting_failure_cannot_escape_to_the_caller(caplog: pytest.LogCaptureFixture) -> None:
    with (
        patch.object(sentry_reporting.sentry_sdk, "capture_exception", side_effect=RuntimeError("sdk secret")),
        caplog.at_level(logging.ERROR, logger="app.infrastructure.sentry"),
    ):
        report_exception(RuntimeError("application secret"), operation=Operation.HTTP_REQUEST)

    diagnostics = [record for record in caplog.records if record.getMessage() == "sentry_reporting_failed"]
    assert len(diagnostics) == 1
    assert diagnostics[0].structured == {"error_type": "RuntimeError"}
    assert "sdk secret" not in caplog.text
    assert "application secret" not in caplog.text


def test_initialization_failure_is_bounded_and_fail_safe(caplog: pytest.LogCaptureFixture) -> None:
    with (
        patch.object(sentry_reporting.sentry_sdk, "init", side_effect=RuntimeError("dsn secret")),
        caplog.at_level(logging.ERROR, logger="app.infrastructure.sentry"),
    ):
        configure_sentry(make_settings())

    diagnostics = [record for record in caplog.records if record.getMessage() == "sentry_initialization_failed"]
    assert len(diagnostics) == 1
    assert diagnostics[0].structured == {"error_type": "RuntimeError"}
    assert "dsn secret" not in caplog.text
