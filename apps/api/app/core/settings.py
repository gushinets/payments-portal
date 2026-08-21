from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import quote

from dotenv import load_dotenv
from pydantic import Field, StringConstraints, ValidationInfo, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.core.url_validation import validate_production_cors_origin, validate_production_public_url


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
    database_url: Annotated[str, StringConstraints(strip_whitespace=True)] = ""
    cloudpayments_enabled: bool
    cors_allow_origins: Annotated[tuple[str, ...], NoDecode]
    postgres_db: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    postgres_user: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    postgres_password: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    postgres_host: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    postgres_port: int
    cloudpayments_public_id: str = ""
    cloudpayments_api_secret: str = ""
    cloudpayments_api_base_url: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)] = (
        "https://api.cloudpayments.ru"
    )
    cloudpayments_api_timeout_seconds: float = Field(default=10.0, gt=0)
    cloudpayments_api_connect_timeout_seconds: float = Field(default=3.0, gt=0)
    cloudpayments_api_read_timeout_seconds: float = Field(default=10.0, gt=0)
    cloudpayments_api_write_timeout_seconds: float = Field(default=10.0, gt=0)
    cloudpayments_api_pool_timeout_seconds: float = Field(default=3.0, gt=0)
    cloudpayments_api_max_retries: int = Field(default=2, ge=0)
    cloudpayments_api_retry_backoff_seconds: float = Field(default=0.5, ge=0)
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
        if info.data.get("app_env") == AppEnv.PRODUCTION:
            return validate_production_public_url(value, "APP_PUBLIC_BASE_URL")
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
