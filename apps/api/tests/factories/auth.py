from __future__ import annotations

from typing import Any

from polyfactory.factories.pydantic_factory import ModelFactory

from app.domains.identity.router import LoginRequest, RegisterRequest


class RegisterRequestFactory(ModelFactory[RegisterRequest]):
    __model__ = RegisterRequest

    email = "user@example.com"
    password = "very-secret-password"
    personal_consent = True
    offer_consent = True

    @classmethod
    def payload(cls, **overrides: Any) -> dict[str, Any]:
        return cls.build(**overrides).model_dump(mode="json")


class LoginRequestFactory(ModelFactory[LoginRequest]):
    __model__ = LoginRequest

    email = "user@example.com"
    password = "very-secret-password"

    @classmethod
    def payload(cls, **overrides: Any) -> dict[str, Any]:
        return cls.build(**overrides).model_dump(mode="json")
