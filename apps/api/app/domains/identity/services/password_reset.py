from __future__ import annotations

import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.observability import record_password_reset_email
from app.core.password_reset_email import build_password_reset_url, send_password_reset_email
from app.core.time import utc_now
from app.domains.identity.errors import (
    InvalidOrExpiredResetTokenError,
    PasswordResetError,
    PasswordResetRateLimitedError,
)
from app.domains.identity.passwords import hash_password
from app.infrastructure.persistence.password_reset import (
    claim_valid_password_reset_token,
    increment_password_reset_rate_limit,
    invalidate_outstanding_password_reset_tokens,
    prune_expired_password_reset_rate_limits,
    prune_expired_password_reset_tokens,
    revoke_active_auth_sessions,
)
from app.infrastructure.queries.identity import (
    get_active_user_by_normalized_email,
    get_magic_link_token_by_hash_and_purpose,
)
from app.infrastructure.sentry import FailureCategory, Operation, report_exception
from app.models import MagicLinkPurpose, MagicLinkToken


PASSWORD_RESET_TTL_MINUTES = 30
PASSWORD_RESET_PURPOSE = MagicLinkPurpose.PASSWORD_RESET
PASSWORD_RESET_RATE_LIMIT_WINDOW_MINUTES = 15
PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX = 5
PASSWORD_RESET_IP_RATE_LIMIT_MAX = 20
logger = logging.getLogger("payment_portal.identity.password_reset")


@dataclass(frozen=True)
class PasswordResetDeliveryResult:
    recipient_email: str
    reset_url: str
    send_email: bool


def make_password_reset_token() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = utc_now() + timedelta(minutes=PASSWORD_RESET_TTL_MINUTES)
    return token, token_hash, expires_at


def normalize_email(value: str) -> str:
    return value.strip().lower()


def password_reset_rate_limit_keys(
    *,
    tenant_id: str,
    region: str,
    email_normalized: str,
    client_ip: str,
) -> tuple[str, str]:
    return (
        f"account:{tenant_id}:{region}:{email_normalized}",
        f"ip:{tenant_id}:{region}:{client_ip}",
    )


def make_password_reset_decoy_email_normalized(*, tenant_id: str, region: str, email_normalized: str) -> str:
    digest = hashlib.sha256(f"{tenant_id}:{region}:{email_normalized}".encode("utf-8")).hexdigest()
    return f"password-reset-decoy:{digest}"


def enforce_password_reset_rate_limit(*, db: Session, key: str, limit: int, now: datetime) -> None:
    expires_at = now + timedelta(minutes=PASSWORD_RESET_RATE_LIMIT_WINDOW_MINUTES)
    attempts = increment_password_reset_rate_limit(
        db,
        key=key,
        now=now,
        expires_at=expires_at,
    )
    if attempts > limit:
        raise PasswordResetRateLimitedError()


def prepare_password_reset(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    email: str,
    client_ip: str,
    user_agent: str | None,
) -> PasswordResetDeliveryResult:
    normalized_email = normalize_email(email)
    now = utc_now()
    account_rate_limit_key, ip_rate_limit_key = password_reset_rate_limit_keys(
        tenant_id=tenant_id,
        region=region,
        email_normalized=normalized_email,
        client_ip=client_ip,
    )
    try:
        prune_expired_password_reset_tokens(db=db, now=now)
        prune_expired_password_reset_rate_limits(db=db, now=now)
        db.commit()
        enforce_password_reset_rate_limit(
            db=db,
            key=ip_rate_limit_key,
            limit=PASSWORD_RESET_IP_RATE_LIMIT_MAX,
            now=now,
        )
        db.commit()
        enforce_password_reset_rate_limit(
            db=db,
            key=account_rate_limit_key,
            limit=PASSWORD_RESET_ACCOUNT_RATE_LIMIT_MAX,
            now=now,
        )
        db.commit()
    except PasswordResetError:
        db.rollback()
        raise

    token, token_hash, expires_at = make_password_reset_token()
    user = get_active_user_by_normalized_email(
        db,
        tenant_id=tenant_id,
        region=region,
        email_normalized=normalized_email,
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
        ip=client_ip,
        user_agent=user_agent,
    )
    db.add(reset_token)
    recipient_email = user.email if user is not None else normalized_email
    send_email = user is not None
    db.commit()

    return PasswordResetDeliveryResult(
        recipient_email=recipient_email,
        reset_url=build_password_reset_url(token),
        send_email=send_email,
    )


def confirm_password_reset(
    db: Session,
    *,
    token: str,
    password: str,
) -> None:
    now = utc_now()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    claimed = claim_valid_password_reset_token(
        db,
        token_hash=token_hash,
        now=now,
    )
    if claimed != 1:
        db.rollback()
        raise InvalidOrExpiredResetTokenError()

    reset_token = get_magic_link_token_by_hash_and_purpose(
        db,
        token_hash=token_hash,
        purpose=PASSWORD_RESET_PURPOSE,
    )
    if reset_token is None:
        db.rollback()
        raise InvalidOrExpiredResetTokenError()

    user = get_active_user_by_normalized_email(
        db,
        tenant_id=reset_token.tenant_id,
        region=reset_token.region,
        email_normalized=reset_token.email_normalized,
    )
    if user is None:
        db.rollback()
        raise InvalidOrExpiredResetTokenError()

    user.password_hash = hash_password(password)
    db.add(user)
    invalidate_outstanding_password_reset_tokens(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        email_normalized=user.email_normalized,
        now=now,
    )
    revoke_active_auth_sessions(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        now=now,
    )
    db.commit()


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
        report_exception(
            error,
            operation=Operation.PASSWORD_RESET_EMAIL,
            failure_category=FailureCategory.INTEGRATION_FAILURE,
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
