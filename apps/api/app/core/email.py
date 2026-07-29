from __future__ import annotations

import smtplib
import logging
from email.message import EmailMessage

from app.core.settings import settings

logger = logging.getLogger("payment_portal.email")


def send_text_email(*, to_email: str, subject: str, body: str) -> bool:
    if not settings.smtp_host:
        logger.warning(
            "email_delivery_disabled",
            extra={"structured": {"outcome": "disabled", "reason": "missing_smtp_host"}},
        )
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = to_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)

    return True
