from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote, urlsplit

from dotenv import load_dotenv
from pydantic import Field, SecretStr, StringConstraints, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.url_validation import (
    validate_production_cors_origin,
    validate_production_public_url,
)

SUPPORTED_INSTANCE_TENANT_ID = "anytoolai"
SUPPORTED_INSTANCE_REGION = "ru"


def require_supported_instance_scope(*, tenant_id: str, region: str) -> None:
    """Reject deployment scopes that do not have a supported bootstrap."""
    if (tenant_id, region) != (SUPPORTED_INSTANCE_TENANT_ID, SUPPORTED_INSTANCE_REGION):
        raise ValueError(
            "unsupported instance scope: the current bootstrap supports only "
            f"{SUPPORTED_INSTANCE_TENANT_ID}/{SUPPORTED_INSTANCE_REGION}"
        )


def _split_csv_value(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


class AppEnv(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_env: AppEnv
    instance_tenant_id: Annotated[
        str,
        StringConstraints(strip_whitespace=True, to_lower=True, min_length=1),
    ]
    instance_region: Annotated[
        str,
        StringConstraints(strip_whitespace=True, to_lower=True, min_length=1),
    ]
    app_public_base_url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    database_url: Annotated[str, StringConstraints(strip_whitespace=True)] = ""
    cors_allow_origins: Annotated[tuple[str, ...], NoDecode]
    postgres_db: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    postgres_user: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    postgres_password: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    postgres_host: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    postgres_port: int
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "support@any-tool-ai.ru"
    smtp_use_tls: bool = True
    sentry_dsn: Annotated[str, StringConstraints(strip_whitespace=True)] = ""
    sentry_release: Annotated[str, StringConstraints(strip_whitespace=True)] = ""
    kernel_base_url: str = ""
    kernel_service_token: SecretStr = SecretStr("")
    kernel_mock_enabled: bool = False
    # Application policy, in seconds/bytes/operations; not a source-provider SLA.
    preflight_total_timeout_seconds: float = Field(default=10.0, gt=0, le=120, allow_inf_nan=False)
    preflight_cleanup_timeout_seconds: float = Field(default=0.25, gt=0, le=5, allow_inf_nan=False)
    preflight_max_active: int = Field(default=8, ge=1, le=128)
    preflight_max_waiting: int = Field(default=8, ge=0, le=128)
    kernel_connect_timeout_seconds: float = Field(default=1.0, gt=0, le=30, allow_inf_nan=False)
    kernel_read_timeout_seconds: float = Field(default=2.0, gt=0, le=30, allow_inf_nan=False)
    kernel_max_response_bytes: int = Field(default=262144, ge=1024, le=1048576)
    kernel_max_retries: int = Field(default=1, ge=0, le=2)
    kernel_retry_delay_seconds: float = Field(default=0.1, ge=0, le=5, allow_inf_nan=False)
    lbx_base_url: str = ""
    lbx_server_username: SecretStr = SecretStr("")
    lbx_server_password: SecretStr = SecretStr("")
    lbx_widget_signing_secret: SecretStr = SecretStr("")
    lbx_seller_organization_id: str = ""
    # Required only for effective-dated offers, never inferred from locale/host.
    lbx_billing_timezone: str = ""
    lbx_currency_id: str = "1"
    lbx_currency: str = "RUB"
    lbx_connect_timeout_seconds: float = Field(default=1.0, gt=0, le=30, allow_inf_nan=False)
    lbx_read_timeout_seconds: float = Field(default=2.0, gt=0, le=30, allow_inf_nan=False)
    lbx_max_response_bytes: int = Field(default=524288, ge=1024, le=1048576)
    # Total HTTP exchanges per logical read, INCLUDING auth and one reauth.
    lbx_max_get_attempts: int = Field(default=5, ge=1, le=8)
    lbx_retry_delay_seconds: float = Field(default=0.1, ge=0, le=5, allow_inf_nan=False)
    lbx_max_retry_delay_seconds: float = Field(default=2.0, ge=0, le=5, allow_inf_nan=False)
    # CLI execution identity; no default principal, wildcard or human attribution.
    mapping_operator_uids: tuple[Annotated[int, Field(strict=True, ge=0)], ...] = ()
    # Shared trusted local path for ALL operator processes in this deployment.
    # Required by dry-run/publish only; query and the HTTP API do not use it.
    mapping_operator_lock_file: Path | None = None
    mapping_lock_timeout_seconds: float = Field(default=2.0, gt=0, le=10, allow_inf_nan=False)

    @field_validator("smtp_use_tls", mode="before")
    @classmethod
    def parse_smtp_use_tls(cls, value: Any) -> bool:
        if isinstance(value, str):
            return value.lower() == "true"
        return bool(value)

    @field_validator("cors_allow_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return _split_csv_value(value)
        if value is None:
            return ()
        return tuple(value)

    @field_validator("app_public_base_url")
    @classmethod
    def require_https_public_base_url_in_production(cls, value: str, info: ValidationInfo) -> str:
        if info.data.get("app_env") == AppEnv.PRODUCTION:
            return validate_production_public_url(value, "APP_PUBLIC_BASE_URL")
        return value

    @field_validator("sentry_dsn")
    @classmethod
    def require_https_sentry_dsn_in_production(cls, value: str, info: ValidationInfo) -> str:
        if value and info.data.get("app_env") == AppEnv.PRODUCTION:
            return validate_production_public_url(value, "SENTRY_DSN")
        return value

    @model_validator(mode="before")
    @classmethod
    def derive_database_url_from_postgres_environment(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        if str(data.get("database_url") or "").strip():
            return data

        postgres_db = str(data.get("postgres_db") or "").strip()
        postgres_user = str(data.get("postgres_user") or "").strip()
        postgres_password = str(data.get("postgres_password") or "")
        if not (postgres_db and postgres_user and postgres_password):
            return data

        postgres_host = str(data.get("postgres_host") or "postgres").strip() or "postgres"
        postgres_port = int(data.get("postgres_port") or 5432)
        database_url = (
            f"postgresql+psycopg://{quote(postgres_user, safe='')}:"
            f"{quote(postgres_password, safe='')}@{postgres_host}:{postgres_port}/"
            f"{quote(postgres_db, safe='')}"
        )
        return {**data, "database_url": database_url}

    @field_validator("database_url")
    @classmethod
    def require_database_url(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("DATABASE_URL is required")
        return value

    @field_validator("cors_allow_origins")
    @classmethod
    def require_cors_origins(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        if not value:
            raise ValueError("CORS_ALLOW_ORIGINS is required")
        if info.data.get("app_env") == AppEnv.PRODUCTION:
            return tuple(validate_production_cors_origin(origin) for origin in value)
        return value

    @model_validator(mode="after")
    def require_supported_bootstrap_scope(self) -> Settings:
        require_supported_instance_scope(
            tenant_id=self.instance_tenant_id,
            region=self.instance_region,
        )
        return self

    @model_validator(mode="after")
    def require_sentry_release_when_enabled(self) -> Settings:
        if self.sentry_dsn and not self.sentry_release:
            raise ValueError("SENTRY_RELEASE is required when SENTRY_DSN is configured")
        return self

    @model_validator(mode="after")
    def require_safe_kernel_configuration(self) -> Settings:
        if self.preflight_cleanup_timeout_seconds >= self.preflight_total_timeout_seconds:
            raise ValueError("preflight cleanup reserve must be shorter than the total timeout")
        if self.kernel_mock_enabled and self.app_env == AppEnv.PRODUCTION:
            raise ValueError("Kernel mock requires development/test")
        token = self.kernel_service_token.get_secret_value()
        if not self.kernel_base_url and not token:
            return self
        if not self.kernel_base_url or not token:
            raise ValueError("KERNEL_BASE_URL and KERNEL_SERVICE_TOKEN must be configured together")
        try:
            parsed = urlsplit(self.kernel_base_url)
            port = parsed.port
        except ValueError:
            raise ValueError("KERNEL_BASE_URL must be an HTTP(S) origin") from None
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(char.isspace() or ord(char) < 33 for char in self.kernel_base_url)
            or port == 0
        ):
            raise ValueError("KERNEL_BASE_URL must be an HTTP(S) origin without credentials or query")
        if not token.isascii() or any(not 33 <= ord(char) <= 126 for char in token):
            raise ValueError("KERNEL_SERVICE_TOKEN must be a nonempty printable service token without whitespace")
        if self.app_env == AppEnv.PRODUCTION:
            validate_production_public_url(self.kernel_base_url, "KERNEL_BASE_URL")
            if parsed.hostname == "kernel-mock" or parsed.hostname.startswith("kernel-mock."):
                raise ValueError("Kernel mock requires development/test")
        return self

    @property
    def lbx_configuration_error(self) -> str | None:
        """Billing validation is local to billing; a partial config cannot break auth.

        Return field names/codes only. Do not attach input values or credentials.
        """
        username = self.lbx_server_username.get_secret_value()
        password = self.lbx_server_password.get_secret_value()
        configured = (
            self.lbx_base_url,
            username,
            password,
            self.lbx_widget_signing_secret.get_secret_value(),
            self.lbx_seller_organization_id,
        )
        if not any(configured):
            return "lbx_not_configured"
        if not all(configured):
            return "lbx_connection_fields_required"
        try:
            parsed = urlsplit(self.lbx_base_url)
            port = parsed.port
        except ValueError:
            return "lbx_base_url_invalid"
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or any(char.isspace() or ord(char) < 33 for char in self.lbx_base_url)
            or port == 0
        ):
            return "lbx_base_url_invalid"
        if ":" in username or any(ord(char) < 32 or ord(char) == 127 for char in username + password):
            return "lbx_server_credentials_invalid"
        if (
            not self.lbx_seller_organization_id.isascii()
            or not self.lbx_seller_organization_id.isdecimal()
            or not self.lbx_seller_organization_id.lstrip("0")
        ):
            return "lbx_seller_organization_id_invalid"
        if self.app_env == AppEnv.PRODUCTION:
            try:
                validate_production_public_url(self.lbx_base_url, "LBX_BASE_URL")
            except ValueError:
                return "lbx_base_url_requires_public_https"
        return None

    @property
    def lbx_external_billing_account_id(self) -> str:
        """Storage-compatible connection scope. Password rotation preserves identity.

        This is provenance of a trusted connection, not provider account proof.
        No manual scope input, locale, browser value or secret is included.
        """
        if not self.lbx_base_url or not self.lbx_server_username.get_secret_value():
            return ""
        try:
            parsed = urlsplit(self.lbx_base_url)
            port = parsed.port
        except ValueError:
            return ""
        hostname = parsed.hostname or ""
        if ":" in hostname:
            hostname = f"[{hostname}]"
        suffix = "" if port is None or (parsed.scheme, port) in {("http", 80), ("https", 443)} else f":{port}"
        origin = f"{parsed.scheme.lower()}://{hostname.lower()}{suffix}"
        identity = json.dumps([origin, self.lbx_server_username.get_secret_value()], separators=(",", ":"))
        return "lbx-connection:v1:" + hashlib.sha256(identity.encode()).hexdigest()


def _load_settings_env_file(settings_file: Path | str = Path(__file__)) -> str | None:
    search_root = Path(settings_file).resolve().parent
    for directory in (search_root, *search_root.parents):
        dotenv_file = directory / ".env"
        if dotenv_file.is_file():
            dotenv_path = str(dotenv_file)
            load_dotenv(dotenv_path, override=False)
            return dotenv_path
        if (directory / "AGENTS.md").is_file() and (directory / "apps" / "api").is_dir():
            break
    return None


settings = Settings(_env_file=_load_settings_env_file())
