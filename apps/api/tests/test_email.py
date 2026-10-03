from __future__ import annotations

from string import Formatter
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

import app.core.email as email_sender
import app.core.email_verification_email as email_verification_email
import app.core.password_reset_email as password_reset_email
from app.generated.locales import SUPPORTED_ROUTE_LOCALES, RouteLocale


class FakeSmtp:
    def __init__(self) -> None:
        self.tls_context = None
        self.sent = False

    def __enter__(self) -> "FakeSmtp":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def starttls(self, *, context: object) -> None:
        self.tls_context = context

    def login(self, _username: str, _password: str) -> None:
        return None

    def send_message(self, _message: object) -> None:
        self.sent = True


def test_send_text_email_uses_verifying_tls_context(monkeypatch) -> None:
    smtp = FakeSmtp()
    tls_context = object()
    monkeypatch.setattr(
        email_sender,
        "settings",
        SimpleNamespace(
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_from_email="support@example.com",
            smtp_use_tls=True,
            smtp_username="",
            smtp_password="",
        ),
    )
    monkeypatch.setattr(
        email_sender.smtplib,
        "SMTP",
        lambda _host, _port, timeout: smtp,
    )
    monkeypatch.setattr(
        email_sender.ssl,
        "create_default_context",
        lambda: tls_context,
    )

    assert email_sender.send_text_email(
        to_email="user@example.com",
        subject="Reset",
        body="Reset link",
    )
    assert smtp.tls_context is tls_context
    assert smtp.sent


@pytest.mark.parametrize("route_locale", SUPPORTED_ROUTE_LOCALES)
def test_password_reset_url_keeps_token_in_fragment_only(
    monkeypatch: pytest.MonkeyPatch,
    route_locale: RouteLocale,
) -> None:
    monkeypatch.setattr(
        password_reset_email,
        "settings",
        SimpleNamespace(app_public_base_url="https://payments.example.com/"),
    )
    token = "secret-token?&/value"

    reset_url = password_reset_email.build_password_reset_url(token, route_locale)
    parsed_url = urlsplit(reset_url)

    assert parsed_url.path == f"/{route_locale}/reset-password"
    assert parsed_url.query == ""
    assert parse_qs(parsed_url.fragment) == {"token": [token]}
    assert token not in parsed_url.path
    assert token not in parsed_url.query


def test_password_reset_email_templates_cover_supported_locales_exactly() -> None:
    assert set(password_reset_email.PASSWORD_RESET_EMAIL_TEMPLATES) == set(SUPPORTED_ROUTE_LOCALES)

    for template in password_reset_email.PASSWORD_RESET_EMAIL_TEMPLATES.values():
        field_names = {field_name for _, field_name, _, _ in Formatter().parse(template.body) if field_name is not None}
        assert field_names == {"reset_url", "ttl_minutes"}


@pytest.mark.parametrize("route_locale", SUPPORTED_ROUTE_LOCALES)
def test_password_reset_email_renders_every_supported_locale(
    route_locale: RouteLocale,
) -> None:
    reset_url = f"https://payments.example.com/{route_locale}/reset-password#token=secret"
    ttl_minutes = 37

    content = password_reset_email.render_password_reset_email(
        route_locale=route_locale,
        reset_url=reset_url,
        ttl_minutes=ttl_minutes,
    )

    assert content.subject.strip()
    assert content.body.strip()
    assert reset_url in content.body
    assert str(ttl_minutes) in content.body


def test_password_reset_email_uses_authored_brazilian_portuguese_template() -> None:
    expected_subject = "Redefinição de senha do AnytoolAI"
    expected_body_template = "\n".join(
        [
            "Olá!",
            "",
            "Para alterar sua senha do AnytoolAI, acesse este link:",
            "{reset_url}",
            "",
            "Se você não solicitou a redefinição da senha, basta ignorar este e-mail.",
            "O link é válido por {ttl_minutes} minutos.",
        ]
    )
    reset_url = "https://payments.example.com/pt/reset-password#token=secret"

    template = password_reset_email.PASSWORD_RESET_EMAIL_TEMPLATES["pt"]
    content = password_reset_email.render_password_reset_email(
        route_locale="pt",
        reset_url=reset_url,
        ttl_minutes=30,
    )

    assert template.subject == expected_subject
    assert template.body == expected_body_template
    assert content.subject == expected_subject
    assert content.body == expected_body_template.format(
        reset_url=reset_url,
        ttl_minutes=30,
    )


