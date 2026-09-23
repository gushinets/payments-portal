from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.settings import settings
from app.domains.identity.services.password_reset import (
    confirm_password_reset as confirm_password_reset_use_case,
    prepare_password_reset,
    send_password_reset_email_safely,
    skip_password_reset_email,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=8, max_length=128)


@router.post("/password-reset/request")
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Annotated[Session, Depends(get_db)],
):
    delivery = prepare_password_reset(
        db,
        tenant_id=settings.instance_tenant_id,
        region=settings.instance_region,
        email=str(payload.email),
        client_ip=request.client.host if request.client else "unknown",
        user_agent=request.headers.get("user-agent"),
    )
    background_tasks.add_task(
        send_password_reset_email_safely if delivery.send_email else skip_password_reset_email,
        delivery.recipient_email,
        delivery.reset_url,
    )

    return {"status": "accepted"}


@router.post("/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    db: Annotated[Session, Depends(get_db)],
):
    confirm_password_reset_use_case(
        db,
        token=payload.token,
        password=payload.password,
        tenant_id=settings.instance_tenant_id,
        region=settings.instance_region,
    )
    return {"status": "password_reset"}
