from __future__ import annotations

from unicodedata import normalize
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
from httpx2 import Response

from app.core.database import SessionLocal
from app.domains.identity.passwords import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    hash_password,
    password_meets_policy,
)
from app.domains.identity.services import password_reset as password_reset_service
from app.models import User
from apps.api.tests.support.api import client, register_test_user, reset_api_database


DECOMPOSED_PASSWORD = " α\u0301βγδεζηθικ "
GENERATED_PASSWORDS = (
    pytest.param("a9V4qR7mX2sL", id="alphanumeric"),
    pytest.param("a9V4qR7mX2sL~", id="tilde-only-punctuation"),
    pytest.param(DECOMPOSED_PASSWORD, id="decomposed-unicode-with-spaces"),
)
ACCEPTED_NEW_PASSWORDS = (
    *GENERATED_PASSWORDS,
    pytest.param("🧰" * 12, id="minimum-length"),
    pytest.param("🧰" * 128, id="maximum-length"),
)


def setup_function() -> None:
    reset_api_database()


def _register_with_password(email: str, password: str) -> Response:
    return client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": password,
            "personal_consent": True,
            "offer_consent": True,
        },
    )


def _reset_with_password(email: str, password: str, monkeypatch: pytest.MonkeyPatch) -> Response:
    register_test_user(email=email)
    send_email = Mock(return_value=True)
    monkeypatch.setattr(password_reset_service, "send_password_reset_email", send_email)

    reset_request = client.post("/api/auth/password-reset/request", json={"email": email})
    assert reset_request.status_code == 200, reset_request.text
    assert send_email.call_count == 1
    reset_url = send_email.call_args.args[1]
    token = parse_qs(urlsplit(reset_url).fragment)["token"][0]

    return client.post("/api/auth/password-reset/confirm", json={"token": token, "password": password})


@pytest.mark.parametrize(("length", "expected"), [(11, False), (12, True), (128, True), (129, False)])
def test_password_policy_counts_unicode_code_points(length: int, expected: bool) -> None:
    assert password_meets_policy("🧰" * length) is expected


def test_password_policy_constants_define_business_bounds() -> None:
    assert (PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH) == (12, 128)


@pytest.mark.parametrize("password", GENERATED_PASSWORDS)
def test_password_policy_accepts_generated_password(password: str) -> None:
    assert password_meets_policy(password) is True


@pytest.mark.parametrize("password", ACCEPTED_NEW_PASSWORDS)
def test_registration_accepts_new_password(password: str) -> None:
    response = _register_with_password("generated-password@example.com", password)

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("password", ACCEPTED_NEW_PASSWORDS)
def test_password_reset_accepts_new_password(password: str, monkeypatch: pytest.MonkeyPatch) -> None:
    response = _reset_with_password("generated-password-reset@example.com", password, monkeypatch)

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "password_reset"}


@pytest.mark.parametrize("length", [11, 129])
def test_registration_returns_password_policy_error_for_out_of_bounds_length(length: int) -> None:
    response = _register_with_password("invalid-password@example.com", "🧰" * length)

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "password_policy_not_met"}}


@pytest.mark.parametrize("flow", ["registration", "reset"])
def test_new_password_preserves_decomposed_unicode_and_spaces(flow: str, monkeypatch: pytest.MonkeyPatch) -> None:
    email = "exact-unicode-password@example.com"
    if flow == "registration":
        response = _register_with_password(email, DECOMPOSED_PASSWORD)
    else:
        response = _reset_with_password(email, DECOMPOSED_PASSWORD, monkeypatch)
    assert response.status_code == 200, response.text

    exact = client.post("/api/auth/login", json={"email": email, "password": DECOMPOSED_PASSWORD})
    assert exact.status_code == 200

    trimmed = client.post("/api/auth/login", json={"email": email, "password": DECOMPOSED_PASSWORD.strip()})
    assert trimmed.status_code == 401

    normalized = client.post(
        "/api/auth/login", json={"email": email, "password": normalize("NFC", DECOMPOSED_PASSWORD)}
    )
    assert normalized.status_code == 401


@pytest.mark.parametrize(
    "password",
    [
        "пароль с пробелом",
        "spaces are valid",
        "quotes \" and apostrophes '",
        "semicolons;are;valid",
        "🧰" * 15,
    ],
)
def test_password_policy_accepts_unicode_spaces_quotes_and_punctuation(
    password: str,
) -> None:
    assert password_meets_policy(password)


def test_injection_looking_password_registers_and_logs_in_without_mutation() -> None:
    password = "Valid1!'; DROP TABLE users;--"
    registration = client.post(
        "/api/auth/register",
        json={
            "email": "literal-password@example.com",
            "password": password,
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    login = client.post(
        "/api/auth/login",
        json={"email": "literal-password@example.com", "password": password},
    )

    assert registration.status_code == 200
    assert login.status_code == 200


def test_login_does_not_apply_new_password_policy_to_existing_credentials() -> None:
    registration = client.post(
        "/api/auth/register",
        json={
            "email": "existing-credential@example.com",
            "password": "Initial-pass1!",
            "personal_consent": True,
            "offer_consent": True,
        },
    )
    assert registration.status_code == 200
    with SessionLocal() as db:
        user = db.query(User).filter_by(email_normalized="existing-credential@example.com").one()
        user.password_hash = hash_password("weak-pass")
        db.commit()

    login = client.post(
        "/api/auth/login",
        json={"email": "existing-credential@example.com", "password": "weak-pass"},
    )

    assert login.status_code == 200
