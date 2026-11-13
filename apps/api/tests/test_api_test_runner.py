"""Runner contracts using small real subprocess suites, without PostgreSQL."""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts import api_test_runner as runner, repo


@pytest.fixture
def suite(tmp_path: Path) -> Path:
    (tmp_path / "apps/api/tests").mkdir(parents=True)
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    postgres: database partition\n", encoding="utf-8")
    return tmp_path


def source(root: Path, name: str, text: str) -> Path:
    path = root / "apps/api/tests" / name
    path.write_text(text, encoding="utf-8")
    return path


def environment() -> dict[str, str]:
    return {**os.environ, "PYTHONPATH": str(repo.ROOT), "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}


def run_suite(root: Path, *, target: str = "api-postgres", workers: int = 4) -> runner.RunnerResult:
    return runner.run_api_tests(
        root=root,
        artifacts=root / "reports",
        target=target,
        workers=workers,
        environment=environment(),
        junitxml=root / "current.xml",
    )


def report_nodes(path: Path) -> list[str]:
    return [prop.attrib["value"] for prop in ET.parse(path).findall(".//testcase/properties/property[@name='nodeid']")]


def test_greedy_partition_keeps_modules_complete_and_case_order() -> None:
    nodes = [
        f"apps/api/tests/test_{module}.py::test_case[{i}]"
        for module, size in [("a", 2), ("b", 5), ("c", 3), ("d", 1)]
        for i in range(size)
    ]
    assert runner.partition_modules(nodes, 2) == [nodes[2:7] + nodes[10:], nodes[:2] + nodes[7:10]]
    groups = runner.partition_modules(nodes, 4)
    assert sorted(node for group in groups for node in group) == sorted(nodes)
    assert runner.partition_modules([], 4) == []
    assert runner.partition_modules(nodes, 1) == [nodes]


@pytest.mark.parametrize(
    "arguments",
    [
        ["-m", "postgres or slow"],
        ["-m", "not postgres"],
        ["--cov=apps/api/app"],
        ["-n", "4"],
        ["--junitxml=old.xml"],
        ["@old.txt"],
        ["../outside.py"],
        ["-k"],
        ["--durations=no"],
        ["--rootdir=/tmp"],
    ],
)
def test_rejects_unsafe_or_incompatible_arguments(suite: Path, arguments: list[str]) -> None:
    with pytest.raises(runner.RunnerError):
        runner.validate_arguments(arguments, "api-postgres", suite)


def test_selector_and_marker_validation_preserves_spaces_and_metacharacters(suite: Path) -> None:
    path = source(suite, "test_space.py", "")
    args = runner.validate_arguments(
        [str(path) + "::test_case[x $() ; ]", "-m", "postgres", "-k", "case", "--durations=3"], "api-postgres", suite
    )
    assert args == runner.PytestArguments(
        ["-k", "case", "--durations=3"], ["apps/api/tests/test_space.py::test_case[x $() ; ]"]
    )
    assert runner.validate_arguments(["-m", "not postgres"], "api-fast", suite).options == []
    with pytest.raises(runner.RunnerError):
        runner.validate_arguments(["-m", "postgres"], "api", suite)


def test_one_and_four_workers_have_identical_collections_and_skip_reports(suite: Path) -> None:
    for module in range(4):
        source(
            suite,
            f"test_{module}.py",
            """import pytest
pytestmark = pytest.mark.postgres
@pytest.mark.parametrize("case", ["literal spaces ; $()", "second"])
def test_value(case):
    assert case
@pytest.mark.skip(reason="intentional sample skip")
def test_skip():
    pass
""",
        )
    serial = run_suite(suite, workers=1)
    parallel = run_suite(suite)
    assert serial.returncode == parallel.returncode == 0
    assert serial.directory != parallel.directory
    assert sorted(report_nodes(serial.directory / "junit.xml")) == sorted(
        report_nodes(parallel.directory / "junit.xml")
    )
    xml = ET.parse(parallel.directory / "junit.xml").getroot()
    assert xml.attrib["tests"] == "12" and xml.attrib["skipped"] == "4"
    for result, count in ((serial, 1), (parallel, 4)):
        assert len(list(result.directory.glob("postgres/worker-*/manifest.json"))) == count
        assert len(list(result.directory.glob("postgres/worker-*/pytest.log"))) == count


def test_mixed_dispatcher_runs_postgres_after_failed_fast_partition(suite: Path) -> None:
    source(
        suite,
        "test_mixed.py",
        """import pytest
def test_fast_failure():
    assert False, "deliberate fast failure"
@pytest.mark.postgres
def test_postgres_pass():
    assert True
""",
    )
    result = run_suite(suite, target="api")
    assert result.returncode == 1
    xml = ET.parse(suite / "current.xml")
    assert len(xml.findall(".//failure")) == 1
    assert xml.getroot().attrib["tests"] == "2"  # A test failure is not an extra infrastructure case.
    assert any(node.endswith("test_postgres_pass") for node in report_nodes(suite / "current.xml"))
    assert (result.directory / "fast/worker-1/manifest.json").is_file()
    assert (result.directory / "postgres/worker-1/manifest.json").is_file()


def test_collection_failure_replaces_previous_report_and_still_runs_other_partition(suite: Path) -> None:
    source(suite, "test_broken.py", "raise RuntimeError('collection defect')")
    (suite / "current.xml").write_text('<testsuites tests="999"/>')
    result = run_suite(suite, target="api")
    assert result.returncode == 1
    assert ET.parse(suite / "current.xml").findall(".//error")
    assert (result.directory / "fast/collection/pytest.log").is_file()
    assert (result.directory / "postgres/collection/pytest.log").is_file()
    assert "999" not in (suite / "current.xml").read_text()


@pytest.mark.parametrize(
    "defect", ["crash", "manifest-missing", "manifest-mismatch", "junit-missing", "junit-mismatch"]
)
def test_worker_protocol_defects_fail_without_losing_other_worker_reports(suite: Path, defect: str) -> None:
    body = "import os; os._exit(7)" if defect == "crash" else "assert True"
    source(
        suite, "test_broken.py", f"import pytest\npytestmark = pytest.mark.postgres\ndef test_worker():\n    {body}\n"
    )
    source(
        suite, "test_good.py", "import pytest\npytestmark = pytest.mark.postgres\ndef test_good():\n    assert True\n"
    )
    if defect != "crash":
        source(
            suite,
            "conftest.py",
            f"""from pathlib import Path
import json

def pytest_unconfigure(config):
    if config.option.collectonly:
        return
    manifest = Path(config.getoption("--runner-manifest"))
    value = json.loads(manifest.read_text())
    if not any("test_broken.py" in node for node in value["nodeids"]):
        return
    defect = {defect!r}
    if defect == "manifest-missing":
        manifest.unlink()
    elif defect == "manifest-mismatch":
        value["nodeids"] = ["apps/api/tests/test_broken.py::wrong"]
        manifest.write_text(json.dumps(value))
    elif defect == "junit-missing":
        Path(config.option.xmlpath).unlink()
    else:
        xml = Path(config.option.xmlpath)
        xml.write_text(xml.read_text().replace("::test_worker", "::wrong"))
""",
        )
    result = run_suite(suite)
    assert result.returncode == 1
    assert ET.parse(suite / "current.xml").findall(".//error")
    assert any(node.endswith("::test_good") for node in report_nodes(suite / "current.xml"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal integration; Windows uses CTRL_BREAK_EVENT")
def test_interruption_joins_workers_and_allows_fixture_cleanup(suite: Path) -> None:
    source(
        suite,
        "test_wait.py",
        """import time
from pathlib import Path
import pytest
pytestmark = pytest.mark.postgres
@pytest.fixture
def resource():
    yield
    Path("cleaned").write_text("cleaned")
def test_wait(resource):
    Path("ready").write_text("ready")
    time.sleep(30)
""",
    )
    script = f"""from pathlib import Path
from scripts.api_test_runner import run_api_tests
import os
root = Path({str(suite)!r})
result = run_api_tests(root=root, artifacts=root / "reports", target="api-postgres", workers=1, environment=dict(os.environ), junitxml=root / "current.xml")
raise SystemExit(result.returncode)
"""
    (suite / "current.xml").write_text('<testsuites tests="999"/>')
    with (suite / "parent.log").open("wb") as log:
        process = subprocess.Popen(
            [sys.executable, "-c", script], env=environment(), stdout=log, stderr=subprocess.STDOUT
        )
        try:
            deadline = time.monotonic() + 15
            while not (suite / "ready").exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.05)
            assert (suite / "ready").exists(), (suite / "parent.log").read_text()
            pending_error = bool(ET.parse(suite / "current.xml").findall(".//error"))
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=25) == 130
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    assert (suite / "cleaned").read_text() == "cleaned"
    assert pending_error, "The previous success must be invalidated before starting children"
    result_path = next((suite / "reports").glob("*/result.json"))
    assert json.loads(result_path.read_text())["returncode"] == 130
    interruption = next((suite / "reports").glob("*/postgres/worker-*/interrupted.json"))
    assert json.loads(interruption.read_text()) == {"forced_termination": False}
    assert ET.parse(suite / "current.xml").findall(".//error")


@pytest.mark.parametrize("target,workers", [("api-fast", None), ("api-postgres", None), ("api", 1)])
def test_command_defaults_and_aliases_dispatch_to_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, target: str, workers: int | None
) -> None:
    captured: list[dict[str, object]] = []

    def capture(**kwargs: object) -> runner.RunnerResult:
        captured.append(kwargs)
        return runner.RunnerResult(0, tmp_path)

    monkeypatch.setattr(runner, "run_api_tests", capture)
    monkeypatch.setattr(repo, "api_test_environment", lambda target, env: env)
    repo.cmd_test(argparse.Namespace(target=target, workers=workers, junitxml=None), environment={"SAFE": "value"})
    assert captured[0]["workers"] == (workers or (1 if target == "api-fast" else 4))
    assert captured[0]["environment"] == {"SAFE": "value"}
    scripts = json.loads((repo.ROOT / "package.json").read_text())["scripts"]
    assert scripts[
        {"api": "test:api", "api-fast": "test:api:fast", "api-postgres": "test:api:postgres"}[target]
    ].endswith("test " + target)


