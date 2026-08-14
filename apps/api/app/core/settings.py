from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from dotenv import load_dotenv


def _split_csv_value(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _bool_env(environ: Mapping[str, str], name: str, default: str) -> bool:
    return environ.get(name, default).lower() == "true"


def _int_env(environ: Mapping[str, str], name: str, default: str) -> int:
    return int(environ.get(name, default))


@dataclass(frozen=True)
class Settings:
    app_public_base_url: str = "http://localhost:3000"
    database_url: str = (
        "postgresql+psycopg://anytoolai:anytoolai@localhost:5432/anytoolai"
    )
    cloudpayments_public_id: str = ""
    cloudpayments_api_secret: str = ""
    cloudpayments_enabled: bool = False
    cors_allow_origins: tuple[str, ...] = ()
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "support@any-tool-ai.ru"
    smtp_use_tls: bool = True


def load_settings_from_environment(environ: Mapping[str, str]) -> Settings:
    return Settings(
        app_public_base_url=environ.get(
            "APP_PUBLIC_BASE_URL",
            "http://localhost:3000",
        ),
        database_url=environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://anytoolai:anytoolai@localhost:5432/anytoolai",
        ),
        cloudpayments_public_id=environ.get("CLOUDPAYMENTS_PUBLIC_ID", ""),
        cloudpayments_api_secret=environ.get("CLOUDPAYMENTS_API_SECRET", ""),
        cloudpayments_enabled=_bool_env(environ, "CLOUDPAYMENTS_ENABLED", "false"),
        cors_allow_origins=_split_csv_value(environ.get("CORS_ALLOW_ORIGINS", "")),
        smtp_host=environ.get("SMTP_HOST", ""),
        smtp_port=_int_env(environ, "SMTP_PORT", "587"),
        smtp_username=environ.get("SMTP_USERNAME", ""),
        smtp_password=environ.get("SMTP_PASSWORD", ""),
        smtp_from_email=environ.get("SMTP_FROM_EMAIL", "support@any-tool-ai.ru"),
        smtp_use_tls=_bool_env(environ, "SMTP_USE_TLS", "true"),
    )


load_dotenv()
settings = load_settings_from_environment(os.environ)
