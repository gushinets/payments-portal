from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from pathlib import Path

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.responses import Response

from app.core.errors import AppError
from app.domains.identity.errors import (
    AutomaticRenewalNotPermittedError,
    InvalidOrExpiredResetTokenError,
    MissingRequiredDocumentsError,
    PasswordResetRateLimitedError,
    ProviderCurrencyMismatchError,
    RecurringConsentRequiredError,
    UnknownProductPlanError,
)


logger = logging.getLogger("payment_portal.http")
INTERNAL_ERROR_CODE = "internal_server_error"
REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
APPLICATION_ROOT = Path(__file__).resolve().parent
HTTP_ERRORS_MODULE = Path(__file__).resolve()
HTTP_ERROR_RESPONSES: dict[type[AppError], tuple[int, str]] = {
    UnknownProductPlanError: (400, "unknown_product_plan"),
    AutomaticRenewalNotPermittedError: (409, "automatic_renewal_not_permitted"),
    MissingRequiredDocumentsError: (409, "missing_required_documents"),
    RecurringConsentRequiredError: (409, "recurring_consent_required"),
    ProviderCurrencyMismatchError: (409, "provider_currency_mismatch"),
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


def _log_internal_failure(request: Request, error: BaseException) -> None:
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


def _internal_server_error_response() -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": INTERNAL_ERROR_CODE}},
    )


def app_error_handler(request: Request, error: AppError) -> JSONResponse:
    spec = HTTP_ERROR_RESPONSES.get(type(error))
    if spec is not None:
        status_code, public_code = spec
        detail: dict[str, object] = {"code": public_code}
        if isinstance(error, MissingRequiredDocumentsError):
            detail["documents"] = error.details_safe["documents"]
        return JSONResponse(status_code=status_code, content={"detail": detail})

    _log_internal_failure(request, error)
    return _internal_server_error_response()


async def unexpected_failure_middleware(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    try:
        return await call_next(request)
    except Exception as error:
        _log_internal_failure(request, error)
        return _internal_server_error_response()
