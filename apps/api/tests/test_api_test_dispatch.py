import argparse
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

import pytest

from scripts import repo


@pytest.mark.parametrize("postgres_fails", [False, True])
def test_complete_api_keeps_fast_serial_and_preserves_partition_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    postgres_fails: bool,
) -> None:
    commands: list[list[str]] = []
    monkeypatch.setattr(repo, "HARNESS_DIR", tmp_path / "harness")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        commands.append(command)
        is_postgres = "scripts.pytest_parallel" in command
        destination = (
            command[command.index("--junitxml") + 1]
            if is_postgres
            else next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junitxml="))
        )
        failure = "<failure/>" if is_postgres and postgres_fails else ""
        Path(destination).write_text(
            f'<testsuites><testsuite><testcase name="{is_postgres}">{failure}</testcase></testsuite></testsuites>'
        )
        if failure:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(repo, "run", run)
    report = tmp_path / "combined.xml"
    args = argparse.Namespace(target="api", workers=None, junitxml=str(report))
    environment = {"TEST_POSTGRES_DATABASE_URL": "postgresql+psycopg://owner@localhost/configured_tests"}
    if postgres_fails:
        with pytest.raises(subprocess.CalledProcessError):
            repo.cmd_test(args, environment=environment)
    else:
        repo.cmd_test(args, environment=environment)
    assert commands[0][1:3] == ["-m", "pytest"]
    assert "not postgres" in commands[0]
    assert commands[1][1:5] == ["-m", "scripts.pytest_parallel", "--workers", "4"]
    assert "postgres" in commands[1]
    assert len(ET.parse(report).findall(".//testcase")) == 2
    assert len(ET.parse(report).findall(".//failure")) == int(postgres_fails)
