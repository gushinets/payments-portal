from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from pydantic import StringConstraints, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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
    app_public_base_url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    database_url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    cloudpayments_enabled: bool
    cors_allow_origins: Annotated[tuple[str, ...], NoDecode]
    cloudpayments_public_id: str = ""
    cloudpayments_api_secret: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "support@any-tool-ai.ru"
    smtp_use_tls: bool = True

    @field_validator("cloudpayments_enabled", "smtp_use_tls", mode="before")
    @classmethod
    def parse_legacy_bool(cls, value: Any) -> bool:
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
        if info.data.get("app_env") == AppEnv.PRODUCTION and not value.startswith("https://"):
            raise ValueError("APP_PUBLIC_BASE_URL must use https in production")
        return value

    @field_validator("cors_allow_origins")
    @classmethod
    def require_cors_origins(cls, value: tuple[str, ...], info: ValidationInfo) -> tuple[str, ...]:
        if not value:
            raise ValueError("CORS_ALLOW_ORIGINS is required")
        if info.data.get("app_env") == AppEnv.PRODUCTION:
            forbidden_origins = ("localhost", "127.0.0.1", "::1", "*")
            if any(forbidden_origin in origin for origin in value for forbidden_origin in forbidden_origins):
                raise ValueError("CORS_ALLOW_ORIGINS contains a forbidden production origin")
        return value

    @model_validator(mode="after")
    def require_cloudpayments_credentials_when_enabled(self) -> Settings:
        if self.cloudpayments_enabled:
            if not self.cloudpayments_public_id.strip():
                raise ValueError("CLOUDPAYMENTS_PUBLIC_ID is required when CLOUDPAYMENTS_ENABLED=true")
            if not self.cloudpayments_api_secret.strip():
                raise ValueError("CLOUDPAYMENTS_API_SECRET is required when CLOUDPAYMENTS_ENABLED=true")
        return self


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
