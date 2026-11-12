from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest

from scripts.pytest_parallel import partition_files, run_parallel, stop_workers


def test_partition_keeps_modules_whole_and_assigns_every_file_once() -> None:
    groups = partition_files(["a.py::test_a[0]", "a.py::test_a[1]", "b.py::test_b", "c.py::test_c"], 2)
    assert groups == [["a.py"], ["b.py", "c.py"]]
    assert partition_files(["a.py::test_a"], 4) == [["a.py"]]


@pytest.mark.parametrize("failure", [False, True])
def test_parallel_reports_preserve_all_cases_and_failures(tmp_path: Path, failure: bool) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_a.py").write_text(
        "import pytest\n@pytest.mark.parametrize('value', [0, 1])\ndef test_a(value): assert value < 2\n"
    )
    (suite / "test_b.py").write_text(f"def test_b(): assert {not failure}\n")
    report = tmp_path / "combined.xml"
    result = run_parallel(
        root=Path.cwd(),
        test_path=str(suite),
        marker=None,
        workers=2,
        artifacts=tmp_path / "artifacts",
        junitxml=report,
    )
    cases = ET.parse(report).findall(".//testcase")
    assert len(cases) == 3
    assert sum(case.find("failure") is not None for case in cases) == int(failure)
    assert result == int(failure)


def test_worker_exit_without_report_cannot_pass(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    executed = tmp_path / "executed"
    (suite / "test_crash.py").write_text(
        f"import os\nfrom pathlib import Path\ndef test_crash():\n    Path({str(executed)!r}).touch()\n    os._exit(0)\n"
    )
    report = tmp_path / "combined.xml"
    report.write_text("stale report")
    result = run_parallel(
        root=Path.cwd(),
        test_path=str(suite),
        marker=None,
        workers=2,
        artifacts=tmp_path / "artifacts",
        junitxml=report,
    )
    assert result == 1
    assert executed.exists()
    assert "stale" not in report.read_text()


def test_collection_failure_replaces_stale_junit(tmp_path: Path) -> None:
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_broken.py").write_text("def broken syntax\n")
    report = tmp_path / "combined.xml"
    report.write_text("stale report")
    result = run_parallel(
        root=Path.cwd(),
        test_path=str(suite),
        marker=None,
        workers=2,
        artifacts=tmp_path / "artifacts",
        junitxml=report,
    )
    assert result != 0
    assert ET.parse(report).findall(".//error")


def test_cancellation_reaps_running_worker() -> None:
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"], stderr=subprocess.DEVNULL)
    stop_workers([process])
    assert process.poll() is not None
