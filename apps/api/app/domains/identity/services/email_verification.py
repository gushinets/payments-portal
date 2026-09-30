from __future__ import annotations

import hashlib
import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.core.email_verification_email import (
    build_email_verification_url,
    send_email_verification_email,
)
from app.core.observability import record_email_verification_email
from app.core.time import utc_now
from app.generated.locales import RouteLocale


EMAIL_VERIFICATION_TTL_HOURS = 24
logger = logging.getLogger("payment_portal.identity.email_verification")


@dataclass(frozen=True)
class EmailVerificationDeliveryResult:
    recipient_email: str
    verification_url: str
    send_email: bool
    route_locale: RouteLocale
    user_id: uuid.UUID | None


def make_email_verification_token() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = utc_now() + timedelta(hours=EMAIL_VERIFICATION_TTL_HOURS)
    return token, token_hash, expires_at


def make_email_verification_delivery(
    *,
    recipient_email: str,
    token: str,
    route_locale: RouteLocale,
    user_id: uuid.UUID,
) -> EmailVerificationDeliveryResult:
    return EmailVerificationDeliveryResult(
        recipient_email=recipient_email,
        verification_url=build_email_verification_url(token, route_locale),
        send_email=True,
        route_locale=route_locale,
        user_id=user_id,
    )


def make_skipped_email_verification_delivery(
    *,
    recipient_email: str,
    route_locale: RouteLocale,
) -> EmailVerificationDeliveryResult:
    return EmailVerificationDeliveryResult(
        recipient_email=recipient_email,
        verification_url="",
        send_email=False,
        route_locale=route_locale,
        user_id=None,
    )


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
        record_email_verification_email("failed")
        logger.warning(
            "email_verification_delivery_failed",
            extra={
                "structured": {
                    "outcome": "failed",
                    "reason": error.__class__.__name__,
                }
            },
        )
        return

    outcome = "sent" if sent else "disabled"
    record_email_verification_email(outcome)
    if not sent:
        logger.warning(
            "email_verification_delivery_disabled",
            extra={"structured": {"outcome": outcome, "reason": "smtp_not_configured"}},
        )
