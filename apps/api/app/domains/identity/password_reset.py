from __future__ import annotations

import re
from typing import Annotated, Literal

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
from app.generated.locales import (
    DEFAULT_ROUTE_LOCALE,
    LANGUAGE_TAG_BY_ROUTE_LOCALE,
    RouteLocale,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


_ROUTE_LOCALE_BY_LANGUAGE_TAG: dict[str, RouteLocale] = {
    language_tag.casefold(): route_locale for route_locale, language_tag in LANGUAGE_TAG_BY_ROUTE_LOCALE.items()
}
if len(_ROUTE_LOCALE_BY_LANGUAGE_TAG) != len(LANGUAGE_TAG_BY_ROUTE_LOCALE):
    raise RuntimeError("Generated locale language tags must be unique after case-folding")
_ACCEPT_LANGUAGE_QVALUE = re.compile(r"(?:0(?:\.[0-9]{0,3})?|1(?:\.0{0,3})?)\Z")


def _normalize_request_language(value: str | None) -> RouteLocale:
    if not value:
        return DEFAULT_ROUTE_LOCALE

    best_route_locale: RouteLocale | None = None
    best_quality = 0
    for raw_item in value.split(","):
        item = raw_item.strip()
        if not item:
            continue

        segments = [segment.strip() for segment in item.split(";")]
        if len(segments) not in (1, 2):
            continue

        route_locale = _ROUTE_LOCALE_BY_LANGUAGE_TAG.get(segments[0].casefold())
        if route_locale is None:
            continue

        quality = 1000
        if len(segments) == 2:
            parameter_name, separator, qvalue = segments[1].partition("=")
            if (
                separator != "="
                or parameter_name.casefold() != "q"
                or _ACCEPT_LANGUAGE_QVALUE.fullmatch(qvalue) is None
            ):
                continue
            if qvalue.startswith("1"):
                quality = 1000
            else:
                _, _, fraction = qvalue.partition(".")
                quality = int(fraction.ljust(3, "0")) if fraction else 0

        if quality > best_quality:
            best_route_locale = route_locale
            best_quality = quality

    return best_route_locale or DEFAULT_ROUTE_LOCALE


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=8, max_length=128)


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
    route_locale = _normalize_request_language(request.headers.get("accept-language"))
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
