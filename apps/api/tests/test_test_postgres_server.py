from __future__ import annotations

import argparse
import json
import os
from dataclasses import asdict
from pathlib import Path

import pytest

import scripts.repo as repo


def test_test_db_uses_written_runtime_values_over_parent_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(repo, "HARNESS_DIR", tmp_path)
    monkeypatch.setattr(repo, "RUNTIME_JSON", tmp_path / "runtime.json")
    monkeypatch.setattr(repo, "RUNTIME_ENV", tmp_path / "runtime.env")
    monkeypatch.setattr(repo, "read_dotenv", dict)
    monkeypatch.setattr(repo, "tool", lambda name: name)
    config = repo.runtime_config(root=tmp_path)
    monkeypatch.setattr(repo, "load_runtime", lambda: config)
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_PORT_TEST"):
        monkeypatch.setenv(name, "parent-value")
    captured: list[dict[str, str]] = []

    def capture_run(command: list[str], *, env: dict[str, str] | None = None) -> None:
        captured.append(dict(os.environ if env is None else env))

    monkeypatch.setattr(repo, "run", capture_run)
    repo.cmd_test_db(argparse.Namespace(action="up"))
    runtime = repo.read_runtime_env()
    assert len(captured) == 1
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_PORT_TEST"):
        assert captured[0][name] == runtime[name] != "parent-value"


def test_test_server_identity_is_worktree_scoped_and_separate_from_development(tmp_path: Path) -> None:
    first = repo.runtime_config(root=tmp_path / "first")
    second = next(
        candidate
        for i in range(100)
        if (candidate := repo.runtime_config(root=tmp_path / f"second-{i}")).postgres_port != first.postgres_port
    )
    assert first.compose_project != second.compose_project
    assert first.postgres_test_port != second.postgres_test_port
    assert first.postgres_test_port == repo.runtime_config(root=tmp_path / "first").postgres_test_port
    for config in (first, second):
        assert config.postgres_test_port not in repo.runtime_ports(config)
    assert repo.runtime_config(7, root=tmp_path / "first").postgres_test_port == first.postgres_test_port + 7


def test_old_runtime_json_still_loads_and_writes_dedicated_test_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(repo, "HARNESS_DIR", tmp_path)
    monkeypatch.setattr(repo, "RUNTIME_JSON", tmp_path / "runtime.json")
    monkeypatch.setattr(repo, "RUNTIME_ENV", tmp_path / "runtime.env")
    monkeypatch.setattr(repo, "read_dotenv", dict)
    config = repo.runtime_config(root=tmp_path)
    repo.RUNTIME_JSON.write_text(json.dumps(asdict(config)), encoding="utf-8")

    loaded = repo.load_runtime()
    assert loaded == config
    repo.write_runtime(loaded)
    environment = repo.read_runtime_env()
    assert environment["POSTGRES_PORT_TEST"] == str(config.postgres_test_port)
    assert environment["POSTGRES_PORT"] == str(config.postgres_port)
    assert environment["DATABASE_URL"].endswith(f"@postgres:5432/{config.database_name}")


@pytest.mark.parametrize("test_port", [None, ""])
def test_stale_runtime_refuses_development_port_and_explains_recovery(
    monkeypatch: pytest.MonkeyPatch, test_port: str | None
) -> None:
    runtime = {
        "POSTGRES_DB": "payments_worktree",
        "POSTGRES_USER": "test-user",
        "POSTGRES_PASSWORD": "synthetic-password",
        "POSTGRES_PORT": "32053",
    }
    if test_port is not None:
        runtime["POSTGRES_PORT_TEST"] = test_port
    monkeypatch.setattr(repo, "read_runtime_env", lambda: runtime)
    monkeypatch.setattr(repo, "port_is_free", lambda _: pytest.fail("Do not probe the development server"))

    with pytest.raises(repo.HarnessError, match=r"(?s)POSTGRES_PORT_TEST.*python scripts/repo.py test-db up"):
        repo.api_test_environment("api-postgres", {})


def test_stopped_test_server_explains_recovery_even_with_development_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        repo,
        "read_runtime_env",
        lambda: {
            "POSTGRES_DB": "payments_worktree",
            "POSTGRES_USER": "test-user",
            "POSTGRES_PASSWORD": "synthetic-password",
            "POSTGRES_PORT": "32053",
            "POSTGRES_PORT_TEST": "42053",
        },
    )
    monkeypatch.setattr(repo, "port_is_free", lambda port: port == 42053)

    with pytest.raises(repo.HarnessError, match=r"(?s)not running.*python scripts/repo.py test-db up"):
        repo.api_test_environment("api-postgres", {})
