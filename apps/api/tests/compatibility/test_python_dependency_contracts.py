from __future__ import annotations

import os
import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from sqlalchemy.engine import make_url

from apps.api.tests.support.settings import DEFAULT_API_TEST_ENV
from apps.api.tests.support.settings import configure_api_test_environment
from apps.api.tests.support.postgres import alembic_test_config

configure_api_test_environment()

from app.core.settings import AppEnv, Settings  # noqa: E402
from app.core.settings import _load_settings_env_file  # noqa: E402
from app.domains.identity.router import normalize_email  # noqa: E402
from apps.api.tests.factories.auth import (  # noqa: E402
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


def test_settings_require_critical_environment_values_when_environment_is_absent() -> None:
    with patch.dict(os.environ, {}, clear=True):
        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None)

    missing_fields = {validation_error["loc"][0] for validation_error in error.value.errors()}
    assert missing_fields == {
        "app_env",
        "app_public_base_url",
        "database_url",
        "postgres_db",
        "postgres_user",
        "postgres_password",
        "postgres_host",
        "postgres_port",
        "cloudpayments_enabled",
        "cors_allow_origins",
    }


@pytest.mark.parametrize("app_env", ["development", "test", "production"])
def test_settings_accept_supported_app_environments(app_env: str) -> None:
    environment = {
        **DEFAULT_API_TEST_ENV,
        "APP_ENV": app_env,
        "APP_PUBLIC_BASE_URL": "https://payments.example.com",
        "CORS_ALLOW_ORIGINS": "https://payments.example.com",
    }
    with patch.dict(os.environ, environment, clear=True):
        loaded_settings = Settings(_env_file=None)

    assert loaded_settings.app_env == AppEnv(app_env)
    assert loaded_settings.app_public_base_url == "https://payments.example.com"
    assert loaded_settings.database_url == "sqlite+pysqlite:///:memory:"
    assert loaded_settings.cloudpayments_enabled is False
    assert loaded_settings.cors_allow_origins == ("https://payments.example.com",)
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
    cloudpayments_credentials = (
        {
            "CLOUDPAYMENTS_PUBLIC_ID": "pk_test_provider",
            "CLOUDPAYMENTS_API_SECRET": "secret-test-provider",
        }
        if expected
        else {}
    )
    with patch.dict(
        os.environ,
        {
            **DEFAULT_API_TEST_ENV,
            **cloudpayments_credentials,
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
                "APP_ENV=development",
                'APP_PUBLIC_BASE_URL="https://dotenv.example/app"',
                "DATABASE_URL=sqlite+pysqlite:///from-dotenv.db",
                "POSTGRES_DB=payments_dotenv",
                "POSTGRES_USER=dotenv_user",
                "POSTGRES_PASSWORD=dotenv_password",
                "POSTGRES_HOST=postgres",
                "POSTGRES_PORT=5432",
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
            "APP_ENV": "test",
            "APP_PUBLIC_BASE_URL": "https://process.example/app",
            "SMTP_USERNAME": "process-user",
        },
        clear=True,
    ):
        loaded_settings = Settings(_env_file=dotenv_path)

    assert loaded_settings.app_env == AppEnv.TEST
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


def test_settings_derives_encoded_database_url_from_postgres_environment() -> None:
    environment = {
        **DEFAULT_API_TEST_ENV,
        "DATABASE_URL": "",
        "POSTGRES_DB": "payments/prod",
        "POSTGRES_USER": "payments user",
        "POSTGRES_PASSWORD": "secret#value?",
        "POSTGRES_HOST": "postgres",
        "POSTGRES_PORT": "5432",
    }
    with patch.dict(os.environ, environment, clear=True):
        loaded_settings = Settings(_env_file=None)

    assert loaded_settings.database_url == (
        "postgresql+psycopg://payments%20user:secret%23value%3F@postgres:5432/payments%2Fprod"
    )


def test_alembic_test_config_overrides_settings_database_url() -> None:
    from app.core.settings import settings

    original_database_url = settings.database_url
    database_url = make_url("postgresql+psycopg://test_user:secret%23value%3F@localhost:5432/payments_alembic_test")
    expected_database_url = "postgresql+psycopg://test_user:secret%23value%3F@localhost:5432/payments_alembic_test"

    with alembic_test_config(database_url) as config:
        assert config.get_main_option("sqlalchemy.url") == expected_database_url
        assert os.environ["DATABASE_URL"] == expected_database_url
        assert settings.database_url == expected_database_url

    assert settings.database_url == original_database_url


@pytest.mark.parametrize("app_env", ["", "staging", "prod"])
def test_settings_reject_unsupported_app_environment(app_env: str) -> None:
    environment = {**DEFAULT_API_TEST_ENV, "APP_ENV": app_env}
    with patch.dict(os.environ, environment, clear=True):
        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None)

    assert error.value.errors()[0]["loc"] == ("app_env",)


