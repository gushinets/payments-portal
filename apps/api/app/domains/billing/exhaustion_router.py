"""Authenticated backend exhaustion receiver; ACK follows the durable hint commit."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response

from app.core.backend_consumers import BackendPermission
from app.domains.billing.allowance_exhaustion import AllowanceExhaustion, accept_exhaustion
from app.domains.billing.contracts import BillingRefused
from app.domains.catalog.publication import SessionFactory
from app.http.backend_auth import BackendPrincipal, authenticate_backend
from app.http.backend_session_policy import BackendErrorResponse
from app.http.dependencies import get_session_factory

router = APIRouter(tags=["allowance-exhaustion"])


@router.post(
    "/internal/v1/allowance-exhaustions",
    status_code=204,
    summary="Durably accept one immutable allowance exhaustion hint (V1)",
    description="Requires BackendServiceBearer with allowance-exhaustion:write. Validates the sender's "
    "product and retained source/backend ownership plus the full issued tuple. 204 follows durable commit, "
    "including duplicates and historical cycles. All responses are no-store; browser Origin is refused. "
    "The hint can schedule GET-only reconciliation; it never revokes, refills or sends financial commands.",
    responses={status: {"model": BackendErrorResponse} for status in (401, 403, 409, 422, 503)},
)
def allowance_exhaustion(
    payload: AllowanceExhaustion,
    principal: Annotated[BackendPrincipal, Depends(authenticate_backend)],
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
) -> Response:
    try:
        if BackendPermission.WRITE_EXHAUSTION not in principal.consumer.permissions:
            raise BillingRefused("allowance_exhaustion_forbidden", 403)
        accept_exhaustion(factory, principal.consumer, payload)
    except BillingRefused as error:
        raise HTTPException(error.status, detail={"code": error.code}) from None
    return Response(status_code=204)
