from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.core.errors import AppError
from app.domains.identity.errors import (
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    InvalidOrExpiredResetTokenError,
    MissingOfferConsentError,
    MissingPersonalConsentError,
    PasswordResetRateLimitedError,
)
from app.infrastructure.sentry import Operation, report_exception


logger = logging.getLogger("payment_portal.http")
INTERNAL_ERROR_CODE = "internal_server_error"
HTTP_ERRORS_MODULE = Path(__file__).resolve()
APPLICATION_ROOT = HTTP_ERRORS_MODULE.parents[1]
REPOSITORY_ROOT = APPLICATION_ROOT.parents[2]
HTTP_ERROR_RESPONSES: dict[type[AppError], tuple[int, str]] = {
    MissingPersonalConsentError: (400, "missing_personal_consent"),
    MissingOfferConsentError: (400, "missing_offer_consent"),
    EmailAlreadyRegisteredError: (409, "email_already_registered"),
    InvalidCredentialsError: (401, "invalid_credentials"),
    PasswordResetRateLimitedError: (429, "password_reset_rate_limited"),
    InvalidOrExpiredResetTokenError: (400, "invalid_or_expired_reset_token"),
}


def _matched_route_template(request: Request) -> str | None:
    route = request.scope.get("route")
    route_path = getattr(route, "path", None)
    return route_path if isinstance(route_path, str) else None


def _application_failure_location(error: BaseException) -> dict[str, object] | None:
    location: dict[str, object] | None = None
    traceback = error.__traceback__
    while traceback is not None:
        filename = Path(traceback.tb_frame.f_code.co_filename).resolve()
        if filename.is_relative_to(APPLICATION_ROOT) and filename != HTTP_ERRORS_MODULE:
            location = {
                "module": filename.relative_to(REPOSITORY_ROOT).as_posix(),
                "function": traceback.tb_frame.f_code.co_name,
                "line": traceback.tb_lineno,
            }
        traceback = traceback.tb_next
    return location


def _report_internal_failure(request: Request, error: Exception) -> None:
    structured: dict[str, object] = {
        "method": request.method,
        "error_type": type(error).__name__,
    }
    route = _matched_route_template(request)
    if route is not None:
        structured["route"] = route
    if isinstance(error, AppError) and error.code is not None:
        structured["error_code"] = error.code
    location = _application_failure_location(error)
    if location is not None:
        structured["failure_location"] = location
    logger.error("http_internal_failure", extra={"structured": structured})
    report_exception(
        error,
        operation=Operation.HTTP_REQUEST,
        method=request.method,
        route=route,
        error_code=error.code if isinstance(error, AppError) else None,
        failure_location=location,
    )


def _internal_server_error_response() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": INTERNAL_ERROR_CODE}},
    )


def app_error_handler(request: Request, error: AppError) -> JSONResponse:
    spec = HTTP_ERROR_RESPONSES.get(type(error))
    if spec is not None:
        status_code, public_code = spec
        if status_code >= 500:
            _report_internal_failure(request, error)
        detail: dict[str, object] = {"code": public_code}
        return JSONResponse(status_code=status_code, content={"detail": detail})

    _report_internal_failure(request, error)
    return _internal_server_error_response()


async def unexpected_failure_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    try:
        return await call_next(request)
    except Exception as error:
        _report_internal_failure(request, error)
        return _internal_server_error_response()
