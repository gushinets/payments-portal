from __future__ import annotations

import hashlib
import secrets
from collections import defaultdict
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.password_reset_email import build_password_reset_url, send_password_reset_email
from app.domains.identity.passwords import hash_password
from app.domains.identity.session import (
    DEFAULT_REGION,
    DEFAULT_TENANT_ID,
    utc_now,
)
from app.models import AuthSession, MagicLinkToken, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

PASSWORD_RESET_TTL_MINUTES = 30
PASSWORD_RESET_PURPOSE = "password_reset"
PASSWORD_RESET_RATE_LIMIT_WINDOW_MINUTES = 15
PASSWORD_RESET_RATE_LIMIT_MAX = 5
password_reset_attempts: dict[str, list[datetime]] = defaultdict(list)


class PasswordResetRequest(BaseModel):
    tenant_id: str = DEFAULT_TENANT_ID
    region: str = DEFAULT_REGION
    email: EmailStr


class PasswordResetConfirmRequest(BaseModel):
    token: str = Field(min_length=32, max_length=256)
    password: str = Field(min_length=8, max_length=128)


def make_password_reset_token() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = utc_now() + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES)
    return token, token_hash, expires_at


def normalize_tenant_id(value: str) -> str:
    return value.strip().lower()


def normalize_region(value: str) -> str:
    return value.strip().lower()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def password_reset_rate_limit_key(
    *, tenant_id: str, region: str, email_normalized: str, request: Request
) -> str:
    ip = request.client.host if request.client else "unknown"
    return f"{tenant_id}:{region}:{email_normalized}:{ip}"


def enforce_password_reset_rate_limit(key: str, now: datetime) -> None:
    window_start = now - timedelta(minutes=PASSWORD_RESET_RATE_LIMIT_WINDOW_MINUTES)
    recent = [attempt for attempt in password_reset_attempts[key] if attempt > window_start]
    if len(recent) >= PASSWORD_RESET_RATE_LIMIT_MAX:
        password_reset_attempts[key] = recent
        raise HTTPException(status_code=429, detail="password_reset_rate_limited")
    recent.append(now)
    password_reset_attempts[key] = recent


def send_password_reset_email_safely(email: str, reset_url: str) -> None:
    try:
        send_password_reset_email(email, reset_url)
    except Exception:
        pass


@router.post("/password-reset/request")
def request_password_reset(
    payload: PasswordResetRequest,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    tenant_id = normalize_tenant_id(payload.tenant_id)
    region = normalize_region(payload.region)
    normalized_email = normalize_email(str(payload.email))
    now = utc_now()
    enforce_password_reset_rate_limit(
        password_reset_rate_limit_key(
            tenant_id=tenant_id,
            region=region,
            email_normalized=normalized_email,
            request=request,
        ),
        now,
    )
    token, token_hash, expires_at = make_password_reset_token()
    user = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.region == region,
            User.email_normalized == normalized_email,
            User.status == "active",
        )
        .first()
    )

    if user is not None:
        reset_token = MagicLinkToken(
            tenant_id=user.tenant_id,
            region=user.region,
            email_normalized=user.email_normalized,
            token_hash=token_hash,
            purpose=PASSWORD_RESET_PURPOSE,
            expires_at=expires_at,
            ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
        )
        db.add(reset_token)
        db.commit()
        background_tasks.add_task(
            send_password_reset_email_safely,
            user.email,
            build_password_reset_url(token),
        )

    return {"status": "accepted"}


@router.post("/password-reset/confirm")
def confirm_password_reset(
    payload: PasswordResetConfirmRequest,
    db: Session = Depends(get_db),
):
    now = utc_now()
    token_hash = hashlib.sha256(payload.token.encode("utf-8")).hexdigest()
    claimed = (
        db.query(MagicLinkToken)
        .filter(
            MagicLinkToken.token_hash == token_hash,
            MagicLinkToken.purpose == PASSWORD_RESET_PURPOSE,
            MagicLinkToken.used_at.is_(None),
            MagicLinkToken.expires_at > now,
        )
        .update({"used_at": now}, synchronize_session=False)
    )
    if claimed != 1:
        db.rollback()
        raise HTTPException(status_code=400, detail="invalid_or_expired_reset_token")

    reset_token = (
        db.query(MagicLinkToken)
        .filter(
            MagicLinkToken.token_hash == token_hash,
            MagicLinkToken.purpose == PASSWORD_RESET_PURPOSE,
        )
        .first()
    )
    if reset_token is None:
        db.rollback()
        raise HTTPException(status_code=400, detail="invalid_or_expired_reset_token")

    user = (
        db.query(User)
        .filter(
            User.tenant_id == reset_token.tenant_id,
            User.region == reset_token.region,
            User.email_normalized == reset_token.email_normalized,
            User.status == "active",
        )
        .first()
    )
    if user is None:
        db.rollback()
        raise HTTPException(status_code=400, detail="invalid_or_expired_reset_token")

    user.password_hash = hash_password(payload.password)
    db.add(user)

    (
        db.query(AuthSession)
        .filter(
            AuthSession.tenant_id == user.tenant_id,
            AuthSession.region == user.region,
            AuthSession.user_id == user.id,
            AuthSession.revoked_at.is_(None),
        )
        .update({"revoked_at": now}, synchronize_session=False)
    )
    db.commit()

    return {"status": "password_reset"}
