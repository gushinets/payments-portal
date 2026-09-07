from __future__ import annotations

import json

import pytest
from starlette.requests import Request

from app.core.errors import AppError
from app.domains.identity.errors import CheckoutError, PasswordResetError
from app.http_errors import app_error_handler
from app.main import create_app


def make_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/auth/checkout-intent",
            "headers": [],
            "query_string": b"",
        }
    )


def test_create_app_registers_the_central_app_error_handler() -> None:
    application = create_app()

    assert application.exception_handlers[AppError] is app_error_handler


@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        ("unknown_product_plan", 400),
        ("automatic_renewal_not_permitted", 409),
        ("recurring_consent_required", 409),
        ("provider_currency_mismatch", 409),
    ],
)
def test_checkout_app_errors_use_structured_code(code: str, status_code: int) -> None:
    response = app_error_handler(make_request(), CheckoutError(code))

    assert response.status_code == status_code
    assert json.loads(response.body) == {"detail": {"code": code}}


def test_missing_documents_are_the_only_safe_details_exposed() -> None:
    response = app_error_handler(
        make_request(),
        CheckoutError(
            "missing_required_documents",
            details_safe={
                "documents": [{"document_version_id": "document-id"}],
                "internal": "must not be exposed",
            },
        ),
    )

    assert response.status_code == 409
    assert json.loads(response.body) == {
        "detail": {
            "code": "missing_required_documents",
            "documents": [{"document_version_id": "document-id"}],
        }
    }


def test_unmapped_app_errors_fail_closed_with_generic_detail() -> None:
    response = app_error_handler(
        make_request(),
        AppError(
            "provider_secret_error",
            message_safe="internal provider message",
            details_safe={"token": "secret-token"},
        ),
    )

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": {"code": "internal_error"}}


def test_unmapped_checkout_errors_fail_closed_with_generic_detail() -> None:
    response = app_error_handler(make_request(), CheckoutError("unsupported_checkout_code"))

    assert response.status_code == 500
    assert json.loads(response.body) == {"detail": {"code": "internal_error"}}


@pytest.mark.parametrize(
    ("error", "status_code", "code"),
    [
        (PasswordResetError("password_reset_rate_limited"), 429, "password_reset_rate_limited"),
        (PasswordResetError("invalid_or_expired_reset_token"), 400, "invalid_or_expired_reset_token"),
    ],
)
def test_password_reset_app_errors_use_structured_code(
    error: PasswordResetError,
    status_code: int,
    code: str,
) -> None:
    response = app_error_handler(make_request(), error)

    assert response.status_code == status_code
    assert json.loads(response.body) == {"detail": {"code": code}}
