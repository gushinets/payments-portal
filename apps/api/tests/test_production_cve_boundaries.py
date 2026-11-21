from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from apps.api.tests.support.settings import DEFAULT_API_TEST_ENV, configure_api_test_environment

configure_api_test_environment()

from app.core.settings import Settings  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


def settings_for(database_url: str, app_env: str) -> Settings:
    environment = {
        **DEFAULT_API_TEST_ENV,
        "APP_ENV": app_env,
        "APP_PUBLIC_BASE_URL": "https://payments.example.com",
        "CORS_ALLOW_ORIGINS": "https://payments.example.com",
        "DATABASE_URL": database_url,
    }
    with patch.dict(os.environ, environment, clear=True):
        return Settings(_env_file=None)


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite+pysqlite:///:memory:",
        "sqlite:////tmp/untrusted.db",
        "mysql+pymysql://user:private-value@db/payments",
        "postgresql://user:private-value@db:private-value/payments",
    ],
)
def test_production_rejects_non_postgresql_database(database_url: str) -> None:
    with pytest.raises(ValidationError, match="Production DATABASE_URL must use PostgreSQL") as error:
        settings_for(database_url, "production")

    assert "private-value" not in str(error.value)


@pytest.mark.parametrize("app_env", ["test", "development"])
def test_sqlite_remains_supported_outside_production(app_env: str) -> None:
    assert settings_for("sqlite+pysqlite:///:memory:", app_env).database_url == "sqlite+pysqlite:///:memory:"


@pytest.mark.parametrize(
    "database_url", ["postgresql+psycopg://user:value@db/payments", "postgresql://user:value@db/payments"]
)
def test_production_preserves_postgresql_database_contract(database_url: str) -> None:
    assert settings_for(database_url, "production").database_url == database_url


@pytest.mark.parametrize("service", ["api", "migrate"])
def test_production_api_and_migrations_drop_all_capabilities(service: str) -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8"))
    security = compose["services"][service]

    assert security.get("cap_drop") == ["ALL"]
    assert not security.get("cap_add")
    assert not security.get("privileged", False)
    assert "no-new-privileges:true" in security["security_opt"]
