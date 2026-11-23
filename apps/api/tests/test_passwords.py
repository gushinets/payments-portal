from __future__ import annotations

from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.database import SessionLocal
from app.domains.identity.passwords import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PASSWORD_SPECIAL_CHARACTERS,
    hash_password,
    password_meets_policy,
)
from app.domains.identity.services import password_reset as password_reset_service
from app.models import User
from apps.api.tests.support.api import client, register_test_user, reset_api_database


GENERATED_PASSWORDS = (
    pytest.param("a9V4qR7mX2sL", id="alphanumeric"),
    pytest.param("a9V4qR7mX2sL~", id="tilde-only-punctuation"),
    pytest.param(" α\u0301βγδεζηθικ ", id="decomposed-unicode-with-spaces"),
)


def setup_function() -> None:
    reset_api_database()


@pytest.mark.parametrize(
    ("password", "expected"),
    [
        ("Aa1!" + "a" * 7, False),
        ("Aa1!" + "a" * 8, True),
        ("Aa1!" + "a" * 124, True),
        ("Aa1!" + "a" * 125, False),
    ],
)
def test_password_policy_boundaries(password: str, expected: bool) -> None:
    assert password_meets_policy(password) is expected


def test_password_policy_constants_define_business_bounds() -> None:
    assert (PASSWORD_MIN_LENGTH, PASSWORD_MAX_LENGTH) == (12, 128)
    assert PASSWORD_SPECIAL_CHARACTERS == "!@#$%^&*()-_=+[]{}:,.?"


@pytest.mark.parametrize(
    "password",
    [
        "aa1!" + "a" * 8,
        "AA1!" + "A" * 8,
        "Aaa!" + "a" * 8,
        "Aa11" + "a" * 8,
    ],
)
def test_password_policy_requires_each_character_class(password: str) -> None:
    assert password_meets_policy(password) is False


@pytest.mark.parametrize("password", GENERATED_PASSWORDS)
def test_password_policy_accepts_generated_password(password: str) -> None:
    assert password_meets_policy(password) is True


@pytest.mark.parametrize("password", GENERATED_PASSWORDS)
def test_registration_accepts_generated_password(password: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "email": "generated-password@example.com",
            "password": password,
            "personal_consent": True,
            "offer_consent": True,
        },
    )

    assert response.status_code == 200, response.text


@pytest.mark.parametrize("password", GENERATED_PASSWORDS)
def test_password_reset_accepts_generated_password(password: str, monkeypatch: pytest.MonkeyPatch) -> None:
    email = "generated-password-reset@example.com"
    register_test_user(email=email)
    send_email = Mock(return_value=True)
    monkeypatch.setattr(password_reset_service, "send_password_reset_email", send_email)

    reset_request = client.post("/api/auth/password-reset/request", json={"email": email})
    assert reset_request.status_code == 200, reset_request.text
    assert send_email.call_count == 1
    reset_url = send_email.call_args.args[1]
    token = parse_qs(urlsplit(reset_url).fragment)["token"][0]

    response = client.post("/api/auth/password-reset/confirm", json={"token": token, "password": password})

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "password_reset"}


@pytest.mark.parametrize(
    "password",
    [
        "Aa1!aaaaaaa",  # 11 characters
        "Aa1!" + "a" * 125,  # 129 characters
        "aa1!" + "a" * 8,  # missing uppercase
        "AA1!" + "A" * 8,  # missing lowercase
        "Aaa!" + "a" * 8,  # missing digit
        "Aa11" + "a" * 8,  # missing special character
    ],
)
@pytest.mark.parametrize("endpoint", ["register", "password-reset/confirm"])
def test_api_returns_password_policy_error_for_invalid_new_password(
    endpoint: str,
    password: str,
) -> None:
    payload = (
        {
            "email": f"invalid-password-{len(password)}-{endpoint.replace('/', '-')}@example.com",
            "password": password,
            "personal_consent": True,
            "offer_consent": True,
        }
        if endpoint == "register"
        else {"token": "t" * 32, "password": password}
    )

    response = client.post(f"/api/auth/{endpoint}", json=payload)

    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "password_policy_not_met"}}


@pytest.mark.parametrize("special", PASSWORD_SPECIAL_CHARACTERS)
def test_every_allowed_special_character_can_qualify(special: str) -> None:
    assert password_meets_policy(f"Aa1{special}" + "a" * 8) is True


@pytest.mark.parametrize(
    "additional_characters",
    [
        "пароль с пробелом",
        "spaces are valid",
        "quotes \" and apostrophes '",
        "semicolons;are;valid",
        "🧰" * 15,
    ],
)
def test_password_policy_accepts_unicode_spaces_quotes_and_punctuation(
    additional_characters: str,
) -> None:
    assert password_meets_policy(f"Aa1!abcdefgh{additional_characters}")


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
