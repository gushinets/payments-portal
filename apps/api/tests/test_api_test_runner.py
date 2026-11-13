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


@pytest.fixture
def previous_report(tmp_path: Path) -> Path:
    path = tmp_path / "current.xml"
    path.write_text(
        '<testsuites tests="1"><testsuite tests="1"><testcase name="previous-success"/></testsuite></testsuites>',
        encoding="utf-8",
    )
    return path


def assert_startup_error(path: Path, message: str) -> None:
    report = ET.parse(path)
    assert report.getroot().attrib["errors"] == "1"
    assert report.find(".//testcase[@name='previous-success']") is None
    errors = report.findall(".//error")
    assert len(errors) == 1 and message in errors[0].attrib["message"]


@pytest.mark.parametrize(
    "target,workers,arguments,message",
    [
        ("api-postgres", 4, ["--unsupported"], "Unsupported pytest argument"),
        ("api-postgres", 0, [], "Workers must be"),
        ("api-fast", 2, [], "api-fast supports only"),
    ],
)
def test_runner_startup_failure_replaces_previous_report(
    suite: Path,
    previous_report: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    workers: int,
    arguments: list[str],
    message: str,
) -> None:
    monkeypatch.setattr(runner, "execute", lambda *args: pytest.fail("Startup failure must not start pytest"))
    with pytest.raises(runner.RunnerError, match=message):
        runner.run_api_tests(
            root=suite,
            artifacts=suite / "reports",
            target=target,
            workers=workers,
            environment=environment(),
            arguments=arguments,
            junitxml=previous_report,
        )
    assert_startup_error(previous_report, message)


