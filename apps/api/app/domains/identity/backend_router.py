"""Portal-owned delegation wire boundary. Secret bodies never enter error responses."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.core.backend_consumers import BackendConsumer
from app.core.database import get_db
from app.core.settings import settings
from app.domains.identity.services.backend_delegation import (
    DelegationUnavailableError,
    InvalidDelegationError,
    exchange_code,
    introspect_token,
    issue_code,
    require_consumer_policy,
)
from app.http.backend_auth import BackendPrincipal, authorize_exchange, authorize_introspection
from app.http.backend_session_policy import BackendErrorResponse

router = APIRouter(
    tags=["backend-session"],
    responses={status: {"model": BackendErrorResponse} for status in (401, 403, 422, 503)},
)


class BackendCodeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        json_schema_extra={
            "examples": [
                {
                    "consumer_id": "platform-kernel",
                    "code_challenge_method": "S256",
                    "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
                }
            ]
        },
    )
    consumer_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$", examples=["platform-kernel"])
    code_challenge: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)
    code_challenge_method: Literal["S256"] = Field(examples=["S256"])


class BackendCodeResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "code": "c" * 43,
                    "expires_at": "2026-11-09T04:01:00Z",
                }
            ]
        }
    )
    code: str = Field(repr=False)
    expires_at: datetime


class BackendExchangeRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        hide_input_in_errors=True,
        json_schema_extra={
            "examples": [
                {
                    "code": "c" * 43,
                    "code_verifier": "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk",
                }
            ]
        },
    )
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$", repr=False)
    code_verifier: str = Field(pattern=r"^[A-Za-z0-9._~-]{43,128}$", repr=False)


class BackendExchangeResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "schema_version": 2,
                    "access_token": "t" * 43,
                    "token_type": "Bearer",
                    "consumer_id": "platform-kernel",
                    "consumer_policy_revision": 1,
                    "tenant_id": "anytoolai",
                    "region": "ru",
                    "user_id": "00000000-0000-4000-8000-000000000001",
                    "expires_at": "2026-11-09T04:30:00Z",
                }
            ]
        }
    )
    schema_version: Literal[2] = 2
    access_token: str = Field(repr=False)
    token_type: Literal["Bearer"] = "Bearer"
    consumer_id: str
    consumer_policy_revision: int = Field(strict=True, ge=1, le=2**53 - 1)
    tenant_id: str
    region: str
    user_id: UUID
    expires_at: datetime


class BackendIntrospectionRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid", hide_input_in_errors=True, json_schema_extra={"examples": [{"access_token": "t" * 43}]}
    )
    access_token: str = Field(
        min_length=43,
        max_length=512,
        repr=False,
        description="Secret delegated user bearer for this consumer. Service bearer stays in Authorization.",
        examples=["synthetic-delegation-" + "t" * 43],
    )


class BackendIntrospectionResponse(BaseModel):
    model_config = ConfigDict(
        json_schema_extra={
            "examples": [
                {
                    "schema_version": 2,
                    "consumer_id": "platform-kernel",
                    "consumer_policy_revision": 1,
                    "tenant_id": "anytoolai",
                    "region": "ru",
                    "user_id": "00000000-0000-4000-8000-000000000001",
                    "valid_until": "2026-11-09T04:29:55Z",
                }
            ]
        }
    )
    schema_version: Literal[2] = 2
    consumer_id: str
    consumer_policy_revision: int = Field(strict=True, ge=1, le=2**53 - 1)
    tenant_id: str
    region: str
    user_id: UUID
    valid_until: datetime


portal_user_bearer = HTTPBearer(
    scheme_name="PortalUserBearer",
    auto_error=False,
    description="Primary Portal session bearer. Used only for code issuance; never forwarded to a backend.",
)


def require_portal_bearer(
    request: Request,
    _credentials: Annotated[HTTPAuthorizationCredentials | None, Security(portal_user_bearer)],
) -> str:
    headers = request.headers.getlist("authorization")
    scheme, _, token = (headers[0] if len(headers) == 1 else "").partition(" ")
    if scheme.lower() != "bearer" or not token or token != token.strip():
        raise HTTPException(
            401, detail={"code": "backend_parent_authority_invalid"}, headers={"WWW-Authenticate": "Bearer"}
        )
    return token


def _refusal(error: InvalidDelegationError) -> HTTPException:
    return HTTPException(401, detail={"code": error.code}, headers={"WWW-Authenticate": "Bearer"})


def _require_policy(db: Session, consumer: BackendConsumer) -> None:
    try:
        require_consumer_policy(db, consumer)
    except DelegationUnavailableError:
        raise HTTPException(503, detail={"code": "backend_session_unavailable"}) from None


@router.post(
    "/api/backend-session-codes",
    summary="Issue a consumer-bound S256 authorization code",
    description="Requires PortalUserBearer. A hash-only, single-use code expires within 60 seconds and remains bound "
    "to the parent session and configured consumer. The registered callback is deployment-owned; "
    "callback/redirect body fields are refused. All responses use Cache-Control: no-store. "
    "401: invalid parent session; 403: unknown consumer; 422: invalid PKCE/body; 503: policy/storage unavailable.",
)
def create_backend_code(
    payload: BackendCodeRequest,
    token: Annotated[str, Depends(require_portal_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> BackendCodeResponse:
    consumer = next((item for item in settings.backend_consumers if item.consumer_id == payload.consumer_id), None)
    if consumer is None:
        raise HTTPException(403, detail={"code": "backend_session_forbidden"})
    _require_policy(db, consumer)
    try:
        result = issue_code(
            db,
            token=token,
            tenant_id=settings.instance_tenant_id,
            region=settings.instance_region,
            code_challenge=payload.code_challenge,
            consumer_id=consumer.consumer_id,
        )
        return BackendCodeResponse(code=result.code, expires_at=result.expires_at)
    except InvalidDelegationError as error:
        raise _refusal(error) from None
    except DelegationUnavailableError:
        raise HTTPException(503, detail={"code": "backend_session_unavailable"}) from None


@router.post(
    "/internal/v1/backend-sessions/exchange",
    summary="Redeem this backend's code once",
    description="Requires BackendServiceBearer with backend-session:exchange. Consumer identity comes from the "
    "service credential; the body contains only the code and S256 verifier. Returns a V2 delegated "
    "user bearer, canonical UUID/scope, consumer and current policy revision. Lifetime is at most "
    "30 minutes and parent expiry. No refresh token. All responses are no-store. "
    "401: invalid/used/expired/foreign code or parent; 403: scope/permission; 422: invalid body; "
    "503: policy/storage unavailable. Origin-bearing browser requests are refused.",
)
def exchange_backend_code(
    payload: BackendExchangeRequest,
    principal: Annotated[BackendPrincipal, Depends(authorize_exchange)],
    db: Annotated[Session, Depends(get_db)],
) -> BackendExchangeResponse:
    _require_policy(db, principal.consumer)
    try:
        result = exchange_code(
            db,
            code=payload.code,
            verifier=payload.code_verifier,
            consumer_id=principal.consumer.consumer_id,
            tenant_id=principal.tenant_id,
            region=principal.region,
        )
        return BackendExchangeResponse(
            consumer_id=principal.consumer.consumer_id,
            consumer_policy_revision=principal.consumer.consumer_policy_revision,
            access_token=result.access_token,
            tenant_id=result.identity.tenant_id,
            region=result.identity.region,
            user_id=result.identity.user_id,
            expires_at=result.identity.expires_at,
        )
    except InvalidDelegationError as error:
        raise _refusal(error) from None
    except DelegationUnavailableError:
        raise HTTPException(503, detail={"code": "backend_session_unavailable"}) from None


@router.post(
    "/internal/v1/backend-sessions/introspect",
    summary="Validate this backend's delegated user on every protected request",
    description="Requires BackendServiceBearer with backend-session:introspect in Authorization. The secret "
    "access_token body field contains the delegated USER bearer, not the service credential. "
    "Validates consumer audience, active user, parent revocation/expiry and current policy. "
    "Read-only; no refresh or PII. valid_until includes the configured conservative clock budget. "
    "All responses are no-store. 401: backend_delegation_expired or backend_parent_authority_invalid; "
    "403: scope/permission/browser; 422: invalid secret body; 503: policy/storage unavailable.",
)
def introspect_backend_token(
    payload: BackendIntrospectionRequest,
    principal: Annotated[BackendPrincipal, Depends(authorize_introspection)],
    db: Annotated[Session, Depends(get_db)],
) -> BackendIntrospectionResponse:
    _require_policy(db, principal.consumer)
    if settings.paid_access_clock_skew_seconds is None:
        raise HTTPException(503, detail={"code": "backend_session_unavailable"})
    try:
        result = introspect_token(
            db,
            token=payload.access_token,
            tenant_id=principal.tenant_id,
            region=principal.region,
            clock_skew_seconds=settings.paid_access_clock_skew_seconds,
            consumer_id=principal.consumer.consumer_id,
        )
        return BackendIntrospectionResponse(
            consumer_id=principal.consumer.consumer_id,
            consumer_policy_revision=principal.consumer.consumer_policy_revision,
            tenant_id=result.tenant_id,
            region=result.region,
            user_id=result.user_id,
            valid_until=result.expires_at,
        )
    except InvalidDelegationError as error:
        raise _refusal(error) from None
    except DelegationUnavailableError:
        raise HTTPException(503, detail={"code": "backend_session_unavailable"}) from None
