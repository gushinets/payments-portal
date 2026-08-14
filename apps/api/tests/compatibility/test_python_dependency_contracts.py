from __future__ import annotations

import os
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.core.settings import Settings
from app.core.settings import _dotenv_file
from app.core.settings import _load_dotenv_into_environment
from app.domains.identity.router import normalize_email
from apps.api.tests.factories.auth import (
    LoginRequestFactory,
    RegisterRequestFactory,
)

API_ROOT = Path(__file__).resolve().parents[2]


def assert_register_email_is_rejected(email: str) -> None:
    with pytest.raises(ValidationError):
        RegisterRequestFactory.build(email=email)


@pytest.mark.parametrize("email", ["not-an-email", "user＠example.com"])
def test_identity_email_validation_rejects_malformed_addresses(email: str) -> None:
    assert_register_email_is_rejected(email)


def test_identity_email_validation_preserves_current_length_boundaries() -> None:
    local_part_limit_email = f"{'a' * 64}@example.com"
    local_part_65_email = f"{'a' * 65}@example.com"
    max_total_length_email = f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 57}.com"
    over_total_length_email = f"{'a' * 64}@{'b' * 63}.{'c' * 63}.{'d' * 58}.com"

    assert len(max_total_length_email) == 254
    assert len(over_total_length_email) == 255
    assert str(RegisterRequestFactory.build(email=local_part_limit_email).email) == (local_part_limit_email)
    assert str(RegisterRequestFactory.build(email=local_part_65_email).email) == (local_part_65_email)
    assert str(RegisterRequestFactory.build(email=max_total_length_email).email) == (max_total_length_email)
    assert_register_email_is_rejected(over_total_length_email)


@pytest.mark.parametrize("factory", [RegisterRequestFactory, LoginRequestFactory])
def test_identity_email_normalization_contract_for_auth_lookup(factory: type) -> None:
    request = factory.build(email="USER@EXAMPLE.COM")

    assert str(request.email) == "USER@example.com"
    assert normalize_email(str(request.email)) == "user@example.com"


def test_settings_preserve_fallback_defaults_when_environment_is_absent() -> None:
    with patch.dict(os.environ, {}, clear=True):
        loaded_settings = Settings(_env_file=None)

    assert loaded_settings.app_public_base_url == "http://localhost:3000"
    assert loaded_settings.database_url == ("postgresql+psycopg://anytoolai:anytoolai@localhost:5432/anytoolai")
    assert loaded_settings.cloudpayments_public_id == ""
    assert loaded_settings.cloudpayments_api_secret == ""
    assert loaded_settings.cloudpayments_enabled is False
    assert loaded_settings.cors_allow_origins == ()
    assert loaded_settings.smtp_host == ""
    assert loaded_settings.smtp_port == 587
    assert loaded_settings.smtp_username == ""
    assert loaded_settings.smtp_password == ""
    assert loaded_settings.smtp_from_email == "support@any-tool-ai.ru"
    assert loaded_settings.smtp_use_tls is True


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [
        ("true", True),
        ("TRUE", True),
        ("false", False),
        ("1", False),
        ("yes", False),
        ("", False),
    ],
)
def test_settings_preserve_legacy_boolean_parsing(
    raw_value: str,
    expected: bool,
) -> None:
    with patch.dict(
        os.environ,
        {
            "CLOUDPAYMENTS_ENABLED": raw_value,
            "SMTP_USE_TLS": raw_value,
        },
        clear=True,
    ):
        loaded_settings = Settings(_env_file=None)

    assert loaded_settings.cloudpayments_enabled is expected
    assert loaded_settings.smtp_use_tls is expected


