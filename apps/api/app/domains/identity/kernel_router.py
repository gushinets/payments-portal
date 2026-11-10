"""Portal-owned delegation wire boundary. Secret bodies never enter error responses."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import settings
from app.domains.identity.services.kernel_delegation import (
    DelegationUnavailableError,
    InvalidDelegationError,
    exchange_code,
    introspect_token,
    issue_code,
)
from app.http.kernel_auth import KernelPrincipal, authorize_exchange, authorize_introspection
from app.http.kernel_session_policy import KernelErrorResponse

router = APIRouter(
    tags=["kernel-session"],
    responses={status: {"model": KernelErrorResponse} for status in (401, 422, 503)},
)


class KernelCodeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)
    code_challenge_method: Literal["S256"]


class KernelCodeResponse(BaseModel):
    code: str = Field(repr=False)
    expires_at: datetime


class KernelExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)
    code_verifier: str = Field(pattern=r"^[A-Za-z0-9._~-]{43,128}$", repr=False)


class KernelExchangeResponse(BaseModel):
    schema_version: Literal[1] = 1
    access_token: str = Field(repr=False)
    token_type: Literal["Bearer"] = "Bearer"
    tenant_id: str
    region: str
    user_id: UUID
    expires_at: datetime


class KernelIntrospectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    access_token: str = Field(min_length=43, max_length=512, repr=False)


class KernelIntrospectionResponse(BaseModel):
    schema_version: Literal[1] = 1
    tenant_id: str
    region: str
    user_id: UUID
    valid_until: datetime


def require_portal_bearer(request: Request) -> str:
    headers = request.headers.getlist("authorization")
    scheme, _, token = (headers[0] if len(headers) == 1 else "").partition(" ")
    if scheme.lower() != "bearer" or not token or token != token.strip():
        raise HTTPException(
            401, detail={"code": "kernel_parent_authority_invalid"}, headers={"WWW-Authenticate": "Bearer"}
        )
    return token


def _refusal(error: InvalidDelegationError) -> HTTPException:
    return HTTPException(401, detail={"code": error.code}, headers={"WWW-Authenticate": "Bearer"})


@router.post("/api/kernel-session-codes")
def create_kernel_code(
    payload: KernelCodeRequest,
    token: Annotated[str, Depends(require_portal_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> KernelCodeResponse:
    try:
        result = issue_code(
            db,
            token=token,
            tenant_id=settings.instance_tenant_id,
            region=settings.instance_region,
            code_challenge=payload.code_challenge,
        )
        return KernelCodeResponse(code=result.code, expires_at=result.expires_at)
    except InvalidDelegationError as error:
        raise _refusal(error) from None
    except DelegationUnavailableError:
        raise HTTPException(503, detail={"code": "kernel_session_unavailable"}) from None


@router.post("/internal/v1/kernel-sessions/exchange", responses={403: {"model": KernelErrorResponse}})
def exchange_kernel_code(
    payload: KernelExchangeRequest,
    principal: Annotated[KernelPrincipal, Depends(authorize_exchange)],
    db: Annotated[Session, Depends(get_db)],
) -> KernelExchangeResponse:
    try:
        result = exchange_code(
            db,
            code=payload.code,
            verifier=payload.code_verifier,
            tenant_id=principal.tenant_id,
            region=principal.region,
        )
        return KernelExchangeResponse(
            access_token=result.access_token,
            tenant_id=result.identity.tenant_id,
            region=result.identity.region,
            user_id=result.identity.user_id,
            expires_at=result.identity.expires_at,
        )
    except InvalidDelegationError as error:
        raise _refusal(error) from None
    except DelegationUnavailableError:
        raise HTTPException(503, detail={"code": "kernel_session_unavailable"}) from None


@router.post("/internal/v1/kernel-sessions/introspect", responses={403: {"model": KernelErrorResponse}})
def introspect_kernel_token(
    payload: KernelIntrospectionRequest,
    principal: Annotated[KernelPrincipal, Depends(authorize_introspection)],
    db: Annotated[Session, Depends(get_db)],
) -> KernelIntrospectionResponse:
    if settings.paid_access_clock_skew_seconds is None:
        raise HTTPException(503, detail={"code": "kernel_session_unavailable"})
    try:
        result = introspect_token(
            db,
            token=payload.access_token,
            tenant_id=principal.tenant_id,
            region=principal.region,
            clock_skew_seconds=settings.paid_access_clock_skew_seconds,
        )
        return KernelIntrospectionResponse(
            tenant_id=result.tenant_id, region=result.region, user_id=result.user_id, valid_until=result.expires_at
        )
    except InvalidDelegationError as error:
        raise _refusal(error) from None
    except DelegationUnavailableError:
        raise HTTPException(503, detail={"code": "kernel_session_unavailable"}) from None
