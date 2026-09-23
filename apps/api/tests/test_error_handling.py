from __future__ import annotations

import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.core.errors import AppError
from app.core.url_validation import parse_absolute_url
from app.domains.identity.errors import (
    InvalidOrExpiredResetTokenError,
    PasswordResetError,
    PasswordResetRateLimitedError,
)
import app.domains.legal.router as legal_router
from app.domains.legal.errors import (
    DocumentVersionNotFoundError,
    InvalidAcceptanceTextHashError,
    LegalAcceptanceError,
)
from app.domains.legal.router import AcceptDocumentRequest
from app.http_errors import app_error_handler
from app.infrastructure.sentry import Operation
from app.main import create_app


class UnmappedPasswordResetError(PasswordResetError):
    pass


class UnmappedLegalAcceptanceError(LegalAcceptanceError):
    code = "new_legal_acceptance_error"


def make_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/test-error",
            "headers": [],
            "query_string": b"",
            "route": SimpleNamespace(path="/test-error"),
        }
    )


def make_legal_acceptance_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/legal/acceptances",
            "headers": [(b"user-agent", b"test")],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
        }
    )


def raise_legal_error(error: LegalAcceptanceError, *args: object, **kwargs: object) -> None:
    raise error


def call_legal_acceptance_route(monkeypatch: pytest.MonkeyPatch, error: LegalAcceptanceError) -> None:
    monkeypatch.setattr(legal_router, "accept_legal_document", lambda *args, **kwargs: raise_legal_error(error))
    legal_router.accept_document(
        payload=AcceptDocumentRequest(
            document_version_id="00000000-0000-0000-0000-000000000001",
            acceptance_text_hash="f" * 64,
        ),
        request=make_legal_acceptance_request(),
        current=(object(), object()),
        db=object(),
    )


@pytest.mark.parametrize(
    ("error", "status_code", "detail"),
    [
        (DocumentVersionNotFoundError(), 404, "document_version_not_found"),
        (InvalidAcceptanceTextHashError(), 400, "invalid_acceptance_text_hash"),
    ],
)
def test_legal_acceptance_error_mapping_preserves_public_contract(
    monkeypatch: pytest.MonkeyPatch,
    error: LegalAcceptanceError,
    status_code: int,
    detail: str | dict[str, str],
) -> None:
    with pytest.raises(HTTPException) as raised:
        call_legal_acceptance_route(monkeypatch, error)

    assert raised.value.status_code == status_code
    assert raised.value.detail == detail


