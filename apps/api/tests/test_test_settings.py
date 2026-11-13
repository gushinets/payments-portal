"""Test-process configuration boundaries; all conflicting values are synthetic."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.settings import Settings, _load_settings_env_file
from apps.api.tests.support.settings import DEFAULT_API_TEST_ENV, api_test_environment, configure_api_test_environment
from scripts import repo


def test_configuration_removes_inherited_integrations_before_scenario_overrides() -> None:
    with patch.dict(
        os.environ,
        {
            "PATH": "retained-tool-path",
            "SMTP_HOST": "inherited.invalid",
            "LBX_SERVER_PASSWORD": "inherited-synthetic",
            "PREFLIGHT_TOTAL_TIMEOUT_SECONDS": "0.01",
            "KERNEL_MOCK_ENABLED": "1",
            "BILLING_WORKER_ENABLED": "true",
            "TEST_POSTGRES_DATABASE_URL": "postgresql+psycopg://localhost/explicit_tests",
        },
        clear=True,
    ):
        configure_api_test_environment(KERNEL_BASE_URL="http://scenario.test", KERNEL_SERVICE_TOKEN="synthetic")
        configuration = Settings(_env_file=None)
        assert configuration.smtp_host == ""
        assert configuration.lbx_server_password.get_secret_value() == ""
        assert configuration.preflight_total_timeout_seconds == 10
        assert not configuration.kernel_mock_enabled
        assert not configuration.billing_worker_enabled
        assert configuration.kernel_base_url == "http://scenario.test"
        assert os.environ["PATH"] == "retained-tool-path"
        assert os.environ["TEST_POSTGRES_DATABASE_URL"].endswith("/explicit_tests")


def test_fresh_pytest_bootstrap_and_child_ignore_conflicting_environment(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("KERNEL_MOCK_ENABLED=1\nSMTP_HOST=dotenv.invalid\n", encoding="utf-8")
    root = Path(__file__).resolve().parents[3]
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(root), str(root / "apps/api"))),
        "APP_ENV": "production",
        "DATABASE_URL": "invalid-inherited-url",
        "SMTP_HOST": "inherited.invalid",
        "KERNEL_BASE_URL": "http://inherited.invalid",
        "KERNEL_SERVICE_TOKEN": "synthetic-inherited",
        "KERNEL_MOCK_ENABLED": "1",
        "BILLING_WORKER_ENABLED": "true",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://inherited.invalid",
    }
    environment.pop("PYTHON_DOTENV_DISABLED", None)
    probe = """
import os
import subprocess
import sys
import dotenv

def reject_dotenv(*args, **kwargs):
    raise AssertionError("pytest bootstrap must not read a dotenv file")

dotenv.load_dotenv = reject_dotenv
import apps.api.tests.conftest
from app.core.settings import settings
assert settings.app_env == "test"
assert settings.database_url == "sqlite+pysqlite:///:memory:"
assert settings.smtp_host == ""
assert settings.kernel_base_url == ""
assert not settings.kernel_mock_enabled
assert not settings.billing_worker_enabled
assert os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"] == ""
child = subprocess.run([sys.executable, "-c", '''
from app.core.settings import settings
assert settings.smtp_host == ""
assert settings.kernel_base_url == ""
assert not settings.billing_worker_enabled
'''], check=False)
assert child.returncode == 0
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_disabled_dotenv_cannot_reenter_through_pydantic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / ".env"
    path.write_text("SMTP_HOST=dotenv.invalid\n", encoding="utf-8")
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    loaded = _load_settings_env_file(tmp_path / "settings.py")
    assert loaded is None
    assert Settings(_env_file=loaded).smtp_host == ""


@pytest.mark.parametrize("app_env", ["development", "production"])
def test_enabled_runtime_dotenv_keeps_environment_precedence(tmp_path: Path, app_env: str) -> None:
    path = tmp_path / ".env"
    path.write_text("SMTP_HOST=dotenv.invalid\nSMTP_USERNAME=dotenv-user\n", encoding="utf-8")
    environment = {
        **DEFAULT_API_TEST_ENV,
        "APP_ENV": app_env,
        "APP_PUBLIC_BASE_URL": "https://portal.example.test",
        "CORS_ALLOW_ORIGINS": "https://portal.example.test",
        "SMTP_USERNAME": "explicit-user",
    }
    with patch.dict(os.environ, environment, clear=True):
        loaded = _load_settings_env_file(tmp_path / "settings.py")
        assert loaded == str(path)
        configuration = Settings(_env_file=loaded)
        assert configuration.app_env == app_env
        assert configuration.smtp_host == "dotenv.invalid"
        assert configuration.smtp_username == "explicit-user"


def test_harness_dotenv_requires_explicit_synthetic_file_in_tests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repo, "ROOT", tmp_path)
    path = tmp_path / ".env"
    path.write_text("SMTP_HOST=dotenv.invalid\n", encoding="utf-8")
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    assert repo.read_dotenv() == {}
    assert repo.read_dotenv(path) == {"SMTP_HOST": "dotenv.invalid"}
    monkeypatch.delenv("PYTHON_DOTENV_DISABLED")
    assert repo.read_dotenv() == {"SMTP_HOST": "dotenv.invalid"}


