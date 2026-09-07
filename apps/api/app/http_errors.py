from __future__ import annotations

import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from app.core.errors import AppError
from app.domains.identity.errors import CheckoutError, PasswordResetError


logger = logging.getLogger("payment_portal.http")
INTERNAL_ERROR_CODE = "internal_error"
CHECKOUT_ERROR_STATUS_CODES = {
    "unknown_product_plan": 400,
    "automatic_renewal_not_permitted": 409,
    "missing_required_documents": 409,
    "recurring_consent_required": 409,
    "provider_currency_mismatch": 409,
}
PASSWORD_RESET_ERROR_STATUS_CODES = {
    "password_reset_rate_limited": 429,
    "invalid_or_expired_reset_token": 400,
}


def app_error_handler(_: Request, error: AppError) -> JSONResponse:
    if isinstance(error, CheckoutError):
        status_code = CHECKOUT_ERROR_STATUS_CODES.get(error.code)
        if status_code is not None:
            detail: dict[str, object] = {"code": error.code}
            if error.code == "missing_required_documents" and "documents" in error.details_safe:
                detail["documents"] = error.details_safe["documents"]
            return JSONResponse(status_code=status_code, content={"detail": detail})

    if isinstance(error, PasswordResetError):
        status_code = PASSWORD_RESET_ERROR_STATUS_CODES.get(error.code)
        if status_code is not None:
            return JSONResponse(
                status_code=status_code,
                content={"detail": {"code": error.code}},
            )

    logger.error(
        "unmapped_app_error",
        extra={"structured": {"error_type": type(error).__name__}},
    )
    return JSONResponse(
        status_code=500,
        content={"detail": {"code": INTERNAL_ERROR_CODE}},
    )
