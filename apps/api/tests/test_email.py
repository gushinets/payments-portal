from __future__ import annotations

from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

import app.core.email as email_sender
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
