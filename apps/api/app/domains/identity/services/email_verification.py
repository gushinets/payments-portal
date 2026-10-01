from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.email_verification_email import (
    build_email_verification_url,
    send_email_verification_email,
)
from app.core.time import utc_now
from app.domains.identity.errors import InvalidOrExpiredVerificationTokenError
from app.generated.locales import RouteLocale
from app.infrastructure.persistence.email_verification import (
    claim_valid_email_verification_token,
    get_email_verification_token,
    get_newest_outstanding_email_verification_token,
    invalidate_outstanding_email_verification_tokens,
)
from app.infrastructure.queries.identity import lock_active_user_by_id_and_scope
from app.models import MagicLinkPurpose, MagicLinkToken, User


EMAIL_VERIFICATION_TTL_HOURS = 24
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS = 60
logger = logging.getLogger("payment_portal.identity.email_verification")


@dataclass(frozen=True)
class EmailVerificationDelivery:
    recipient_email: str
    verification_url: str
    route_locale: RouteLocale


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def make_email_verification_token() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = utc_now() + timedelta(hours=EMAIL_VERIFICATION_TTL_HOURS)
    return token, token_hash, expires_at


def create_email_verification(
    db: Session,
    *,
    user: User,
    route_locale: RouteLocale,
    client_ip: str | None,
    user_agent: str | None,
) -> EmailVerificationDelivery:
    token, token_hash, expires_at = make_email_verification_token()
    db.add(
        MagicLinkToken(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            email_normalized=user.email_normalized,
            token_hash=token_hash,
            purpose=MagicLinkPurpose.EMAIL_VERIFICATION,
            expires_at=expires_at,
            ip=client_ip,
            user_agent=user_agent,
        )
    )
    return EmailVerificationDelivery(
        recipient_email=user.email,
        verification_url=build_email_verification_url(token, route_locale),
        route_locale=route_locale,
    )


def _belongs_to_user(token: MagicLinkToken | None, *, user: User) -> bool:
    return (
        token is not None
        and token.purpose == MagicLinkPurpose.EMAIL_VERIFICATION
        and token.user_id == user.id
        and token.email_normalized == user.email_normalized
        and token.tenant_id == user.tenant_id
        and token.region == user.region
    )


def _is_valid_candidate(token: MagicLinkToken | None, *, user: User, now: datetime) -> bool:
    return (
        _belongs_to_user(token, user=user)
        and token is not None
        and token.used_at is None
        and _as_utc(token.expires_at) > now
    )


def confirm_email_verification(
    db: Session,
    *,
    token: str,
    authenticated_user: User,
) -> None:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    candidate = get_email_verification_token(
        db,
        token_hash=token_hash,
        tenant_id=authenticated_user.tenant_id,
        region=authenticated_user.region,
    )
    if not _belongs_to_user(candidate, user=authenticated_user):
        db.rollback()
        raise InvalidOrExpiredVerificationTokenError()

    user = lock_active_user_by_id_and_scope(
        db,
        user_id=authenticated_user.id,
        tenant_id=authenticated_user.tenant_id,
        region=authenticated_user.region,
    )
    if user is None:
        db.rollback()
        raise InvalidOrExpiredVerificationTokenError()

    now = utc_now()
    candidate = get_email_verification_token(
        db,
        token_hash=token_hash,
        tenant_id=user.tenant_id,
        region=user.region,
    )
    if not _is_valid_candidate(candidate, user=user, now=now):
        db.rollback()
        raise InvalidOrExpiredVerificationTokenError()

    if user.email_verified_at is not None:
        db.rollback()
        return

    claimed = claim_valid_email_verification_token(
        db,
        token_hash=token_hash,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        now=now,
    )
    if claimed != 1:
        db.rollback()
        raise InvalidOrExpiredVerificationTokenError()

    user.email_verified_at = now
    db.add(user)
    invalidate_outstanding_email_verification_tokens(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        now=now,
    )
    db.commit()


def prepare_email_verification_resend(
    db: Session,
    *,
    user_id: uuid.UUID,
    tenant_id: str,
    region: str,
    route_locale: RouteLocale,
    client_ip: str | None,
    user_agent: str | None,
) -> EmailVerificationDelivery | None:
    user = lock_active_user_by_id_and_scope(
        db,
        user_id=user_id,
        tenant_id=tenant_id,
        region=region,
    )
    if user is None:
        db.rollback()
        raise InvalidOrExpiredVerificationTokenError()
    if user.email_verified_at is not None:
        db.rollback()
        return None

    now = utc_now()
    newest = get_newest_outstanding_email_verification_token(
        db,
        tenant_id=tenant_id,
        region=region,
        user_id=user.id,
        now=now,
    )
    if newest is not None and now - _as_utc(newest.created_at) < timedelta(
        seconds=EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS
    ):
        db.rollback()
        return None

    invalidate_outstanding_email_verification_tokens(
        db,
        tenant_id=tenant_id,
        region=region,
        user_id=user.id,
        now=now,
    )
    delivery = create_email_verification(
        db,
        user=user,
        route_locale=route_locale,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    db.commit()
    return delivery


def send_email_verification_email_safely(
    email: str,
    verification_url: str,
    route_locale: RouteLocale,
) -> None:
    try:
        sent = send_email_verification_email(
            email,
            verification_url,
            route_locale,
            EMAIL_VERIFICATION_TTL_HOURS,
        )
    except Exception as error:
        logger.warning(
            "email_verification_delivery_failed",
            extra={"structured": {"outcome": "failed", "reason": error.__class__.__name__}},
        )
        return

    if not sent:
        logger.warning(
            "email_verification_delivery_disabled",
            extra={"structured": {"outcome": "disabled", "reason": "smtp_not_configured"}},
        )
