from __future__ import annotations

import os
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.errors import AppError
from app.core.settings import AppEnv
from apps.api.tests.support.commercial_mappings import SIMULATED_UID, operator_settings
from apps.api.tests.support.kernel_walkthrough import require_development_operator
from scripts import repo


def test_opt_in_uses_same_worktree_project_and_adds_only_its_own_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo, "read_dotenv", lambda: {})
    monkeypatch.setattr(repo, "tool", lambda name: name)
    monkeypatch.setenv("KERNEL_MOCK_ENABLED", "0")
    configuration = repo.runtime_config()
    ordinary = repo.compose_command(configuration)
    ports = tuple(repo.runtime_ports(configuration))
    assert not any("kernel-mock" in argument for argument in ordinary)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("KERNEL_MOCK_ENABLED", "1")
    assert repo.compose_command(configuration) == [
        *ordinary,
        "-f",
        str(repo.ROOT / "docker-compose.kernel-mock.dev.yml"),
    ]
    assert tuple(repo.runtime_ports(configuration)) == (*ports, configuration.kernel_mock_port)
    assert configuration.kernel_mock_port not in ports
    assert repo.runtime_config(1).kernel_mock_port == configuration.kernel_mock_port + 1


@pytest.mark.parametrize("environment", ["production", "test"])
def test_opt_in_refuses_non_development_harness(monkeypatch: pytest.MonkeyPatch, environment: str) -> None:
    monkeypatch.setattr(repo, "read_dotenv", lambda: {})
    monkeypatch.setenv("KERNEL_MOCK_ENABLED", "1")
    monkeypatch.setenv("APP_ENV", environment)
    with pytest.raises(repo.HarnessError, match="development"):
        repo.compose_command(repo.runtime_config())


def test_opt_in_injects_container_source_settings_without_printing_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(repo, "HARNESS_DIR", tmp_path)
    monkeypatch.setattr(repo, "RUNTIME_ENV", tmp_path / "runtime.env")
    monkeypatch.setattr(repo, "RUNTIME_JSON", tmp_path / "runtime.json")
    monkeypatch.setattr(repo, "read_dotenv", lambda: {})
    monkeypatch.setenv("KERNEL_MOCK_ENABLED", "1")
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("KERNEL_SERVICE_TOKEN", "explicit-simulated-service-token")
    monkeypatch.setenv("KERNEL_MOCK_TOKEN", "explicit-simulated-service-token")
    monkeypatch.setenv("MAPPING_OPERATOR_UIDS", "[0]")
    repo.write_runtime(repo.runtime_config())
    written = repo.read_runtime_env()
    assert written["KERNEL_SERVICE_TOKEN"] == written["KERNEL_MOCK_TOKEN"] == "explicit-simulated-service-token"
    assert written["MAPPING_OPERATOR_UIDS"] == "[0]"
    assert written["KERNEL_MOCK_PORT"] == str(repo.runtime_config().kernel_mock_port)
    output = capsys.readouterr()
    assert not output.out and not output.err
    monkeypatch.setenv("KERNEL_MOCK_ENABLED", "0")
    repo.write_runtime(repo.runtime_config())
    written = repo.read_runtime_env()
    assert written["KERNEL_SERVICE_TOKEN"] == "explicit-simulated-service-token"
    assert "KERNEL_MOCK_ENABLED" not in written
    assert "KERNEL_MOCK_TOKEN" not in written
    assert "KERNEL_MOCK_SCENARIO" not in written
    assert "KERNEL_MOCK_DELAY_SECONDS" not in written


@pytest.mark.parametrize(
    "selection",
    [
        {"KERNEL_MOCK_ENABLED": "1"},
        {"KERNEL_MOCK_TOKEN": "test-only"},
        {"COMPOSE_PROFILES": "kernel-mock"},
        {"COMPOSE_FILE": "docker-compose.prod.yml:docker-compose.kernel-mock.dev.yml"},
    ],
)
def test_production_deployment_refuses_mock_inputs(selection: dict[str, str]) -> None:
    with pytest.raises(repo.HarnessError, match="Kernel mock"):
        repo.validate_production_deployment_environment(environ={"CADDY_DOMAIN": "portal.example.com", **selection})


@pytest.mark.parametrize("url", ["http://kernel-mock:8091", "https://kernel-mock.example.com"])
def test_production_settings_cannot_select_mock_even_with_https(url: str) -> None:
    with pytest.raises(ValidationError):
        operator_settings(
            app_env=AppEnv.PRODUCTION,
            app_public_base_url="https://portal.example.com",
            cors_allow_origins=("https://portal.example.com",),
            kernel_base_url=url,
        )


@pytest.mark.parametrize(
    ("changes", "code"),
    [
        ({"app_env": AppEnv.TEST}, "kernel_walkthrough_development_only"),
        ({"mapping_operator_uids": ()}, "mapping_operator_forbidden"),
        ({"postgres_db": "postgres"}, "kernel_walkthrough_worktree_database_required"),
        ({"database_url": "sqlite+pysqlite:///:memory:"}, "kernel_walkthrough_worktree_database_required"),
        ({"mapping_account_id": "another-account"}, "kernel_walkthrough_simulated_account_required"),
    ],
)
def test_walkthrough_guard_precedes_any_source_or_db(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, object], code: str
) -> None:
    monkeypatch.setattr(os, "geteuid", lambda: SIMULATED_UID, raising=False)
    configuration = operator_settings(
        **{
            "app_env": AppEnv.DEVELOPMENT,
            "postgres_db": "payments_12345678",
            "database_url": "postgresql+psycopg://unused@localhost/payments_12345678",
            **changes,
        }
    )
    with pytest.raises(AppError, match=code):
        require_development_operator(configuration)
