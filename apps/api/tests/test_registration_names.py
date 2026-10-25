"""Optional names do not change verification, legal consent or session wire."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.database import SessionLocal
from app.domains.identity.names import InvalidPersonalNameError, normalize_optional_name
from app.models import DocumentAcceptance, User
from apps.api.tests.support.api import client, reset_api_database


FIELDS = ("user_surname", "user_name", "user_patronymic")


def setup_function() -> None:
    reset_api_database()


@pytest.mark.parametrize(
    "names",
    [
        {},
        {"user_surname": None, "user_name": "", "user_patronymic": "   "},
        {"user_surname": "  Иванова-Петрова  "},
        {"user_name": "Мария Анна"},
        {"user_patronymic": "Ильинична"},
        dict(zip(FIELDS, ("  García-Иванова ", " Анна Мария ", " Ильинична "), strict=True)),
    ],
)
def test_optional_names_persist_only_on_the_registered_user(names: dict[str, str | None]) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "email": "optional-names@example.com",
            "password": "Original-pass1!",
            "personal_consent": True,
            "offer_consent": True,
            **names,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["user"]["email_verified"] is False
    assert not set(FIELDS) & body["user"].keys()
    with SessionLocal() as db:
        user = db.get(User, UUID(body["user"]["user_id"]))
        assert tuple(getattr(user, field) for field in FIELDS) == tuple(
            normalize_optional_name(names.get(field)) for field in FIELDS
        )
        assert len(list(db.scalars(select(DocumentAcceptance).where(DocumentAcceptance.user_id == user.id)))) >= 2
        assert user.email_verified_at is None
    session = client.get("/api/auth/session", headers={"Authorization": "Bearer " + body["token"]})
    assert session.status_code == 200
    assert not set(FIELDS) & session.json()["user"].keys()


@pytest.mark.parametrize("value", ["x" * 257, "Ivan\nPetrov", "\t", "Name\x00", "Name\u202e", 42, ["name"]])
def test_invalid_names_use_safe_machine_error(value: object) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "email": "invalid-name@example.com",
            "password": "Original-pass1!",
            "personal_consent": True,
            "offer_consent": True,
            "user_name": value,
        },
    )
    assert response.status_code == 400
    assert response.json() == {"detail": {"code": "invalid_personal_name"}}
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email_normalized == "invalid-name@example.com")) is None


@pytest.mark.parametrize("consent", ["personal_consent", "offer_consent"])
def test_names_do_not_replace_legal_consent(consent: str) -> None:
    payload = {
        "email": "no-consent@example.com",
        "password": "Original-pass1!",
        "personal_consent": True,
        "offer_consent": True,
        "user_name": "Анна",
    }
    payload[consent] = False
    assert client.post("/api/auth/register", json=payload).status_code == 400


def test_name_normalization_preserves_unicode_and_internal_spacing() -> None:
    assert normalize_optional_name("  Анна  Мария-Éva  ") == "Анна  Мария-Éva"
    assert normalize_optional_name("  ") is None
    with pytest.raises(InvalidPersonalNameError):
        normalize_optional_name("invalid\rname")
