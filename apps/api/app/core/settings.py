from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any

from dotenv import load_dotenv
from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _split_csv_value(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    app_public_base_url: str = "http://localhost:3000"
    database_url: str = "postgresql+psycopg://anytoolai:anytoolai@localhost:5432/anytoolai"
    cloudpayments_public_id: str = ""
    cloudpayments_api_secret: str = ""
    cloudpayments_enabled: bool = False
    cors_allow_origins: Annotated[tuple[str, ...], NoDecode] = ()
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


def _dotenv_file(settings_file: Path | str = Path(__file__)) -> str | None:
    search_root = Path(settings_file).resolve().parent
    for directory in (search_root, *search_root.parents):
        dotenv_file = directory / ".env"
        if dotenv_file.is_file():
            return str(dotenv_file)
        if _is_repository_root(directory):
            break
    return None


def _is_repository_root(directory: Path) -> bool:
    return (directory / "AGENTS.md").is_file() and (directory / "apps" / "api").is_dir()


def _load_dotenv_into_environment(dotenv_file: str | None) -> str | None:
    if dotenv_file:
        load_dotenv(dotenv_file, override=False)
    return dotenv_file


settings = Settings(_env_file=_load_dotenv_into_environment(_dotenv_file()))
