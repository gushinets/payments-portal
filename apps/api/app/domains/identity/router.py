from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import settings
from app.domains.identity.services.auth import (
    AuthenticationResult,
    login_user,
    logout_session,
    register_user,
)
from app.http.dependencies import get_current_session
from app.models import AuthSession, User

router = APIRouter(prefix="/api/auth", tags=["auth"])


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
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


def present_user(result: AuthenticationResult) -> SessionUserResponse:
    return SessionUserResponse(
        tenant_id=result.tenant_id,
        region=result.region,
        user_id=str(result.user_id),
        email=result.email,
    )


@router.post("/register")
def register(
    payload: RegisterRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> RegisterResponse:
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
    )

    return RegisterResponse(
        status="registered",
        token=result.token,
        user=present_user(result),
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
