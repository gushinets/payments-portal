from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
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
    assert captured[0]["POSTGRES_PORT_TEST"] == runtime["POSTGRES_PORT_TEST"] != "parent-value"
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD"):
        assert captured[0][name] not in {runtime[name], "parent-value"}


def test_test_server_identity_is_worktree_scoped_and_separate_from_development(tmp_path: Path) -> None:
    first = repo.runtime_config(root=tmp_path / "first")
    second = next(
        candidate
        for i in range(100)
        if (candidate := repo.runtime_config(root=tmp_path / f"second-{i}")).postgres_port != first.postgres_port
    )
    assert first.compose_project != second.compose_project
    assert first.test_postgres_port != second.test_postgres_port
    assert first.test_postgres_port == repo.runtime_config(root=tmp_path / "first").test_postgres_port
    for config in (first, second):
        assert config.test_postgres_port not in repo.runtime_ports(config)
    assert repo.runtime_config(7, root=tmp_path / "first").test_postgres_port == first.test_postgres_port + 7


def test_test_server_credentials_distinguish_worktrees_with_the_same_port(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(repo, "HARNESS_DIR", tmp_path)
    monkeypatch.setattr(repo, "RUNTIME_JSON", tmp_path / "runtime.json")
    monkeypatch.setattr(repo, "RUNTIME_ENV", tmp_path / "runtime.env")
    monkeypatch.setattr(repo, "read_dotenv", dict)
    monkeypatch.setattr(repo, "tool", lambda name: name)
    first = repo.runtime_config(root=tmp_path / "first")
    second_root = tmp_path / "second"
    offset = first.test_postgres_port - repo.runtime_config(root=second_root).test_postgres_port
    second = repo.runtime_config(offset, root=second_root)
    assert first.test_postgres_port == second.test_postgres_port
    captured: list[dict[str, str]] = []
    monkeypatch.setattr(repo, "run", lambda command, *, env: captured.append(env))
    for config in (first, second):
        monkeypatch.setattr(repo, "load_runtime", lambda: config)
        repo.cmd_test_db(argparse.Namespace(action="up"))
        development = repo.read_runtime_env()
        for name in ("POSTGRES_USER", "POSTGRES_PASSWORD"):
            assert captured[-1][name] != development[name]
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD"):
        assert captured[0][name] != captured[1][name]


@pytest.mark.parametrize("missing", ["runtime.env", "runtime.json"])
def test_test_startup_preserves_existing_runtime_when_a_file_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    runtime_json, runtime_env = tmp_path / "runtime.json", tmp_path / "runtime.env"
    monkeypatch.setattr(repo, "HARNESS_DIR", tmp_path)
    monkeypatch.setattr(repo, "RUNTIME_JSON", runtime_json)
    monkeypatch.setattr(repo, "RUNTIME_ENV", runtime_env)
    monkeypatch.setattr(repo, "read_dotenv", dict)
    config = repo.runtime_config(37, root=tmp_path)
    repo.write_runtime(config)
    missing_file = tmp_path / missing
    existing_file = runtime_json if missing_file == runtime_env else runtime_env
    original = existing_file.read_bytes()
    missing_file.unlink()
    monkeypatch.setattr(repo, "port_is_free", lambda port: False)
    monkeypatch.setattr(repo, "tool", lambda name: name)
    monkeypatch.setattr(
        repo,
        "run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 0, stdout=f"127.0.0.1:{config.test_postgres_port}"
        ),
    )
    dotenv_reads: list[bool] = []
    monkeypatch.setattr(repo, "read_dotenv", lambda: dotenv_reads.append(True) or {"SMTP_HOST": "synthetic.test"})

    with pytest.raises(repo.HarnessError, match=rf"(?s){missing}.*python scripts/repo.py test-db up"):
        repo.api_test_environment("api-postgres", {})

    assert existing_file.read_bytes() == original
    assert not missing_file.exists()
    assert not dotenv_reads


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
    assert environment["POSTGRES_PORT_TEST"] == str(config.test_postgres_port)
    assert environment["POSTGRES_PORT"] == str(config.postgres_port)
    assert environment["DATABASE_URL"].endswith(f"@postgres:5432/{config.database_name}")


