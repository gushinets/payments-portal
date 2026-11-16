"""Authenticated usage readback, separate from the reserved local access path."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, Security
from fastapi.security import HTTPAuthorizationCredentials

from app.composition.paid_usage import PaidUsageResources
from app.core.observability import request_id_context
from app.core.settings import settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.usage_contracts import PaidUsageErrorResponse, PaidUsageResponse
from app.http.backend_auth import portal_user_bearer

router = APIRouter(
    prefix="/api",
    tags=["paid-usage"],
    responses={status: {"model": PaidUsageErrorResponse} for status in (401, 403, 503)},
)


async def usage_resources(request: Request) -> PaidUsageResources:
    return request.app.state.paid_usage


@router.get(
    "/paid-usage",
    response_model=PaidUsageResponse,
    description=(
        "Read actual usage for server-selected current or eligible historical allowances. "
        "Requires an active verified-email Portal session. No caller-selected owner or allowance IDs. "
        "No-store responses; backend outages and concurrent paid-state changes return retryable 503."
    ),
)
async def paid_usage(
    response: Response,
    reads: Annotated[PaidUsageResources, Depends(usage_resources)],
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(portal_user_bearer)],
) -> PaidUsageResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        if credentials is None:
            raise BillingRefused("billing_session_required", 401)
        return await reads.read(settings, credentials.credentials)
    except BillingRefused as error:
        raise HTTPException(
            status_code=error.status,
            detail={"code": error.code, "request_id": request_id_context.get()},
            headers={"Cache-Control": "no-store"},
        ) from None
