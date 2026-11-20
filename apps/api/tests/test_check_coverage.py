from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from scripts import api_test_runner, repo


@dataclass
class CheckCalls:
    environment: dict[str, str]
    commands: list[tuple[list[str], dict[str, str] | None]] = field(default_factory=list)
    runners: list[tuple[str, int, dict[str, str]]] = field(default_factory=list)


@pytest.fixture
def check_calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> CheckCalls:
    calls = CheckCalls(
        {"TEMP": "check-temp", "TEST_POSTGRES_DATABASE_URL": "postgresql+psycopg://localhost/unused_tests"}
    )
    monkeypatch.setattr(repo, "ROOT", tmp_path)
    monkeypatch.setattr(repo, "canonical_check_environment", lambda: calls.environment)
    monkeypatch.setattr(repo, "cmd_docs", lambda _: None)
    monkeypatch.setattr(repo, "cmd_generate", lambda _: None)
    monkeypatch.setattr(repo, "cmd_architecture", lambda _: None)
    monkeypatch.setattr(repo, "tool", lambda name: name)
    monkeypatch.delenv("RUN_E2E", raising=False)

    def capture_run(command: list[str], *, env: dict[str, str] | None = None, **_: object) -> None:
        calls.commands.append((command, env))

    def capture_runner(
        *, target: str, workers: int, environment: dict[str, str], **_: object
    ) -> api_test_runner.RunnerResult:
        calls.runners.append((target, workers, environment))
        return api_test_runner.RunnerResult(0, tmp_path)

    monkeypatch.setattr(repo, "run", capture_run)
    monkeypatch.setattr(api_test_runner, "run_api_tests", capture_runner)
    return calls


@pytest.mark.parametrize("fast", [False, True])
@pytest.mark.parametrize("coverage", [False, True])
def test_check_executes_each_suite_once(check_calls: CheckCalls, tmp_path: Path, fast: bool, coverage: bool) -> None:
    args = repo.build_parser().parse_args(
        ["check", *(["--fast"] if fast else []), *(["--coverage"] if coverage else [])]
    )
    assert args.fast is fast
    assert args.coverage is coverage
    args.func(args)

    commands = [command for command, _ in check_calls.commands]
    assert [command for command in commands if "@anytoolai/web" in command] == [
        ["npm", "--workspace", "@anytoolai/web", "run", "test:components:coverage" if coverage else "test:components"]
    ]
    coverage_xml = tmp_path / ".harness/coverage/api/coverage.xml"
    assert [command for command in commands if "pytest" in command] == (
        [
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                "-m",
                "not postgres",
                "--cov=apps/api/app",
                "--cov-report=term-missing",
                f"--cov-report=xml:{coverage_xml}",
                "apps/api/tests",
            ]
        ]
        if coverage
        else []
    )
    assert [(target, workers) for target, workers, _ in check_calls.runners] == [
        *([] if coverage else [("api-fast", 1)]),
        *([] if fast else [("api-postgres", 4)]),
    ]
    assert coverage_xml.parent.is_dir() is coverage
    assert (commands.count(["npm", "run", "build:web"]) == 1) is (not fast)
    for command, environment in check_calls.commands:
        expected = (
            repo.api_test_environment("api-fast", check_calls.environment)
            if "pytest" in command
            else check_calls.environment
        )
        if "build:web" in command:
            expected = {**expected, "APP_PUBLIC_BASE_URL": "https://payments.example.test"}
        assert environment == expected
    assert all(
        environment == repo.api_test_environment(target, check_calls.environment)
        for target, _, environment in check_calls.runners
    )


