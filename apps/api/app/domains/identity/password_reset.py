from __future__ import annotations

from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import settings
from app.domains.identity.passwords import PASSWORD_MAX_LENGTH, PASSWORD_MIN_LENGTH
from app.domains.identity.services.password_reset import (
    confirm_password_reset as confirm_password_reset_use_case,
    prepare_password_reset,
    send_password_reset_email_safely,
    skip_password_reset_email,
)
from app.http.request_locale import normalize_request_language

router = APIRouter(prefix="/api/auth", tags=["auth"])


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class PasswordResetRequestResponse(BaseModel):
    status: Literal["accepted"]


class PasswordResetConfirmResponse(BaseModel):
    status: Literal["password_reset"]


@router.post("/password-reset/request")
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
) -> PasswordResetRequestResponse:
    route_locale = normalize_request_language(request.headers.get("accept-language"))
    delivery = prepare_password_reset(
        db,
        tenant_id=settings.instance_tenant_id,
        region=settings.instance_region,
        email=str(payload.email),
        client_ip=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("user-agent"),
        route_locale=route_locale,
    )
    background_tasks.add_task(
        send_password_reset_email_safely if delivery.send_email else skip_password_reset_email,
        delivery.recipient_email,
        delivery.reset_url,
        delivery.route_locale,
    )

    return PasswordResetRequestResponse(status="accepted")


@router.post("/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    db: Annotated[Session, Depends(get_db)],
) -> PasswordResetConfirmResponse:
    confirm_password_reset_use_case(
        db,
        token=payload.token,
        password=payload.password,
        tenant_id=settings.instance_tenant_id,
        region=settings.instance_region,
    )
    return PasswordResetConfirmResponse(status="password_reset")