def test_send_password_reset_email_delegates_rendered_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    send_text_email = Mock(return_value=True)
    monkeypatch.setattr(password_reset_email, "send_text_email", send_text_email)
    reset_url = "https://payments.example.com/fr/reset-password#token=secret"
    expected_content = password_reset_email.render_password_reset_email(
        route_locale="fr",
        reset_url=reset_url,
        ttl_minutes=30,
    )

    sent = password_reset_email.send_password_reset_email(
        "user@example.com",
        reset_url,
        "fr",
        30,
    )

    assert sent is True
    send_text_email.assert_called_once_with(
        to_email="user@example.com",
        subject=expected_content.subject,
        body=expected_content.body,
    )


@pytest.mark.parametrize("route_locale", SUPPORTED_ROUTE_LOCALES)
def test_email_verification_url_keeps_token_in_fragment_only(
    monkeypatch: pytest.MonkeyPatch,
    route_locale: RouteLocale,
) -> None:
    monkeypatch.setattr(
        email_verification_email,
        "settings",
        SimpleNamespace(app_public_base_url="https://payments.example.com/"),
    )
    token = "verification-secret?&/value"

    verification_url = email_verification_email.build_email_verification_url(token, route_locale)
    parsed_url = urlsplit(verification_url)

    assert parsed_url.path == f"/{route_locale}/verify-email"
    assert parsed_url.query == ""
    assert parse_qs(parsed_url.fragment) == {"token": [token]}
    assert token not in parsed_url.path
    assert token not in parsed_url.query


def test_email_verification_templates_cover_supported_locales_exactly() -> None:
    assert set(email_verification_email.EMAIL_VERIFICATION_TEMPLATES) == set(SUPPORTED_ROUTE_LOCALES)

    for template in email_verification_email.EMAIL_VERIFICATION_TEMPLATES.values():
        field_names = {field_name for _, field_name, _, _ in Formatter().parse(template.body) if field_name is not None}
        assert field_names == {"verification_url", "ttl_hours"}


@pytest.mark.parametrize("route_locale", SUPPORTED_ROUTE_LOCALES)
def test_email_verification_email_renders_every_supported_locale(route_locale: RouteLocale) -> None:
    verification_url = f"https://payments.example.com/{route_locale}/verify-email#token=secret"

    content = email_verification_email.render_email_verification_email(
        route_locale=route_locale,
        verification_url=verification_url,
        ttl_hours=24,
    )

    assert content.subject.strip()
    assert content.body.strip()
    assert verification_url in content.body
    assert "24" in content.body


def test_email_verification_uses_authored_brazilian_portuguese_template() -> None:
    expected_subject = "Verifique seu e-mail do AnytoolAI"
    expected_body_template = "\n".join(
        [
            "Olá!",
            "",
            "Para verificar seu endereço de e-mail do AnytoolAI, acesse este link:",
            "{verification_url}",
            "",
            "Se você não criou esta conta, basta ignorar este e-mail.",
            "O link é válido por {ttl_hours} horas.",
        ]
    )
    verification_url = "https://payments.example.com/pt/verify-email#token=secret"

    template = email_verification_email.EMAIL_VERIFICATION_TEMPLATES["pt"]
    content = email_verification_email.render_email_verification_email(
        route_locale="pt",
        verification_url=verification_url,
        ttl_hours=24,
    )

    assert template.subject == expected_subject
    assert template.body == expected_body_template
    assert content.subject == expected_subject
    assert content.body == expected_body_template.format(verification_url=verification_url, ttl_hours=24)


def test_send_email_verification_email_delegates_rendered_text(monkeypatch: pytest.MonkeyPatch) -> None:
    send_text_email = Mock(return_value=True)
    monkeypatch.setattr(email_verification_email, "send_text_email", send_text_email)
    verification_url = "https://payments.example.com/fr/verify-email#token=secret"
    expected_content = email_verification_email.render_email_verification_email(
        route_locale="fr",
        verification_url=verification_url,
        ttl_hours=24,
    )

    sent = email_verification_email.send_email_verification_email(
        "user@example.com",
        verification_url,
        "fr",
        24,
    )

    assert sent is True
    send_text_email.assert_called_once_with(
        to_email="user@example.com",
        subject=expected_content.subject,
        body=expected_content.body,
    )