def test_fast_command_rejects_parallel_setting_before_resolving_database(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(repo, "api_test_environment", lambda *args: pytest.fail("Must reject workers first"))
    with pytest.raises(repo.HarnessError, match="api-fast"):
        repo.cmd_test(argparse.Namespace(target="api-fast", workers=2, junitxml=None))


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"exit_code": True, "nodeids": []},
        {"exit_code": 0, "nodeids": [3]},
        {"exit_code": 0, "nodeids": ["a::b", "a::b"]},
        {"exit_code": 2, "nodeids": []},
    ],
)
def test_manifest_decoder_rejects_invalid_protocol(tmp_path: Path, value: object) -> None:
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(value))
    with pytest.raises(runner.RunnerError):
        runner.read_manifest(path, 0)


@pytest.mark.skipif(os.name == "nt", reason="POSIX signal escalation")
def test_hard_termination_is_reported_and_process_is_joined(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(runner, "CLEANUP_GRACE_SECONDS", 0.1)
    monkeypatch.setattr(runner, "TERMINATE_GRACE_SECONDS", 0.1)
    ready = tmp_path / "ready"
    command = [
        sys.executable,
        "-c",
        "import signal, time; from pathlib import Path; signal.signal(signal.SIGINT, signal.SIG_IGN); signal.signal(signal.SIGTERM, signal.SIG_IGN); Path("
        + repr(str(ready))
        + ").touch(); time.sleep(30)",
    ]
    process = subprocess.Popen(command, start_new_session=True)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists()
        assert runner.stop_processes([process]) is True
        assert process.poll() == -signal.SIGKILL
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_test_launcher_replaces_venv_shim_so_signals_reach_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    venv = tmp_path / "venv"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(repo, "REPOSITORY_VENV", venv)
    monkeypatch.setattr(sys, "argv", ["repo.py", "test", "api-postgres"])
    calls: list[tuple[str, list[str]]] = []
    directories: list[Path] = []
    monkeypatch.setattr(os, "chdir", directories.append)

    def replace(path: str, arguments: list[str]) -> None:
        calls.append((path, arguments))
        raise SystemExit(0)

    monkeypatch.setattr(os, "execv", replace)
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: pytest.fail("A waiting shim would swallow SIGTERM"))
    with pytest.raises(SystemExit) as caught:
        repo.reexec_in_repository_venv_if_required()
    assert caught.value.code == 0
    assert directories == [repo.ROOT]
    assert calls == [
        (
            str(python),
            [str(python), str(Path(repo.__file__).resolve()), "test", "api-postgres"],
        )
    ]


def test_windows_break_signal_uses_pytest_interrupt_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import pytest_manifest

    calls: list[tuple[int, object]] = []
    monkeypatch.setattr(signal, "SIGBREAK", 99, raising=False)
    monkeypatch.setattr(signal, "signal", lambda number, handler: calls.append((number, handler)))
    pytest_manifest.pytest_configure()
    assert calls == [(99, signal.default_int_handler)]