@pytest.mark.parametrize("coverage", [False, True])
@pytest.mark.parametrize("failed_suite", ["components", "api-fast"])
def test_check_propagates_suite_failure(
    monkeypatch: pytest.MonkeyPatch, check_calls: CheckCalls, coverage: bool, failed_suite: str
) -> None:
    original_run = repo.run

    def fail_suite(command: list[str], **kwargs: object) -> None:
        original_run(command, **kwargs)
        if (failed_suite == "components" and "@anytoolai/web" in command) or (
            failed_suite == "api-fast" and "pytest" in command
        ):
            raise subprocess.CalledProcessError(7, command)

    def fail_runner(**_: object) -> api_test_runner.RunnerResult:
        raise SystemExit(7)

    monkeypatch.setattr(repo, "run", fail_suite)
    monkeypatch.setattr(api_test_runner, "run_api_tests", fail_runner)
    args = repo.build_parser().parse_args(["check", "--fast", *(["--coverage"] if coverage else [])])
    with pytest.raises((subprocess.CalledProcessError, SystemExit)) as caught:
        args.func(args)
    error = caught.value
    assert (error.returncode if isinstance(error, subprocess.CalledProcessError) else error.code) == 7
    commands = [command for command, _ in check_calls.commands]
    assert sum("@anytoolai/web" in command for command in commands) == 1
    assert sum("pytest" in command for command in commands) == int(coverage and failed_suite == "api-fast")


@pytest.mark.parametrize("target", ["api", "api-fast"])
def test_standalone_api_coverage_retains_serial_scope(check_calls: CheckCalls, tmp_path: Path, target: str) -> None:
    args = repo.build_parser().parse_args(["coverage", target])
    args.func(args)

    assert check_calls.runners == []
    assert check_calls.commands == [
        (
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "no:cacheprovider",
                *(["-m", "not postgres"] if target == "api-fast" else []),
                "--cov=apps/api/app",
                "--cov-report=term-missing",
                f"--cov-report=xml:{tmp_path / '.harness/coverage/api/coverage.xml'}",
                "apps/api/tests",
            ],
            repo.api_test_environment(target, check_calls.environment),
        )
    ]


@pytest.mark.parametrize(
    "arguments", [["check", "--fast", "--coverage"], ["coverage", "api-fast"], ["coverage", "api"]]
)
def test_coverage_cannot_hide_failure_with_ambient_pytest_configuration(
    check_calls: CheckCalls, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    tests = tmp_path / "apps/api/tests"
    application = tmp_path / "apps/api/app"
    tests.mkdir(parents=True)
    application.mkdir(parents=True)
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    postgres: database partition\n", encoding="utf-8")
    (application / "sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    plugin = tmp_path / "hide_tests.py"
    plugin.write_text(
        "from pathlib import Path\n"
        "Path(__file__).with_suffix('.loaded').touch()\n"
        "def pytest_collection_modifyitems(config, items):\n"
        "    hidden = [item for item in items if item.name == 'test_regression']\n"
        "    items[:] = [item for item in items if item not in hidden]\n"
        "    config.hook.pytest_deselected(items=hidden)\n",
        encoding="utf-8",
    )
    (tests / "test_selection.py").write_text(
        "from runpy import run_path\n"
        "sample = run_path('apps/api/app/sample.py')\n"
        "def test_selected():\n    assert sample['VALUE'] == 1\n"
        "def test_regression():\n    assert False, 'coverage must retain this failure'\n",
        encoding="utf-8",
    )
    check_calls.environment.update(
        {
            "PATH": os.environ["PATH"],
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTEST_PLUGINS": "hide_tests",
            "PYTEST_ADDOPTS": "-k selected",
            "COVERAGE_FILE": str(tmp_path / ".coverage"),
        }
    )
    capture_run = repo.run

    def execute_api(command: list[str], *, env: dict[str, str] | None = None, **kwargs: object) -> None:
        capture_run(command, env=env, **kwargs)
        if "pytest" in command:
            # This probe disables autoload; select its required coverage plugin explicitly.
            command = [*command[:3], "-p", "pytest_cov.plugin", *command[3:]]
            subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, check=True, timeout=15)

    monkeypatch.setattr(repo, "run", execute_api)
    args = repo.build_parser().parse_args(arguments)
    with pytest.raises(subprocess.CalledProcessError) as caught:
        args.func(args)

    assert caught.value.returncode == 1
    assert "1 failed, 1 passed" in caught.value.stdout
    assert "deselected" not in caught.value.stdout
    assert (tmp_path / ".harness/coverage/api/coverage.xml").is_file()
    assert sum("pytest" in command for command, _ in check_calls.commands) == 1
    assert check_calls.environment["PYTEST_ADDOPTS"] == "-k selected"
    assert check_calls.environment["PYTEST_PLUGINS"] == "hide_tests"
    assert not plugin.with_suffix(".loaded").exists()
