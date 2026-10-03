from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping
from urllib.parse import urlencode

from app.core.email import send_text_email
from app.core.settings import settings
from app.generated.locales import RouteLocale


@dataclass(frozen=True)
class EmailVerificationTemplate:
    subject: str
    body: str


@dataclass(frozen=True)
class EmailVerificationContent:
    subject: str
    body: str


EMAIL_VERIFICATION_TEMPLATES: Final[Mapping[RouteLocale, EmailVerificationTemplate]] = MappingProxyType(
    {
        "en": EmailVerificationTemplate(
            subject="Verify your AnytoolAI email",
            body=(
                "Hello!\n\n"
                "To verify your email address for AnytoolAI, open this link:\n"
                "{verification_url}\n\n"
                "If you did not create this account, simply ignore this email.\n"
                "The link is valid for {ttl_hours} hours."
            ),
        ),
        "fr": EmailVerificationTemplate(
            subject="Vérifiez votre adresse e-mail AnytoolAI",
            body=(
                "Bonjour !\n\n"
                "Pour vérifier votre adresse e-mail AnytoolAI, ouvrez ce lien :\n"
                "{verification_url}\n\n"
                "Si vous n’avez pas créé ce compte, ignorez simplement cet e-mail.\n"
                "Ce lien est valide pendant {ttl_hours} heures."
            ),
        ),
        "it": EmailVerificationTemplate(
            subject="Verifica l’indirizzo email di AnytoolAI",
            body=(
                "Salve!\n\n"
                "Per verificare il tuo indirizzo email di AnytoolAI, apri questo link:\n"
                "{verification_url}\n\n"
                "Se non hai creato questo account, ignora questa email.\n"
                "Il link è valido per {ttl_hours} ore."
            ),
        ),
        "de": EmailVerificationTemplate(
            subject="Bestätige deine AnytoolAI-E-Mail-Adresse",
            body=(
                "Hallo!\n\n"
                "Um deine E-Mail-Adresse für AnytoolAI zu bestätigen, öffne diesen Link:\n"
                "{verification_url}\n\n"
                "Wenn du dieses Konto nicht erstellt hast, ignoriere diese E-Mail einfach.\n"
                "Der Link ist {ttl_hours} Stunden lang gültig."
            ),
        ),
        "es": EmailVerificationTemplate(
            subject="Verifica tu correo electrónico de AnytoolAI",
            body=(
                "¡Hola!\n\n"
                "Para verificar tu correo electrónico de AnytoolAI, abre este enlace:\n"
                "{verification_url}\n\n"
                "Si no creaste esta cuenta, simplemente ignora este correo.\n"
                "El enlace es válido durante {ttl_hours} horas."
            ),
        ),
        "ru": EmailVerificationTemplate(
            subject="Подтвердите электронную почту AnytoolAI",
            body=(
                "Здравствуйте!\n\n"
                "Чтобы подтвердить адрес электронной почты AnytoolAI, откройте ссылку:\n"
                "{verification_url}\n\n"
                "Если вы не создавали эту учетную запись, просто проигнорируйте письмо.\n"
                "Срок действия ссылки: {ttl_hours} ч."
            ),
        ),
        "pt": EmailVerificationTemplate(
            subject="Verifique seu e-mail do AnytoolAI",
            body=(
                "Olá!\n\n"
                "Para verificar seu endereço de e-mail do AnytoolAI, acesse este link:\n"
                "{verification_url}\n\n"
                "Se você não criou esta conta, basta ignorar este e-mail.\n"
                "O link é válido por {ttl_hours} horas."
            ),
        ),
    }
)


def build_email_verification_url(token: str, route_locale: RouteLocale) -> str:
    base_url = settings.app_public_base_url.rstrip("/")
    fragment = urlencode({"token": token})
    return f"{base_url}/{route_locale}/verify-email#{fragment}"


def render_email_verification_email(
    *,
    route_locale: RouteLocale,
    verification_url: str,
    ttl_hours: int,
) -> EmailVerificationContent:
    template = EMAIL_VERIFICATION_TEMPLATES[route_locale]
    return EmailVerificationContent(
        subject=template.subject,
        body=template.body.format(
            verification_url=verification_url,
            ttl_hours=ttl_hours,
        ),
    )


def send_email_verification_email(
    email: str,
    verification_url: str,
    route_locale: RouteLocale,
    ttl_hours: int,
) -> bool:
    content = render_email_verification_email(
        route_locale=route_locale,
        verification_url=verification_url,
        ttl_hours=ttl_hours,
    )
    return send_text_email(
        to_email=email,
        subject=content.subject,
        body=content.body,
    )
