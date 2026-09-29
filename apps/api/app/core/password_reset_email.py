from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping
from urllib.parse import urlencode

from app.core.email import send_text_email
from app.core.settings import settings
from app.generated.locales import RouteLocale


@dataclass(frozen=True)
class PasswordResetEmailTemplate:
    subject: str
    body: str


@dataclass(frozen=True)
class PasswordResetEmailContent:
    subject: str
    body: str


PASSWORD_RESET_EMAIL_TEMPLATES: Final[Mapping[RouteLocale, PasswordResetEmailTemplate]] = MappingProxyType(
    {
        "en": PasswordResetEmailTemplate(
            subject="Reset your AnytoolAI password",
            body=(
                "Hello!\n\n"
                "To change your AnytoolAI password, open this link:\n"
                "{reset_url}\n\n"
                "If you did not request a password reset, simply ignore this email.\n"
                "The link is valid for {ttl_minutes} minutes."
            ),
        ),
        "fr": PasswordResetEmailTemplate(
            subject="Réinitialisation du mot de passe AnytoolAI",
            body=(
                "Bonjour !\n\n"
                "Pour modifier votre mot de passe AnytoolAI, ouvrez ce lien :\n"
                "{reset_url}\n\n"
                "Si vous n’avez pas demandé la réinitialisation de votre mot de passe, "
                "ignorez simplement cet e-mail.\n"
                "Ce lien est valide pendant {ttl_minutes} minutes."
            ),
        ),
        "it": PasswordResetEmailTemplate(
            subject="Reimpostazione della password AnytoolAI",
            body=(
                "Salve!\n\n"
                "Per modificare la password di AnytoolAI, apri questo link:\n"
                "{reset_url}\n\n"
                "Se non hai richiesto la reimpostazione della password, ignora questa email.\n"
                "Il link è valido per {ttl_minutes} minuti."
            ),
        ),
        "de": PasswordResetEmailTemplate(
            subject="AnytoolAI-Passwort zurücksetzen",
            body=(
                "Hallo!\n\n"
                "Um dein AnytoolAI-Passwort zu ändern, öffne diesen Link:\n"
                "{reset_url}\n\n"
                "Wenn du keine Passwortzurücksetzung angefordert hast, "
                "ignoriere diese E-Mail einfach.\n"
                "Der Link ist {ttl_minutes} Minuten lang gültig."
            ),
        ),
        "es": PasswordResetEmailTemplate(
            subject="Restablecimiento de la contraseña de AnytoolAI",
            body=(
                "¡Hola!\n\n"
                "Para cambiar tu contraseña de AnytoolAI, abre este enlace:\n"
                "{reset_url}\n\n"
                "Si no solicitaste restablecer tu contraseña, simplemente ignora este correo.\n"
                "El enlace es válido durante {ttl_minutes} minutos."
            ),
        ),
        "ru": PasswordResetEmailTemplate(
            subject="Восстановление пароля AnytoolAI",
            body=(
                "Здравствуйте!\n\n"
                "Чтобы сменить пароль AnytoolAI, откройте ссылку:\n"
                "{reset_url}\n\n"
                "Если вы не запрашивали восстановление пароля, "
                "просто проигнорируйте это письмо.\n"
                "Ссылка действует {ttl_minutes} минут."
            ),
        ),
        "pt": PasswordResetEmailTemplate(
            subject="Redefinição de senha do AnytoolAI",
            body=(
                "Olá!\n\n"
                "Para alterar sua senha do AnytoolAI, acesse este link:\n"
                "{reset_url}\n\n"
                "Se você não solicitou a redefinição da senha, basta ignorar este e-mail.\n"
                "O link é válido por {ttl_minutes} minutos."
            ),
        ),
    }
)


def build_password_reset_url(token: str, route_locale: RouteLocale) -> str:
    base_url = settings.app_public_base_url.rstrip("/")
    fragment = urlencode({"token": token})
    return f"{base_url}/{route_locale}/reset-password#{fragment}"


def render_password_reset_email(
    *,
    route_locale: RouteLocale,
    reset_url: str,
    ttl_minutes: int,
) -> PasswordResetEmailContent:
    template = PASSWORD_RESET_EMAIL_TEMPLATES[route_locale]
    return PasswordResetEmailContent(
        subject=template.subject,
        body=template.body.format(
            reset_url=reset_url,
            ttl_minutes=ttl_minutes,
        ),
    )


def send_password_reset_email(
    email: str,
    reset_url: str,
    route_locale: RouteLocale,
    ttl_minutes: int,
) -> bool:
    content = render_password_reset_email(
        route_locale=route_locale,
        reset_url=reset_url,
        ttl_minutes=ttl_minutes,
    )
    return send_text_email(
        to_email=email,
        subject=content.subject,
        body=content.body,
    )