@pytest.mark.parametrize("failure", ["partial-config", "stopped-server", "invalid-workers"])
def test_command_startup_failure_replaces_previous_report(
    previous_report: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    monkeypatch.setattr(
        runner, "run_api_tests", lambda **kwargs: pytest.fail("Preparation must fail before the runner")
    )
    monkeypatch.setattr(
        repo,
        "read_runtime_env",
        lambda: {
            "POSTGRES_USER": "synthetic",
            "POSTGRES_PASSWORD": "synthetic",
            "POSTGRES_DB": "worktree",
            "POSTGRES_PORT_TEST": "15432",
        },
    )
    monkeypatch.setattr(repo, "port_is_free", lambda port: True)
    target, workers = ("api-fast", 2) if failure == "invalid-workers" else ("api-postgres", 4)
    inherited = {"POSTGRES_USER_TEST": "synthetic"} if failure == "partial-config" else {}
    message = {
        "partial-config": "Incomplete PostgreSQL test configuration",
        "stopped-server": "Local test PostgreSQL server is not running",
        "invalid-workers": "api-fast supports only",
    }[failure]
    with pytest.raises(repo.HarnessError, match=message):
        repo.cmd_test(
            argparse.Namespace(target=target, workers=workers, junitxml=str(previous_report), pytest_args=[]),
            environment=inherited,
        )
    assert_startup_error(previous_report, message)


@pytest.mark.parametrize("target", ["api-fast", "api-postgres"])
def test_cli_startup_failure_returns_error_with_current_report(previous_report: Path, target: str) -> None:
    inherited = {
        name: value
        for name, value in environment().items()
        if name != "TEST_POSTGRES_DATABASE_URL" and not (name.startswith("POSTGRES_") and name.endswith("_TEST"))
    }
    arguments = ["--pytest-args", "--unsupported"] if target == "api-fast" else []
    message = "Unsupported pytest argument" if target == "api-fast" else "Incomplete PostgreSQL test configuration"
    if target == "api-postgres":
        inherited["POSTGRES_USER_TEST"] = "synthetic"
    result = subprocess.run(
        [
            sys.executable,
            str(repo.ROOT / "scripts/repo.py"),
            "test",
            target,
            "--junitxml",
            str(previous_report),
            *arguments,
        ],
        cwd=repo.ROOT,
        env=inherited,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert result.returncode == 1 and message in result.stderr
    assert_startup_error(previous_report, message)


def test_command_startup_invalidates_report_before_configuration(
    previous_report: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def interrupted_configuration(target: str, environment: dict[str, str]) -> dict[str, str]:
        assert_startup_error(previous_report, "not completed")
        raise KeyboardInterrupt

    monkeypatch.setattr(repo, "api_test_environment", interrupted_configuration)
    monkeypatch.setattr(
        runner, "run_api_tests", lambda **kwargs: pytest.fail("Interrupted preparation cannot run pytest")
    )
    with pytest.raises(KeyboardInterrupt):
        repo.cmd_test(argparse.Namespace(target="api-fast", workers=1, junitxml=str(previous_report)), environment={})
    assert_startup_error(previous_report, "not completed")


@pytest.mark.parametrize("entrypoint", ["command", "runner"])
def test_startup_report_write_failure_is_visible_before_preparation(
    suite: Path, monkeypatch: pytest.MonkeyPatch, entrypoint: str
) -> None:
    blocked = suite / "blocked"
    blocked.write_text("not a directory", encoding="utf-8")
    report = blocked / "current.xml"
    monkeypatch.setattr(repo, "api_test_environment", lambda *args: pytest.fail("Cannot prepare without a report"))
    monkeypatch.setattr(runner, "execute", lambda *args: pytest.fail("Cannot execute without a report"))
    with pytest.raises(OSError):
        if entrypoint == "command":
            repo.cmd_test(argparse.Namespace(target="api-fast", workers=1, junitxml=str(report)), environment={})
        else:
            runner.run_api_tests(
                root=suite,
                artifacts=suite / "reports",
                target="api-fast",
                workers=1,
                environment=environment(),
                junitxml=report,
            )


def test_successful_retry_replaces_startup_failure(suite: Path, previous_report: Path) -> None:
    source(
        suite, "test_good.py", "import pytest\npytestmark = pytest.mark.postgres\ndef test_good():\n    assert True\n"
    )
    with pytest.raises(runner.RunnerError, match="Unsupported pytest argument"):
        runner.run_api_tests(
            root=suite,
            artifacts=suite / "reports",
            target="api-postgres",
            workers=1,
            environment=environment(),
            arguments=["--unsupported"],
            junitxml=previous_report,
        )
    assert_startup_error(previous_report, "Unsupported pytest argument")
    result = run_suite(suite)
    assert result.returncode == 0
    assert report_nodes(previous_report) == ["apps/api/tests/test_good.py::test_good"]
    assert not ET.parse(previous_report).findall(".//error")


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


def test_partial_worker_start_retains_completed_results_and_previous_partition(
    suite: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source(suite, "test_fast.py", "def test_fast_failure():\n    assert False\n")
    source(
        suite,
        "test_first.py",
        """import pytest
pytestmark = pytest.mark.postgres
def test_failure():
    assert False, "completed worker failure"
@pytest.mark.skip(reason="intentional sample skip")
def test_skip():
    pass
""",
    )
    source(suite, "test_second.py", "import pytest\n@pytest.mark.postgres\ndef test_unstarted():\n    pass\n")
    popen = subprocess.Popen
    processes: list[subprocess.Popen[bytes]] = []

    def partial_start(command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        reports = [Path(argument.split("=", 1)[1]) for argument in command if argument.startswith("--junitxml=")]
        if reports and reports[0].parent.name == "worker-2":
            # Coordinate the failure with completion, without depending on launch speed.
            assert processes[-1].wait(timeout=15) == 1
            raise OSError("controlled second-worker startup failure")
        process = popen(command, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(runner.subprocess, "Popen", partial_start)
    result = run_suite(suite, target="api", workers=2)

    assert result.returncode == 1
    assert all(process.returncode is not None for process in processes)
    for path in (suite / "current.xml", result.directory / "junit.xml"):
        report = ET.parse(path)
        assert sorted(report_nodes(path)) == [
            "apps/api/tests/test_fast.py::test_fast_failure",
            "apps/api/tests/test_first.py::test_failure",
            "apps/api/tests/test_first.py::test_skip",
        ]
        assert len(report.findall(".//failure")) == 2
        assert len(report.findall(".//skipped")) == 1
        errors = report.findall(".//error")
        assert len(errors) == 1 and "controlled second-worker startup failure" in errors[0].attrib["message"]


def test_interruption_during_report_validation_does_not_duplicate_completed_results(
    suite: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for module in ("first", "second"):
        source(suite, f"test_{module}.py", "import pytest\n@pytest.mark.postgres\ndef test_pass():\n    pass\n")
    validate = runner.check_junit
    checked = 0

    def interrupt_validation(root: ET.Element, expected: list[str], returncode: int) -> None:
        nonlocal checked
        checked += 1
        if checked == 2:
            raise KeyboardInterrupt
        validate(root, expected, returncode)

    monkeypatch.setattr(runner, "check_junit", interrupt_validation)
    result = run_suite(suite, workers=2)

    assert result.returncode == 130
    assert report_nodes(suite / "current.xml") == [
        "apps/api/tests/test_first.py::test_pass",
        "apps/api/tests/test_second.py::test_pass",
    ]
    assert len(ET.parse(suite / "current.xml").findall(".//error")) == 1


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


@pytest.mark.parametrize(
    "arguments",
    [
        ["test", "api-fast", "--pytest-args", "-k", "one or two"],
        ["check", "--fast", "--coverage"],
    ],
)
def test_test_launcher_replaces_venv_shim_so_signals_reach_runner(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, arguments: list[str]
) -> None:
    venv = tmp_path / "venv"
    python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(repo, "REPOSITORY_VENV", venv)
    monkeypatch.setattr(sys, "argv", ["repo.py", *arguments])
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
            [str(python), "--", str(Path(repo.__file__).resolve()), *arguments],
        )
    ]


def test_windows_break_signal_uses_pytest_interrupt_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts import pytest_manifest

    calls: list[tuple[int, object]] = []
    monkeypatch.setattr(signal, "SIGBREAK", 99, raising=False)
    monkeypatch.setattr(signal, "signal", lambda number, handler: calls.append((number, handler)))
    pytest_manifest.pytest_configure()
    assert calls == [(99, signal.default_int_handler)]