@pytest.mark.parametrize(
    "content,reason",
    [
        ('{"worktree_id":', "line 1"),
        ("[]", "expected runtime settings"),
        ({"postgres_port": "32000"}, "'postgres_port' must be int"),
        ({"api_port": True}, "'api_port' must be int"),
        ({"compose_project": None}, "'compose_project' must be str"),
    ],
)
def test_cli_reports_invalid_runtime_json_without_changing_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    content: str | dict[str, object],
    reason: str,
) -> None:
    runtime_json, runtime_env = tmp_path / "runtime.json", tmp_path / "runtime.env"
    report = tmp_path / "current.xml"
    config = repo.runtime_config(37, root=tmp_path)
    if isinstance(content, dict):
        content = json.dumps({**asdict(config), **content})
    runtime_json.write_text(content, encoding="utf-8")
    runtime_env.write_text(f"POSTGRES_DB=synthetic\nPOSTGRES_PORT_TEST={config.test_postgres_port}\n", encoding="utf-8")
    monkeypatch.setattr(repo, "RUNTIME_JSON", runtime_json)
    monkeypatch.setattr(repo, "RUNTIME_ENV", runtime_env)
    monkeypatch.setattr(repo, "REPOSITORY_VENV", tmp_path / "nonexistent")
    monkeypatch.setattr(repo, "canonical_check_environment", dict)
    monkeypatch.setattr(repo, "port_is_free", lambda _: pytest.fail("Must not probe an invalid runtime"))
    monkeypatch.setattr(repo, "write_runtime", lambda _: pytest.fail("Invalid runtime must stay intact"))
    monkeypatch.setattr(repo, "run", lambda *args, **kwargs: pytest.fail("Must not start a subprocess"))

    for arguments in (["test", "api-postgres", "--junitxml", str(report)], ["test-db", "up"]):
        monkeypatch.setattr(sys, "argv", ["repo.py", *arguments])
        assert repo.main() == 1
        error = capsys.readouterr().err
        assert str(runtime_json) in error and reason in error
        assert "docs/engineering/TESTING.md" in error

    junit_error = ET.parse(report).find(".//error")
    assert junit_error is not None
    assert str(runtime_json) in junit_error.attrib["message"] and reason in junit_error.attrib["message"]
    assert runtime_json.read_text(encoding="utf-8") == content


def test_write_runtime_keeps_existing_json_if_atomic_replace_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_json = tmp_path / "runtime.json"
    monkeypatch.setattr(repo, "HARNESS_DIR", tmp_path)
    monkeypatch.setattr(repo, "RUNTIME_JSON", runtime_json)
    monkeypatch.setattr(repo, "RUNTIME_ENV", tmp_path / "runtime.env")
    monkeypatch.setattr(repo, "read_dotenv", dict)
    previous = repo.runtime_config(root=tmp_path)
    updated = repo.runtime_config(1, root=tmp_path)
    repo.write_runtime(previous)
    real_replace = os.replace

    def fail_json_replace(source: Path, destination: Path) -> None:
        if destination == runtime_json:
            assert repo.load_runtime() == previous
            assert json.loads(source.read_text(encoding="utf-8")) == asdict(updated)
            raise OSError("simulated JSON replace failure")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_json_replace)
    with pytest.raises(OSError, match="simulated JSON replace failure"):
        repo.write_runtime(updated)

    assert repo.load_runtime() == previous
    assert not list(tmp_path.glob(".runtime.json.*.tmp"))


@pytest.mark.parametrize("test_port", [None, "", "not-a-port", "-1", "0", "65536"])
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
    monkeypatch.setattr(repo, "read_runtime_env", lambda *, initialize: runtime)
    monkeypatch.setattr(repo, "port_is_free", lambda _: pytest.fail("Do not probe an invalid test port"))

    with pytest.raises(repo.HarnessError, match=r"(?s)POSTGRES_PORT_TEST.*python scripts/repo.py test-db up"):
        repo.api_test_environment("api-postgres", {})


def test_stopped_test_server_explains_recovery_even_with_development_running(monkeypatch: pytest.MonkeyPatch) -> None:
    config = repo.runtime_config()
    monkeypatch.setattr(repo, "load_runtime", lambda *, initialize: config)
    monkeypatch.setattr(
        repo,
        "read_runtime_env",
        lambda *, initialize: {
            "POSTGRES_DB": "payments_worktree",
            "POSTGRES_USER": "test-user",
            "POSTGRES_PASSWORD": "synthetic-password",
            "POSTGRES_PORT": "32053",
            "POSTGRES_PORT_TEST": str(config.test_postgres_port),
        },
    )
    monkeypatch.setattr(repo, "port_is_free", lambda port: port == config.test_postgres_port)

    with pytest.raises(repo.HarnessError, match=r"(?s)not running.*python scripts/repo.py test-db up"):
        repo.api_test_environment("api-postgres", {})


@pytest.mark.parametrize("mapping", ["", "127.0.0.1:1\n", "0.0.0.0:{port}\n"])
def test_another_listener_cannot_replace_the_worktree_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mapping: str
) -> None:
    config = repo.runtime_config(root=tmp_path)
    monkeypatch.setattr(repo, "load_runtime", lambda *, initialize: config)
    monkeypatch.setattr(
        repo,
        "read_runtime_env",
        lambda *, initialize: {
            "POSTGRES_DB": "payments_worktree",
            "POSTGRES_USER": "test-user",
            "POSTGRES_PASSWORD": "synthetic-password",
            "POSTGRES_PORT_TEST": str(config.test_postgres_port),
        },
    )
    monkeypatch.setattr(repo, "port_is_free", lambda port: False)
    monkeypatch.setattr(repo, "tool", lambda name: name)

    def compose_port(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[:4] == ["docker", "compose", "--project-name", f"{config.compose_project}-tests"]
        assert command[-3:] == ["port", "postgres", "5432"]
        return subprocess.CompletedProcess(
            command, 0 if mapping else 1, stdout=mapping.format(port=config.test_postgres_port)
        )

    monkeypatch.setattr(repo, "run", compose_port)
    with pytest.raises(repo.HarnessError, match=r"(?s)worktree.*python scripts/repo.py test-db up"):
        repo.api_test_environment("api-postgres", {})
