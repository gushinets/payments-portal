from __future__ import annotations

from urllib.parse import urlencode

from app.core.email import send_text_email
from app.core.settings import settings


def build_password_reset_url(token: str) -> str:
    base_url = settings.app_public_base_url.rstrip("/")
    fragment = urlencode({"token": token})
    return f"{base_url}/ru/reset-password#{fragment}"


def send_password_reset_email(email: str, reset_url: str) -> bool:
    return send_text_email(
        to_email=email,
        subject="Восстановление пароля AnytoolAI",
        body="\n".join(
            [
                "Здравствуйте!",
                "",
                "Чтобы сменить пароль AnytoolAI, откройте ссылку:",
                reset_url,
                "",
                "Если вы не запрашивали восстановление пароля, просто проигнорируйте это письмо.",
                "Ссылка действует 30 минут.",
            ]
        ),
    )
