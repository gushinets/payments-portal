from __future__ import annotations

import smtplib
from email.message import EmailMessage
from urllib.parse import urlencode

from app.core.settings import settings


def build_password_reset_url(token: str) -> str:
    base_url = settings.app_public_base_url.rstrip("/")
    query = urlencode({"token": token})
    return f"{base_url}/ru/reset-password?{query}"


def send_password_reset_email(email: str, reset_url: str) -> bool:
    if not settings.smtp_host:
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from_email
    message["To"] = email
    message["Subject"] = "Восстановление пароля AnytoolAI"
    message.set_content(
        "\n".join(
            [
                "Здравствуйте!",
                "",
                "Чтобы сменить пароль AnytoolAI, откройте ссылку:",
                reset_url,
                "",
                "Если вы не запрашивали восстановление пароля, просто проигнорируйте это письмо.",
                "Ссылка действует 30 минут.",
            ]
        )
    )

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(message)

    return True