@pytest.mark.parametrize(
    ("missing_name", "field_name"),
    [
        ("APP_PUBLIC_BASE_URL", "app_public_base_url"),
        ("POSTGRES_DB", "postgres_db"),
        ("POSTGRES_USER", "postgres_user"),
        ("POSTGRES_PASSWORD", "postgres_password"),
        ("POSTGRES_HOST", "postgres_host"),
        ("POSTGRES_PORT", "postgres_port"),
        ("CLOUDPAYMENTS_ENABLED", "cloudpayments_enabled"),
        ("CORS_ALLOW_ORIGINS", "cors_allow_origins"),
    ],
)
def test_settings_require_each_critical_environment_value(missing_name: str, field_name: str) -> None:
    environment = DEFAULT_API_TEST_ENV.copy()
    environment.pop(missing_name)
    with patch.dict(os.environ, environment, clear=True):
        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None)

    assert {validation_error["loc"][0] for validation_error in error.value.errors()} == {field_name}


@pytest.mark.parametrize(
    "field_name",
    [
        "APP_PUBLIC_BASE_URL",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_HOST",
        "POSTGRES_PORT",
        "CORS_ALLOW_ORIGINS",
    ],
)
def test_settings_reject_empty_critical_environment_values(field_name: str) -> None:
    environment = {**DEFAULT_API_TEST_ENV, field_name: ""}
    with patch.dict(os.environ, environment, clear=True):
        with pytest.raises(ValidationError):
            Settings(_env_file=None)


def test_settings_require_https_public_base_url_in_production() -> None:
    environment = {
        **DEFAULT_API_TEST_ENV,
        "APP_ENV": "production",
        "APP_PUBLIC_BASE_URL": "http://payments.example.com",
        "CORS_ALLOW_ORIGINS": "https://payments.example.com",
    }
    with patch.dict(os.environ, environment, clear=True):
        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None)

    assert "APP_PUBLIC_BASE_URL must use https in production" in str(error.value)


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://[::1]:3000",
        "*",
    ],
)
def test_settings_reject_forbidden_production_cors_origins(origin: str) -> None:
    environment = {
        **DEFAULT_API_TEST_ENV,
        "APP_ENV": "production",
        "APP_PUBLIC_BASE_URL": "https://payments.example.com",
        "CORS_ALLOW_ORIGINS": origin,
    }
    with patch.dict(os.environ, environment, clear=True):
        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None)

    assert "CORS_ALLOW_ORIGINS contains a forbidden production origin" in str(error.value)


@pytest.mark.parametrize("empty_name", ["CLOUDPAYMENTS_PUBLIC_ID", "CLOUDPAYMENTS_API_SECRET"])
def test_settings_reject_empty_cloudpayments_credentials_when_provider_is_enabled(empty_name: str) -> None:
    environment = {
        **DEFAULT_API_TEST_ENV,
        "CLOUDPAYMENTS_ENABLED": "true",
        "CLOUDPAYMENTS_PUBLIC_ID": "pk_test_provider",
        "CLOUDPAYMENTS_API_SECRET": "secret-test-provider",
    }
    environment[empty_name] = ""
    with patch.dict(os.environ, environment, clear=True):
        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None)

    assert f"{empty_name} is required when CLOUDPAYMENTS_ENABLED=true" in str(error.value)


def test_settings_validation_messages_do_not_include_sensitive_values() -> None:
    environment = {
        **DEFAULT_API_TEST_ENV,
        "APP_ENV": "production",
        "APP_PUBLIC_BASE_URL": "http://secret-host.example/app",
        "DATABASE_URL": "postgresql+psycopg://secret-user:secret-password@db.example/payments",
        "CLOUDPAYMENTS_ENABLED": "true",
        "CLOUDPAYMENTS_PUBLIC_ID": "pk_secret_public_id",
        "CLOUDPAYMENTS_API_SECRET": "secret-cloudpayments-api-key",
    }
    with patch.dict(os.environ, environment, clear=True):
        with pytest.raises(ValidationError) as error:
            Settings(_env_file=None)

    message = str(error.value)
    assert "secret-host.example" not in message
    assert "secret-user" not in message
    assert "secret-password" not in message
    assert "pk_secret_public_id" not in message
    assert "secret-cloudpayments-api-key" not in message


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
    repository_root = tmp_path / "repository"
    settings_file = repository_root / "apps" / "api" / "app" / "core" / "settings.py"
    settings_file.parent.mkdir(parents=True)
    (repository_root / "AGENTS.md").write_text("# Repository instructions\n", encoding="utf-8")
    dotenv_path = repository_root / ".env"
    dotenv_path.write_text(
        "\n".join(
            [
                "LOG_LEVEL=DEBUG",
                "OTEL_EXPORTER_OTLP_ENDPOINT=http://127.0.0.1:4318",
                "OTEL_SERVICE_NAME=payment-portal-test",
                "SKIP_LEGAL_SEED=true",
            ]
        ),
        encoding="utf-8",
    )

    with patch.dict(os.environ, {"LOG_LEVEL": "WARNING"}, clear=True):
        assert _load_settings_env_file(settings_file) == str(dotenv_path)

        assert os.environ["LOG_LEVEL"] == "WARNING"
        assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == "http://127.0.0.1:4318"
        assert os.environ["OTEL_SERVICE_NAME"] == "payment-portal-test"
        assert os.environ["SKIP_LEGAL_SEED"] == "true"


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

    with patch.dict(os.environ, {}, clear=True):
        assert _load_settings_env_file(settings_file) == str(repository_dotenv)

    repository_dotenv.unlink()

    assert _load_settings_env_file(settings_file) is None


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
