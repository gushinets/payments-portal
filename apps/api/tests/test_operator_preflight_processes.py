"""Independent CLI processes, real local HTTP, and the shared Unix flock."""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

from app.core.errors import AppError
from app.infrastructure.operator_preflight import operator_preflight_lock
from apps.api.tests.support.operator_processes import OperatorProcesses, processes as processes


pytestmark = pytest.mark.skipif(os.name != "posix", reason="Operator flock requires Unix")


@pytest.mark.parametrize("contender", ["dry-run", "publish"])
def test_independent_cli_is_saturated_before_http_then_succeeds_after_release(
    processes: OperatorProcesses, contender: str
) -> None:
    first = processes.start("dry-run")
    assert processes.entered.wait(10), "first CLI never reached Kernel"
    path = processes.directory / "operator.lock"
    inode = path.stat().st_ino
    before = list(processes.requests)
    second = processes.run(contender)
    assert second.returncode == 1
    assert json.loads(second.stderr) == {"detail": {"code": "preflight_saturated"}}
    assert processes.requests == before
    processes.release.set()
    output, error = first.communicate(timeout=15)
    assert first.returncode == 0, error
    assert json.loads(output)["persisted"] is False
    retry = processes.run("dry-run")
    assert retry.returncode == 0, retry.stderr
    assert json.loads(retry.stdout)["persisted"] is False
    assert path.stat().st_ino == inode
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len([path for path in processes.requests if path.startswith("/internal/")]) == 2
    assert len([path for path in processes.requests if path.endswith("/auth")]) == 2


def test_killed_cli_owner_releases_lock_without_unlinking_file(processes: OperatorProcesses) -> None:
    first = processes.start("dry-run")
    assert processes.entered.wait(10)
    path = processes.directory / "operator.lock"
    inode = path.stat().st_ino
    first.kill()
    first.communicate(timeout=5)
    assert first.returncode != 0
    processes.release.set()
    next_process = processes.run("dry-run")
    assert next_process.returncode == 0, next_process.stderr
    assert path.stat().st_ino == inode


@pytest.mark.parametrize("invalid", ["missing", "relative", "absent_parent", "directory", "symlink", "public"])
@pytest.mark.parametrize("command", ["dry-run", "publish"])
def test_bad_lock_path_never_reaches_source_http(processes: OperatorProcesses, invalid: str, command: str) -> None:
    path = processes.directory / "operator.lock"
    if invalid == "missing":
        configured = ""
    elif invalid == "relative":
        configured = "operator.lock"
    elif invalid == "absent_parent":
        configured = str(processes.directory / "absent" / "operator.lock")
    elif invalid == "directory":
        configured = str(processes.directory)
    elif invalid == "symlink":
        target = processes.directory / "other.lock"
        target.touch(mode=0o600)
        path.symlink_to(target)
        configured = str(path)
    else:
        path.touch(mode=0o666)
        path.chmod(0o666)
        configured = str(path)
    result = processes.run(command, MAPPING_OPERATOR_LOCK_FILE=configured)
    assert result.returncode == 1
    assert json.loads(result.stderr) == {"detail": {"code": "mapping_operator_lock_unavailable"}}
    assert processes.requests == []


def test_authorization_and_input_validation_precede_lock(processes: OperatorProcesses) -> None:
    denied = processes.run("dry-run", MAPPING_OPERATOR_UIDS="[]")
    assert json.loads(denied.stderr) == {"detail": {"code": "mapping_operator_forbidden"}}
    (processes.directory / "proposal.json").write_text("{}", encoding="utf-8")
    invalid = processes.run("dry-run")
    assert json.loads(invalid.stderr) == {"detail": {"code": "mapping_input_invalid"}}
    assert not (processes.directory / "operator.lock").exists()
    assert processes.requests == []


def test_flock_errors_and_unsupported_import_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import fcntl

    def unavailable(*args: object) -> None:
        raise OSError("SIMULATED flock failure")

    monkeypatch.setattr(fcntl, "flock", unavailable)
    with pytest.raises(AppError, match="mapping_operator_lock_unavailable"):
        with operator_preflight_lock(tmp_path / "operator.lock"):
            pytest.fail("failed flock allowed source work")
    monkeypatch.setitem(sys.modules, "fcntl", None)
    with pytest.raises(AppError, match="mapping_operator_lock_unavailable"):
        with operator_preflight_lock(tmp_path / "operator.lock"):
            pytest.fail("unsupported platform allowed source work")
