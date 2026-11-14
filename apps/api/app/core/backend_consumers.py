"""Bounded deployment-owned backend identities; no dynamic registration."""

from __future__ import annotations

import hashlib
import json
import re
from enum import StrEnum
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator


class BackendPermission(StrEnum):
    EXCHANGE = "backend-session:exchange"
    INTROSPECT = "backend-session:introspect"
    READ_SNAPSHOT = "access-snapshot:read"
    WRITE_EXHAUSTION = "allowance-exhaustion:write"


class BackendConsumer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    consumer_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    tenant_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    consumer_policy_revision: int = Field(strict=True, ge=1, le=2**53 - 1)
    allowed_products: frozenset[str]
    permissions: frozenset[BackendPermission]
    callback_url: str
    backend_base_url: str
    technical_source_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    backend_to_portal_current_secret: SecretStr = Field(repr=False)
    backend_to_portal_previous_secret: SecretStr | None = Field(default=None, repr=False)
    portal_to_backend_current_secret: SecretStr = Field(repr=False)
    portal_to_backend_previous_secret: SecretStr | None = Field(default=None, repr=False)

    @field_validator("allowed_products")
    @classmethod
    def validate_products(cls, value: frozenset[str]) -> frozenset[str]:
        if any(re.fullmatch(r"[a-z][a-z0-9_]{0,127}", product) is None for product in value):
            raise ValueError("Invalid backend product identifier")
        return value

    @field_validator(
        "backend_to_portal_current_secret",
        "backend_to_portal_previous_secret",
        "portal_to_backend_current_secret",
        "portal_to_backend_previous_secret",
    )
    @classmethod
    def validate_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and re.fullmatch(r"[A-Za-z0-9._~+/-]{32,256}={0,2}", value.get_secret_value()) is None:
            raise ValueError("Backend secrets require 32–256 Bearer-safe characters")
        return value

    @field_validator("callback_url", "backend_base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (
            not url.hostname
            or url.username is not None
            or url.password is not None
            or url.query
            or url.fragment
            or any(char.isspace() or ord(char) < 33 for char in value)
            or url.port == 0
            or (
                url.scheme != "https"
                and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"})
            )
        ):
            raise ValueError("Backend URL requires HTTPS (loopback HTTP in development/test)")
        return value

    @model_validator(mode="after")
    def validate_origins_and_rotation(self) -> BackendConsumer:
        base = urlsplit(self.backend_base_url)
        if base.path not in {"", "/"}:
            raise ValueError("Backend base URL must be an origin")
        callback = urlsplit(self.callback_url)
        if (callback.scheme, callback.netloc) != (base.scheme, base.netloc) or not callback.path.startswith("/"):
            raise ValueError("Callback must belong to the configured backend origin")
        secrets = [
            value.get_secret_value()
            for value in (
                self.backend_to_portal_current_secret,
                self.backend_to_portal_previous_secret,
                self.portal_to_backend_current_secret,
                self.portal_to_backend_previous_secret,
            )
            if value is not None
        ]
        if len(secrets) != len(set(secrets)):
            raise ValueError("Backend directional and rotation secrets must be distinct")
        return self

    @property
    def policy_digest(self) -> str:
        document = {
            "consumer_id": self.consumer_id,
            "tenant_id": self.tenant_id,
            "region": self.region,
            "allowed_products": sorted(self.allowed_products),
            "permissions": sorted(self.permissions),
            "technical_source_id": self.technical_source_id,
        }
        return (
            "sha256:"
            + hashlib.sha256(
                json.dumps(
                    document,
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=True,
                ).encode()
            ).hexdigest()
        )
