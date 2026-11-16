"""Keep private receivers outside public CORS and redact validation errors."""

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict
from starlette.responses import JSONResponse, Response

INTERNAL_PREFIX = "/internal/v1/backend-sessions/"
CODE_PATH = "/api/backend-session-codes"
SNAPSHOT_PREFIX = "/internal/v1/access-snapshots/"
EXHAUSTION_PATH = "/internal/v1/allowance-exhaustions"


class BackendErrorDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str


class BackendErrorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detail: BackendErrorDetail


def is_backend_session_path(path: str) -> bool:
    return path.startswith((INTERNAL_PREFIX, SNAPSHOT_PREFIX, EXHAUSTION_PATH)) or path == CODE_PATH


async def session_validation_error(request: Request, error: RequestValidationError) -> Response:
    if is_backend_session_path(request.url.path):
        return JSONResponse(
            status_code=422,
            content={"detail": {"code": "backend_session_request_invalid"}},
            headers={"Cache-Control": "no-store"},
        )
    return await request_validation_exception_handler(request, error)


async def backend_session_policy(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if request.url.path.startswith((INTERNAL_PREFIX, SNAPSHOT_PREFIX, EXHAUSTION_PATH)) and "origin" in request.headers:
        return JSONResponse(
            status_code=403,
            content={"detail": {"code": "browser_access_forbidden"}},
            headers={"Cache-Control": "no-store"},
        )
    response = await call_next(request)
    if is_backend_session_path(request.url.path):
        response.headers["Cache-Control"] = "no-store"
    return response