def test_unmapped_legal_acceptance_error_fails_closed_through_app_error_handler(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = UnmappedLegalAcceptanceError()

    with pytest.raises(UnmappedLegalAcceptanceError):
        call_legal_acceptance_route(monkeypatch, error)

    with patch("app.http_errors.report_exception") as report_exception:
        response = app_error_handler(make_request(), error)

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": {"code": "internal_server_error"}}
    report_exception.assert_called_once()


def test_create_app_registers_the_central_app_error_handler() -> None:
    application = create_app()

    assert application.exception_handlers[AppError] is app_error_handler


def test_sentry_is_configured_after_observability_at_the_composition_root() -> None:
    source = Path(create_app.__code__.co_filename).read_text(encoding="utf-8")

    assert source.rfind("configure_observability(app, engine)") < source.rfind("configure_sentry(settings)")


def test_unmapped_app_errors_fail_closed_with_generic_detail() -> None:
    error = AppError(
        "internal_secret_error",
        message_safe="internal application message",
        details_safe={"token": "secret-token"},
    )
    with patch("app.http_errors.report_exception") as report_exception:
        response = app_error_handler(make_request(), error)

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": {"code": "internal_server_error"}}
    report_exception.assert_called_once()
    assert report_exception.call_args.args == (error,)


def test_unmapped_password_reset_errors_fail_closed_with_generic_detail() -> None:
    error = UnmappedPasswordResetError()
    with patch("app.http_errors.report_exception") as report_exception:
        response = app_error_handler(make_request(), error)

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": {"code": "internal_server_error"}}
    report_exception.assert_called_once()
    assert report_exception.call_args.args == (error,)


def test_unmapped_app_error_logs_one_bounded_failure(caplog: pytest.LogCaptureFixture) -> None:
    secret_message = "application secret must not be logged"
    error = AppError(
        "internal_secret_error",
        message_safe=secret_message,
        details_safe={"authorization": "Bearer secret-token"},
    )

    with (
        patch("app.http_errors.report_exception") as report_exception,
        caplog.at_level(logging.ERROR, logger="payment_portal.http"),
    ):
        response = app_error_handler(make_request(), error)

    diagnostics = [record for record in caplog.records if record.getMessage() == "http_internal_failure"]
    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": {"code": "internal_server_error"}}
    assert len(diagnostics) == 1
    assert diagnostics[0].structured["error_type"] == "AppError"
    assert diagnostics[0].structured["error_code"] == "internal_secret_error"
    report_exception.assert_called_once_with(
        error,
        operation=Operation.HTTP_REQUEST,
        method="POST",
        route="/test-error",
        error_code="internal_secret_error",
        failure_location=None,
    )
    assert secret_message not in caplog.text
    assert "secret-token" not in caplog.text


def test_semantic_app_error_logs_type_without_null_error_code(
    caplog: pytest.LogCaptureFixture,
) -> None:
    error = UnmappedPasswordResetError()
    with (
        patch("app.http_errors.report_exception") as report_exception,
        caplog.at_level(logging.ERROR, logger="payment_portal.http"),
    ):
        response = app_error_handler(make_request(), error)

    diagnostics = [record for record in caplog.records if record.getMessage() == "http_internal_failure"]
    assert response.status_code == 500
    assert len(diagnostics) == 1
    assert diagnostics[0].structured["error_type"] == "UnmappedPasswordResetError"
    assert "error_code" not in diagnostics[0].structured
    report_exception.assert_called_once_with(
        error,
        operation=Operation.HTTP_REQUEST,
        method="POST",
        route="/test-error",
        error_code=None,
        failure_location=None,
    )


def test_unexpected_failures_are_converted_and_logged_safely(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_message = "unexpected secret token: do-not-log"
    request_value = "request-secret-value"
    raised_errors: list[RuntimeError] = []

    def raise_unexpected_failure(request_value: str) -> None:
        local_secret = "local-secret-value"
        del local_secret
        error = RuntimeError(secret_message)
        raised_errors.append(error)
        raise error

    application = create_app()
    application.add_api_route(
        "/test-unexpected/{request_value}",
        raise_unexpected_failure,
        methods=["GET"],
    )

    with (
        patch("app.http_errors.report_exception") as report_exception,
        caplog.at_level(logging.ERROR, logger="payment_portal.http"),
    ):
        response = TestClient(application).get(
            f"/test-unexpected/{request_value}?query_secret=query-secret-value",
            headers={"Authorization": "Bearer header-secret-value"},
        )

    diagnostics = [record for record in caplog.records if record.getMessage() == "http_internal_failure"]
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_server_error"}}
    assert response.headers["X-Request-ID"]
    assert len(diagnostics) == 1
    structured = diagnostics[0].structured
    assert structured["method"] == "GET"
    assert structured["route"] == "/test-unexpected/{request_value}"
    assert structured["error_type"] == "RuntimeError"
    assert "failure_location" not in structured
    assert "unexpected_failure_middleware" not in str(structured)
    assert secret_message not in caplog.text
    assert request_value not in caplog.text
    assert "query-secret-value" not in caplog.text
    assert "header-secret-value" not in caplog.text
    assert "local_secret" not in caplog.text
    assert "raise RuntimeError" not in caplog.text
    assert "Traceback (most recent call last)" not in caplog.text
    assert len(raised_errors) == 1
    report_exception.assert_called_once_with(
        raised_errors[0],
        operation=Operation.HTTP_REQUEST,
        method="GET",
        route="/test-unexpected/{request_value}",
        error_code=None,
        failure_location=None,
    )


def test_unexpected_failures_from_application_code_identify_the_origin_safely(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_message = "unexpected secret token: do-not-log"

    def raise_application_failure() -> None:
        parse_absolute_url(secret_message)

    application = create_app()
    application.add_api_route(
        "/test-application-failure",
        raise_application_failure,
        methods=["GET"],
    )

    with (
        patch("app.http_errors.report_exception") as report_exception,
        caplog.at_level(logging.ERROR, logger="payment_portal.http"),
    ):
        response = TestClient(application).get(
            "/test-application-failure",
            headers={"Authorization": "Bearer header-secret-value"},
        )

    diagnostics = [record for record in caplog.records if record.getMessage() == "http_internal_failure"]
    assert response.status_code == 500
    assert response.json() == {"detail": {"code": "internal_server_error"}}
    assert response.headers["X-Request-ID"]
    assert len(diagnostics) == 1
    structured = diagnostics[0].structured
    assert structured["error_type"] == "ValueError"
    assert set(structured["failure_location"]) == {"module", "function", "line"}
    assert structured["failure_location"]["module"] == "apps/api/app/core/url_validation.py"
    assert structured["failure_location"]["function"] == "parse_absolute_url"
    assert isinstance(structured["failure_location"]["line"], int)
    reported_error = report_exception.call_args.args[0]
    assert isinstance(reported_error, ValueError)
    report_exception.assert_called_once_with(
        reported_error,
        operation=Operation.HTTP_REQUEST,
        method="GET",
        route="/test-application-failure",
        error_code=None,
        failure_location=structured["failure_location"],
    )
    assert "unexpected_failure_middleware" not in str(structured)
    assert secret_message not in caplog.text
    assert "header-secret-value" not in caplog.text
    assert "Traceback (most recent call last)" not in caplog.text


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (PasswordResetRateLimitedError(), 429, "password_reset_rate_limited"),
        (InvalidOrExpiredResetTokenError(), 400, "invalid_or_expired_reset_token"),
    ],
)
def test_password_reset_app_errors_use_structured_code(
    error: PasswordResetError,
    status_code: int,
    code: str,
) -> None:
    with patch("app.http_errors.report_exception") as report_exception:
        response = app_error_handler(make_request(), error)

    assert response.status_code == status_code
    assert json.loads(response.body) == {"detail": {"code": code}}
    report_exception.assert_not_called()
