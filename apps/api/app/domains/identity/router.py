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
    normalize_email as normalize_email,
    register_user,
)
from app.domains.identity.services.account import load_account_session
from app.http_dependencies import get_current_session
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


class SessionResponse(BaseModel):
    authenticated: Literal[True]
    user: SessionUserResponse


def present_user(result: AuthenticationResult) -> dict:
    return {
        "tenant_id": result.tenant_id,
        "region": result.region,
        "user_id": str(result.user_id),
        "email": result.email,
    }


@router.post("/register")
def register(
    payload: RegisterRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
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

    return {
        "status": "registered",
        "token": result.token,
        "user": present_user(result),
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    result = login_user(
        db,
        tenant_id=settings.instance_tenant_id,
        region=settings.instance_region,
        email=str(payload.email),
        password=payload.password,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return {
        "status": "authenticated",
        "token": result.token,
        "user": present_user(result),
    }


@router.get("/session")
def get_session(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
) -> SessionResponse:
    user, _ = current
    result = load_account_session(user=user)

    return SessionResponse(
        authenticated=True,
        user=SessionUserResponse(
            tenant_id=result.tenant_id,
            region=result.region,
            user_id=result.user_id,
            email=result.email,
        ),
    )


@router.post("/logout")
def logout(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
):
    _, session = current
    logout_session(db, auth_session=session)
    return {"status": "logged_out"}
