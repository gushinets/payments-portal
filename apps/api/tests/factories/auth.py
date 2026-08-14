from __future__ import annotations

from typing import Any

from app.domains.identity.router import LoginRequest, RegisterRequest


class RegisterRequestFactory:
    @classmethod
    def payload(cls, **overrides: Any) -> dict[str, Any]:
        payload = {
            "email": "user@example.com",
            "password": "very-secret-password",
            "personal_consent": True,
            "offer_consent": True,
        }
        payload.update(overrides)
        return payload

    @classmethod
    def build(cls, **overrides: Any) -> RegisterRequest:
        return RegisterRequest(**cls.payload(**overrides))


class LoginRequestFactory:
    @classmethod
    def payload(cls, **overrides: Any) -> dict[str, Any]:
        payload = {
            "email": "user@example.com",
            "password": "very-secret-password",
        }
        payload.update(overrides)
        return payload

    @classmethod
    def build(cls, **overrides: Any) -> LoginRequest:
        return LoginRequest(**cls.payload(**overrides))
