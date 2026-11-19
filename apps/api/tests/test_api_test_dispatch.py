import argparse
import os
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest

from scripts import repo


@pytest.mark.parametrize("postgres_fails", [False, True])
def test_complete_api_keeps_fast_serial_and_preserves_partition_reports(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    postgres_fails: bool,
) -> None:
    tests = tmp_path / "apps/api/tests"
    tests.mkdir(parents=True)
    (tmp_path / "pytest.ini").write_text("[pytest]\nmarkers =\n    postgres: database partition\n")
    (tests / "test_fast.py").write_text("def test_fast():\n    assert True\n")
    (tests / "test_postgres.py").write_text(
        f"import pytest\npytestmark = pytest.mark.postgres\ndef test_postgres():\n    assert {not postgres_fails}\n"
    )
    source_root = repo.ROOT
    monkeypatch.setattr(repo, "ROOT", tmp_path)
    monkeypatch.setattr(repo, "HARNESS_DIR", tmp_path / "harness")
    report = tmp_path / "combined.xml"
    report.write_text('<testsuites><testsuite><testcase name="previous-success"/></testsuite></testsuites>')
    args = argparse.Namespace(target="api", workers=None, junitxml=str(report))
    environment = {
        **os.environ,
        "PYTHONPATH": str(source_root),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "TEST_POSTGRES_DATABASE_URL": "postgresql+psycopg://owner@localhost/configured_tests",
    }
    if postgres_fails:
        with pytest.raises(SystemExit) as caught:
            repo.cmd_test(args, environment=environment)
        assert caught.value.code == 1
    else:
        repo.cmd_test(args, environment=environment)
    assert ET.parse(report).find(".//testcase[@name='previous-success']") is None
    assert len(ET.parse(report).findall(".//testcase")) == 2
    assert len(ET.parse(report).findall(".//failure")) == int(postgres_fails)
    assert not ET.parse(report).findall(".//error")
    assert len(list((tmp_path / "harness").glob("api-tests/*/fast/worker-*/junit.xml"))) == 1
    assert len(list((tmp_path / "harness").glob("api-tests/*/postgres/worker-*/junit.xml"))) == 1
