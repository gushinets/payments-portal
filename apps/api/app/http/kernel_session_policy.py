"""Keep private receivers outside public CORS and redact validation errors."""

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from starlette.responses import JSONResponse, Response

INTERNAL_PREFIX = "/internal/v1/kernel-sessions/"
CODE_PATH = "/api/kernel-session-codes"


def is_kernel_session_path(path: str) -> bool:
    return path.startswith(INTERNAL_PREFIX) or path == CODE_PATH


async def session_validation_error(request: Request, error: RequestValidationError) -> Response:
    if is_kernel_session_path(request.url.path):
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "kernel_session_request_invalid"}},
            headers={"Cache-Control": "no-store"},
        )
    return await request_validation_exception_handler(request, error)


async def kernel_session_policy(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if request.url.path.startswith(INTERNAL_PREFIX) and "origin" in request.headers:
        return JSONResponse(
            status_code=403,
            content={"detail": {"code": "browser_access_forbidden"}},
            headers={"Cache-Control": "no-store"},
        )
    response = await call_next(request)
    if is_kernel_session_path(request.url.path):
        response.headers["Cache-Control"] = "no-store"
    return response
