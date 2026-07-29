from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import record_password_reset_email
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
PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX = 5
PASSWORD_RESET_IP_RATE_LIMIT_MAX = 20
logger = logging.getLogger("payment_portal.identity.password_reset")


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


def password_reset_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def password_reset_rate_limit_keys(
    *, tenant_id: str, region: str, email_normalized: str, request: Request
) -> tuple[str, str]:
    ip = password_reset_client_ip(request)
    return (
        f"account:{tenant_id}:{region}:{email_normalized}",
        f"ip:{tenant_id}:{region}:{ip}",
    )


def make_password_reset_decoy_email_normalized(
    *, tenant_id: str, region: str, email_normalized: str
) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{region}:{email_normalized}".encode("utf-8")).hexdigest()
    return f"password-reset-decoy:{digest}"


def enforce_password_reset_rate_limit(*, db: Session, key: str, limit: int, now: datetime) -> None:
    expires_at = now + timedelta(minutes=PASSWORD_RESET_RATE_LIMIT_WINDOW_MINUTES)
    attempts = db.execute(
        text(
            """
            INSERT INTO password_reset_rate_limits (
                rate_limit_key,
                count,
                window_start,
                expires_at,
                created_at,
                updated_at
            )
            VALUES (:key, 1, :now, :expires_at, :now, :now)
            ON CONFLICT(rate_limit_key) DO UPDATE SET
                count = CASE
                    WHEN password_reset_rate_limits.expires_at <= :now THEN 1
                    ELSE password_reset_rate_limits.count + 1
                END,
                window_start = CASE
                    WHEN password_reset_rate_limits.expires_at <= :now THEN :now
                    ELSE password_reset_rate_limits.window_start
                END,
                expires_at = CASE
                    WHEN password_reset_rate_limits.expires_at <= :now THEN :expires_at
                    ELSE password_reset_rate_limits.expires_at
                END,
                updated_at = :now
            RETURNING count
            """
        ),
        {"key": key, "now": now, "expires_at": expires_at},
    ).scalar_one()
    if attempts > limit:
        raise HTTPException(status_code=429, detail="password_reset_rate_limited")


def prune_expired_password_reset_rate_limits(*, db: Session, now: datetime) -> None:
    db.execute(
        text("DELETE FROM password_reset_rate_limits WHERE expires_at <= :now"),
        {"now": now},
    )


def send_password_reset_email_safely(email: str, reset_url: str) -> None:
    try:
        sent = send_password_reset_email(email, reset_url)
    except Exception as error:
        record_password_reset_email("failed")
        logger.warning(
            "password_reset_email_delivery_failed",
            extra={
                "structured": {
                    "outcome": "failed",
                    "reason": error.__class__.__name__,
                }
            },
        )
        return

    outcome = "sent" if sent else "disabled"
    record_password_reset_email(outcome)
    if not sent:
        logger.warning(
            "password_reset_email_delivery_disabled",
            extra={"structured": {"outcome": outcome, "reason": "smtp_not_configured"}},
        )


def skip_password_reset_email(email: str, reset_url: str) -> None:
    return None


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
    account_rate_limit_key, ip_rate_limit_key = password_reset_rate_limit_keys(
        tenant_id=tenant_id,
        region=region,
        email_normalized=normalized_email,
        request=request,
    )
    try:
        prune_expired_password_reset_rate_limits(db=db, now=now)
        enforce_password_reset_rate_limit(
            db=db,
            key=ip_rate_limit_key,
            limit=PASSWORD_RESET_IP_RATE_LIMIT_MAX,
            now=now,
        )
        enforce_password_reset_rate_limit(
            db=db,
            key=account_rate_limit_key,
            limit=PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX,
            now=now,
        )
    except HTTPException:
        db.rollback()
        raise
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

    reset_token = MagicLinkToken(
        tenant_id=user.tenant_id if user is not None else tenant_id,
        region=user.region if user is not None else region,
        email_normalized=(
            user.email_normalized
            if user is not None
            else make_password_reset_decoy_email_normalized(
                tenant_id=tenant_id,
                region=region,
                email_normalized=normalized_email,
            )
        ),
        token_hash=token_hash,
        purpose=PASSWORD_RESET_PURPOSE,
        expires_at=expires_at,
        ip=password_reset_client_ip(request),
        user_agent=request.headers.get("user-agent"),
    )
    db.add(reset_token)

    db.commit()

    background_tasks.add_task(
        send_password_reset_email_safely if user is not None else skip_password_reset_email,
        user.email if user is not None else normalized_email,
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
        db.query(MagicLinkToken)
        .filter(
            MagicLinkToken.tenant_id == user.tenant_id,
            MagicLinkToken.region == user.region,
            MagicLinkToken.email_normalized == user.email_normalized,
            MagicLinkToken.purpose == PASSWORD_RESET_PURPOSE,
            MagicLinkToken.used_at.is_(None),
        )
        .update({"used_at": now}, synchronize_session=False)
    )

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