def test_launcher_builds_safe_settings_without_losing_explicit_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(repo, "read_runtime_env", lambda: pytest.fail("explicit URL must win"))
    inherited = {
        "APP_ENV": "production",
        "KERNEL_BASE_URL": "http://inherited.invalid",
        "BILLING_WORKER_ENABLED": "true",
        "SMTP_HOST": "inherited.invalid",
        "TEST_POSTGRES_DATABASE_URL": "postgresql+psycopg://localhost/explicit_tests",
    }
    environment = repo.api_test_environment("api-postgres", inherited)
    assert environment["APP_ENV"] == "test"
    assert environment["BILLING_WORKER_ENABLED"] == "false"
    assert environment["PYTHON_DOTENV_DISABLED"] == "1"
    assert "KERNEL_BASE_URL" not in environment
    assert "SMTP_HOST" not in environment
    assert environment["TEST_POSTGRES_DATABASE_URL"] == inherited["TEST_POSTGRES_DATABASE_URL"]
    assert inherited["APP_ENV"] == "production"


def test_child_environment_defaults_then_explicit_scenario_overrides(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("SMTP_HOST=dotenv.invalid\n", encoding="utf-8")
    root = Path(__file__).resolve().parents[3]
    environment = api_test_environment(
        BILLING_WORKER_ENABLED="true",
        APP_ENV="development",
        KERNEL_BASE_URL="http://scenario.test",
        KERNEL_SERVICE_TOKEN="synthetic",
        PYTHONPATH=os.pathsep.join((str(root), str(root / "apps/api"))),
    )
    assert environment["BILLING_WORKER_ENABLED"] == "true"
    assert environment["APP_ENV"] == "development"
    assert environment["PYTHON_DOTENV_DISABLED"] == "1"
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from app.core.settings import settings; "
            "assert settings.app_env == 'development'; "
            "assert settings.billing_worker_enabled; "
            "assert settings.kernel_base_url == 'http://scenario.test'; "
            "assert settings.smtp_host == ''",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("uppercase", [True, False])
def test_every_application_setting_is_isolated_from_inherited_values(uppercase: bool) -> None:
    inherited = {(name.upper() if uppercase else name): "invalid-inherited-value" for name in Settings.model_fields}
    environment = api_test_environment(environ=inherited)
    with patch.dict(os.environ, environment, clear=True):
        configuration = Settings(_env_file=None)
    assert configuration.app_env == "test"
    assert configuration.database_url == "sqlite+pysqlite:///:memory:"
    assert configuration.kernel_base_url == configuration.lbx_base_url == configuration.smtp_host == ""


@pytest.mark.parametrize(
    "configuration",
    [
        {"POSTGRES_USER_TEST": "synthetic"},
        {"POSTGRES_HOST_TEST": "localhost"},
        {"POSTGRES_DB_TEST": ""},
    ],
)
def test_direct_pytest_fixture_rejects_partial_database_inputs(configuration: dict[str, str]) -> None:
    from apps.api.tests.conftest import database_test_url

    with patch.dict(os.environ, configuration, clear=True):
        with pytest.raises(repo.HarnessError, match="Incomplete PostgreSQL test configuration"):
            database_test_url.__wrapped__()


def test_direct_pytest_fixture_uses_canonical_database_precedence(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.tests.conftest import database_test_url

    monkeypatch.setattr(repo, "read_runtime_env", lambda: pytest.fail("explicit input wins"))
    complete = {
        "POSTGRES_USER_TEST": "synthetic/user",
        "POSTGRES_PASSWORD_TEST": "synthetic password",
        "POSTGRES_DB_TEST": "scenario_tests",
        "POSTGRES_PORT_TEST": "5433",
    }
    with patch.dict(os.environ, complete, clear=True):
        resolved = database_test_url.__wrapped__()
        assert resolved.host == "localhost" and resolved.port == 5433
        assert resolved.username == "synthetic/user" and resolved.password == "synthetic password"
        assert resolved.database.endswith("_tests") and resolved.database != "scenario_tests"
        os.environ["TEST_POSTGRES_DATABASE_URL"] = "postgresql+psycopg://localhost/url_wins_tests"
        del os.environ["POSTGRES_PASSWORD_TEST"]
        explicit = database_test_url.__wrapped__()
        assert explicit.database != resolved.database
        assert explicit.database.endswith("_tests") and explicit.database != "url_wins_tests"
        assert explicit.set(database="url_wins_tests").render_as_string() == os.environ["TEST_POSTGRES_DATABASE_URL"]
        os.environ["TEST_POSTGRES_DATABASE_URL"] = "postgresql+psycopg://localhost/production"
        with pytest.raises(ValueError, match="Refusing destructive test operations"):
            database_test_url.__wrapped__()
        del os.environ["TEST_POSTGRES_DATABASE_URL"]
        os.environ["POSTGRES_PASSWORD_TEST"] = "synthetic password"
        os.environ["POSTGRES_DB_TEST"] = "production"
        with pytest.raises(ValueError, match="Refusing destructive test operations"):
            database_test_url.__wrapped__()


def test_direct_pytest_fixture_uses_worktree_runtime_when_no_explicit_input(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.tests.conftest import database_test_url

    monkeypatch.setattr(
        repo,
        "read_runtime_env",
        lambda: {
            "POSTGRES_USER": "synthetic",
            "POSTGRES_PASSWORD": "synthetic",
            "POSTGRES_PORT": "5433",
            "POSTGRES_PORT_TEST": "15433",
            "POSTGRES_DB": "worktree",
        },
    )
    monkeypatch.setattr(repo, "port_is_free", lambda port: False)
    with patch.dict(os.environ, {}, clear=True):
        resolved = database_test_url.__wrapped__()
        assert resolved.database.endswith("_tests") and resolved.database != "worktree_tests"
        assert resolved.host == "127.0.0.1"
        assert resolved.port == 15433
        assert resolved.username == resolved.password == "synthetic"