def test_settings_preserve_dotenv_parsing_and_process_environment_precedence(
    tmp_path: Path,
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                'APP_PUBLIC_BASE_URL="https://dotenv.example/app"',
                "DATABASE_URL=sqlite+pysqlite:///from-dotenv.db",
                "CLOUDPAYMENTS_PUBLIC_ID=pk_from_dotenv",
                "CLOUDPAYMENTS_API_SECRET=secret-from-dotenv",
                "CLOUDPAYMENTS_ENABLED=true",
                'CORS_ALLOW_ORIGINS="https://web.example, https://admin.example"',
                "SMTP_HOST=smtp.dotenv.example",
                "SMTP_PORT=2525",
                "SMTP_USERNAME=dotenv-user",
                "SMTP_PASSWORD=dotenv-password",
                "SMTP_FROM_EMAIL=payments@example.com",
                "SMTP_USE_TLS=false",
            ]
        ),
        encoding="utf-8",
    )

    with patch.dict(
        os.environ,
        {
            "APP_PUBLIC_BASE_URL": "https://process.example/app",
            "SMTP_USERNAME": "process-user",
        },
        clear=True,
    ):
        loaded_settings = Settings(_env_file=dotenv_path)

    assert loaded_settings.app_public_base_url == "https://process.example/app"
    assert loaded_settings.database_url == "sqlite+pysqlite:///from-dotenv.db"
    assert loaded_settings.cloudpayments_public_id == "pk_from_dotenv"
    assert loaded_settings.cloudpayments_api_secret == "secret-from-dotenv"
    assert loaded_settings.cloudpayments_enabled is True
    assert loaded_settings.cors_allow_origins == (
        "https://web.example",
        "https://admin.example",
    )
    assert loaded_settings.smtp_host == "smtp.dotenv.example"
    assert loaded_settings.smtp_port == 2525
    assert loaded_settings.smtp_username == "process-user"
    assert loaded_settings.smtp_password == "dotenv-password"
    assert loaded_settings.smtp_from_email == "payments@example.com"
    assert loaded_settings.smtp_use_tls is False


def test_settings_do_not_expose_configurable_default_scope() -> None:
    assert "default_tenant_id" not in Settings.model_fields
    assert "default_region" not in Settings.model_fields


def test_identity_default_scope_stays_aligned_with_ru_seed_data() -> None:
    with patch.dict(
        os.environ,
        {
            "DEFAULT_TENANT_ID": "tenant-from-env",
            "DEFAULT_REGION": "eu",
        },
        clear=True,
    ):
        import app.domains.identity.session as session_module

        assert session_module.DEFAULT_TENANT_ID == "anytoolai"
        assert session_module.DEFAULT_REGION == "ru"


def test_runtime_dotenv_preserves_os_getenv_consumers(
    tmp_path: Path,
) -> None:
    dotenv_path = tmp_path / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "LOG_LEVEL=DEBUG",
                "OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318",
                "OTEL_SERVICE_NAME=payment-portal-test",
            ]
        ),
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"LOG_LEVEL": "WARNING"}, clear=True):
        assert _load_dotenv_into_environment(str(dotenv_path)) == str(dotenv_path)

        assert os.environ["LOG_LEVEL"] == "WARNING"
        assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:4318"
        assert os.environ["OTEL_SERVICE_NAME"] == "payment-portal-test"


def test_dotenv_discovery_starts_from_settings_module_tree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    settings_file = repository_root / "apps" / "api" / "app" / "core" / "settings.py"
    settings_file.parent.mkdir(parents=True)
    (repository_root / "AGENTS.md").write_text("# Repository instructions\n", encoding="utf-8")
    repository_dotenv = repository_root / ".env"
    repository_dotenv.write_text("DATABASE_URL=sqlite+pysqlite:///repo.db\n", encoding="utf-8")

    outside_working_directory = tmp_path / "outside" / "nested"
    outside_working_directory.mkdir(parents=True)
    (tmp_path / "outside" / ".env").write_text("DATABASE_URL=sqlite+pysqlite:///outside.db\n", encoding="utf-8")
    monkeypatch.chdir(outside_working_directory)

    assert _dotenv_file(settings_file) == str(repository_dotenv)

    repository_dotenv.unlink()

    assert _dotenv_file(settings_file) is None


def test_api_test_tooling_stays_out_of_main_dependencies() -> None:
    pyproject = tomllib.loads((API_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    poetry_config = pyproject["tool"]["poetry"]
    main_dependencies = set(poetry_config["dependencies"])
    dev_dependencies = set(poetry_config["group"]["dev"]["dependencies"])
    test_tooling = {"httpx2", "polyfactory", "pytest", "pytest-cov", "ruff"}

    assert test_tooling.isdisjoint(main_dependencies)
    assert test_tooling.issubset(dev_dependencies)


def test_api_production_image_installs_only_main_dependencies() -> None:
    dockerfile = (API_ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "poetry --directory apps/api install --only main --no-root" in dockerfile
