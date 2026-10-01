from __future__ import annotations

import pytest

from app.core.database import SessionLocal
from app.domains.identity.passwords import (
    PASSWORD_MAX_LENGTH,
    PASSWORD_MIN_LENGTH,
    PASSWORD_SPECIAL_CHARACTERS,
    hash_password,
    password_meets_policy,
)
from app.models import User
from apps.api.tests.support.api import client, reset_api_database


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


def test_password_policy_constants_define_transport_bounds() -> None:
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
