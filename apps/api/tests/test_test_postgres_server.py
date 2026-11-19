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


@pytest.mark.parametrize("action", ["up", "stop", "api-postgres"])
def test_foreign_runtime_is_rejected_without_changing_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, action: str
) -> None:
    current, foreign = tmp_path / "current", tmp_path / "foreign"
    config = repo.runtime_config(37, root=foreign)
    runtime_json, runtime_env = tmp_path / "runtime.json", tmp_path / "runtime.env"
    saved_json = json.dumps(asdict(config))
    saved_env = f"POSTGRES_DB={config.database_name}\nPOSTGRES_PORT_TEST={config.test_postgres_port}\n"
    runtime_json.write_text(saved_json, encoding="utf-8")
    runtime_env.write_text(saved_env, encoding="utf-8")
    monkeypatch.setattr(repo, "ROOT", current)
    monkeypatch.setattr(repo, "RUNTIME_JSON", runtime_json)
    monkeypatch.setattr(repo, "RUNTIME_ENV", runtime_env)
    monkeypatch.setattr(repo, "run", lambda *args, **kwargs: pytest.fail("Foreign project must not reach Docker"))
    monkeypatch.setattr(repo, "port_is_free", lambda _: pytest.fail("Foreign port must not be probed"))

    with pytest.raises(repo.HarnessError, match="does not belong to this worktree"):
        if action == "api-postgres":
            repo.api_test_environment(action, {})
        else:
            repo.cmd_test_db(argparse.Namespace(action=action))

    assert runtime_json.read_text(encoding="utf-8") == saved_json
    assert runtime_env.read_text(encoding="utf-8") == saved_env


@pytest.mark.parametrize("action", ["up", "stop"])
@pytest.mark.parametrize("saved_offset", [None, 37])
def test_compose_uses_worktree_settings_without_development_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, action: str, saved_offset: int | None
) -> None:
    runtime_json, runtime_env = tmp_path / "runtime.json", tmp_path / "runtime.env"
    monkeypatch.setattr(repo, "ROOT", tmp_path)
    monkeypatch.setattr(repo, "RUNTIME_JSON", runtime_json)
    monkeypatch.setattr(repo, "RUNTIME_ENV", runtime_env)
    monkeypatch.setattr(repo, "read_dotenv", lambda: pytest.fail("Personal dotenv must not be loaded"))
    monkeypatch.setattr(repo, "tool", lambda name: name)
    config = repo.runtime_config(saved_offset or 0, root=tmp_path)
    if saved_offset is not None:
        runtime_json.write_text(json.dumps(asdict(config)))
        runtime_env.write_text("POSTGRES_PORT_TEST=invalid\n")
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_PORT_TEST"):
        monkeypatch.setenv(name, "parent-value")
    environments = []
    monkeypatch.setattr(repo, "run", lambda command, *, env: environments.append(env))
    repo.cmd_test_db(argparse.Namespace(action=action))

    [env] = environments
    assert env["POSTGRES_PORT_TEST"] == str(config.test_postgres_port)
    assert env["POSTGRES_USER"] != "parent-value" and env["POSTGRES_PASSWORD"] != "parent-value"
    if saved_offset is None:
        assert not runtime_json.exists() and not runtime_env.exists()
    else:
        assert runtime_json.read_text() == json.dumps(asdict(config))
        assert runtime_env.read_text() == "POSTGRES_PORT_TEST=invalid\n"


def test_test_server_identity_and_credentials_are_independent_of_port(tmp_path: Path) -> None:
    first = repo.runtime_config(root=tmp_path / "first")
    second_root = tmp_path / "second"
    second = repo.runtime_config(
        first.test_postgres_port - repo.runtime_config(root=second_root).test_postgres_port, root=second_root
    )
    assert first.test_postgres_port == second.test_postgres_port
    assert first.compose_project != second.compose_project
    for config in (first, second):
        assert config.test_postgres_port not in repo.runtime_ports(config)
    first_env = repo.worktree_test_postgres_environment(first)
    second_env = repo.worktree_test_postgres_environment(second)
    for name in ("POSTGRES_USER", "POSTGRES_PASSWORD"):
        assert first_env[name] != second_env[name]


def test_missing_runtime_json_preserves_existing_development_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    runtime_json, runtime_env = tmp_path / "runtime.json", tmp_path / "runtime.env"
    runtime_env.write_text("POSTGRES_PORT_TEST=42037\n")
    monkeypatch.setattr(repo, "RUNTIME_JSON", runtime_json)
    monkeypatch.setattr(repo, "RUNTIME_ENV", runtime_env)
    monkeypatch.setattr(repo, "run", lambda *args, **kwargs: pytest.fail("Missing saved offset must stop launch"))
    with pytest.raises(repo.HarnessError, match="runtime.json"):
        repo.api_test_environment("api-postgres", {})
    assert runtime_env.read_text() == "POSTGRES_PORT_TEST=42037\n"
    assert not runtime_json.exists()


@pytest.mark.parametrize(
    "content,reason",
    [
        ('{"worktree_id":', "line 1"),
        ("[]", "expected runtime settings"),
        ({"postgres_port": "32000"}, "'postgres_port' must be int"),
        ({"api_port": True}, "'api_port' must be int"),
        ({"compose_project": None}, "'compose_project' must be str"),
        ({"postgres_port": 60000}, "expected 1–65535"),
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
    monkeypatch.setattr(repo, "ROOT", tmp_path)
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


@pytest.mark.parametrize("mapping", ["", "127.0.0.1:1\n", "0.0.0.0:{port}\n"])
def test_another_listener_cannot_replace_the_worktree_server(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mapping: str
) -> None:
    config = repo.runtime_config(root=tmp_path)
    monkeypatch.setattr(repo, "ROOT", tmp_path)
    monkeypatch.setattr(repo, "load_runtime", lambda *, initialize: config)
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
