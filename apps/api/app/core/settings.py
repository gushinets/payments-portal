from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _split_csv_env(name: str) -> tuple[str, ...]:
    raw = os.getenv(name, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class Settings:
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql+psycopg://anytoolai:anytoolai@localhost:5432/anytoolai",
    )
    cloudpayments_public_id: str = os.getenv("CLOUDPAYMENTS_PUBLIC_ID", "")
    cloudpayments_api_secret: str = os.getenv("CLOUDPAYMENTS_API_SECRET", "")
    cloudpayments_enabled: bool = (
        os.getenv("CLOUDPAYMENTS_ENABLED", "false").lower() == "true"
    )
    cors_allow_origins: tuple[str, ...] = _split_csv_env("CORS_ALLOW_ORIGINS")


settings = Settings()
