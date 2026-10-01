from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import settings
from app.domains.identity.passwords import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.domains.identity.services.auth import (
    AuthenticationResult,
    login_user,
    logout_session,
    register_user,
)
from app.domains.identity.services.email_verification import (
    confirm_email_verification,
    prepare_email_verification_resend,
    send_email_verification_email_safely,
)
from app.http.dependencies import get_current_session
from app.http.request_locale import normalize_request_language
from app.models import AuthSession, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    personal_consent: bool
    offer_consent: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class SessionUserResponse(BaseModel):
    tenant_id: str
    region: str
    user_id: UUID
    email: EmailStr
    email_verified: bool


class RegisterResponse(BaseModel):
    status: Literal["registered"]
    token: str
    user: SessionUserResponse


class LoginResponse(BaseModel):
    status: Literal["authenticated"]
    token: str
    user: SessionUserResponse


class SessionResponse(BaseModel):
    authenticated: Literal[True]
    user: SessionUserResponse


class LogoutResponse(BaseModel):
    status: Literal["logged_out"]


class EmailVerificationConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class EmailVerificationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EmailVerificationConfirmResponse(BaseModel):
    status: Literal["verified"]


class EmailVerificationRequestResponse(BaseModel):
    status: Literal["accepted"]


def present_user(result: AuthenticationResult) -> SessionUserResponse:
    return SessionUserResponse(
        tenant_id=result.tenant_id,
        region=result.region,
        user_id=str(result.user_id),
        email=result.email,
        email_verified=result.email_verified,
    )


@router.post("/register")
def register(
    payload: RegisterRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> RegisterResponse:
    route_locale = normalize_request_language(request.headers.get("accept-language"))
    result = register_user(
        db,
        tenant_id=settings.instance_tenant_id,
        region=settings.instance_region,
        email=str(payload.email),
        password=payload.password,
        personal_consent=payload.personal_consent,
        offer_consent=payload.offer_consent,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        route_locale=route_locale,
    )
    authentication = result.authentication
    delivery = result.verification_delivery
    background_tasks.add_task(
        send_email_verification_email_safely,
        delivery.recipient_email,
        delivery.verification_url,
        delivery.route_locale,
    )

    return RegisterResponse(
        status="registered",
        token=authentication.token,
        user=present_user(authentication),
    )


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> LoginResponse:
    result = login_user(
        db,
        tenant_id=settings.instance_tenant_id,
        region=settings.instance_region,
        email=str(payload.email),
        password=payload.password,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return LoginResponse(
        status="authenticated",
        token=result.token,
        user=present_user(result),
    )


@router.get("/session")
def get_session(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
) -> SessionResponse:
    user, _ = current
    return SessionResponse(
        authenticated=True,
        user=SessionUserResponse(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            email=user.email,
            email_verified=user.email_verified_at is not None,
        ),
    )


@router.post("/logout")
def logout(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> LogoutResponse:
    _, session = current
    logout_session(db, auth_session=session)
    return LogoutResponse(status="logged_out")


@router.post("/email-verification/confirm")
def confirm_verification(
    payload: EmailVerificationConfirmRequest,
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> EmailVerificationConfirmResponse:
    user, _ = current
    confirm_email_verification(
        db,
        token=payload.token,
        authenticated_user=user,
    )
    return EmailVerificationConfirmResponse(status="verified")


@router.post("/email-verification/request")
def request_email_verification(
    payload: EmailVerificationRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
) -> EmailVerificationRequestResponse:
    user, _ = current
    delivery = prepare_email_verification_resend(
        db,
        user_id=user.id,
        tenant_id=user.tenant_id,
        region=user.region,
        route_locale=normalize_request_language(request.headers.get("accept-language")),
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    if delivery is not None:
        background_tasks.add_task(
            send_email_verification_email_safely,
            delivery.recipient_email,
            delivery.verification_url,
            delivery.route_locale,
        )
    return EmailVerificationRequestResponse(status="accepted")
