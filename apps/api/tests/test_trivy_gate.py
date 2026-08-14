from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

from scripts.repo import (
    HarnessError,
    cmd_trivy,
    redact_trivy_report,
    summarize_trivy_report,
)


def write_report(path: Path, result: dict[str, object] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"SchemaVersion": 2, "Results": [result or {}]}),
        encoding="utf-8",
    )


def test_gate_blocks_critical_and_fixable_high_vulnerabilities(tmp_path: Path) -> None:
    report = tmp_path / "filesystem.json"
    write_report(
        report,
        {
            "Vulnerabilities": [
                {"Severity": "CRITICAL", "FixedVersion": ""},
                {"Severity": "HIGH", "FixedVersion": "2.0.0"},
                {"Severity": "HIGH", "FixedVersion": ""},
                {"Severity": "MEDIUM", "FixedVersion": "2.0.0"},
            ]
        },
    )

    summary = summarize_trivy_report(report)

    assert summary.critical_vulnerabilities == 1
    assert summary.fixable_high_vulnerabilities == 1
    assert summary.blocking_findings == 2


def test_gate_blocks_high_or_critical_secrets_and_misconfigurations(
    tmp_path: Path,
) -> None:
    report = tmp_path / "filesystem.json"
    write_report(
        report,
        {
            "Misconfigurations": [
                {"Severity": "LOW"},
                {"Severity": "HIGH"},
            ],
            "Secrets": [
                {"Severity": "MEDIUM", "Match": "must-not-be-printed"},
                {"Severity": "CRITICAL", "Match": "must-not-be-printed"},
            ],
        },
    )

    summary = summarize_trivy_report(report)

    assert summary.high_or_critical_misconfigurations == 1
    assert summary.high_or_critical_secrets == 1
    assert summary.blocking_findings == 2


def test_gate_requires_all_reports_and_does_not_print_secret_values(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_report(tmp_path / "filesystem.json")
    write_report(tmp_path / "compose.json")
    write_report(tmp_path / "api-image.json")
    write_report(
        tmp_path / "web-image.json",
        {"Secrets": [{"Severity": "CRITICAL", "Match": "sensitive-value"}]},
    )

    with pytest.raises(HarnessError, match="rejected 1 finding"):
        args = type("Args", (), {"action": "gate", "report_dir": str(tmp_path)})()
        cmd_trivy(args)

    assert "sensitive-value" not in capsys.readouterr().out


def test_gate_rejects_missing_report(tmp_path: Path) -> None:
    write_report(tmp_path / "filesystem.json")

    with pytest.raises(
        HarnessError,
        match=(
            r"Missing Trivy reports: compose\.json, api-image\.json, "
            r"web-image\.json"
        ),
    ):
        args = type("Args", (), {"action": "gate", "report_dir": str(tmp_path)})()
        cmd_trivy(args)


def test_report_redaction_removes_secret_match_and_code(tmp_path: Path) -> None:
    report = tmp_path / "filesystem.json"
    write_report(
        report,
        {
            "Secrets": [
                {
                    "RuleID": "test-secret",
                    "Severity": "HIGH",
                    "Match": "sensitive-value",
                    "Code": {"Lines": [{"Content": "token=sensitive-value"}]},
                }
            ]
        },
    )

    assert redact_trivy_report(report) == 1
    redacted = report.read_text(encoding="utf-8")
    assert "sensitive-value" not in redacted
    assert '"RuleID": "test-secret"' in redacted


def test_trivy_ignore_entries_are_scoped_explained_and_unexpired() -> None:
    policy = yaml.safe_load(Path(".trivyignore.yaml").read_text(encoding="utf-8"))

    for section in ("vulnerabilities", "misconfigurations", "secrets"):
        entries = policy.get(section, [])
        assert isinstance(entries, list)
        for entry in entries:
            assert {"id", "paths", "statement", "expired_at"} <= entry.keys()
            assert entry["id"].strip()
            assert entry["statement"].strip()
            assert entry["paths"] and all(path.strip() for path in entry["paths"])
            expiration = entry["expired_at"]
            if isinstance(expiration, str):
                expiration = date.fromisoformat(expiration)
            assert expiration >= date.today()


def test_non_compose_iac_fixture_requires_yaml_and_json_findings(
    tmp_path: Path,
) -> None:
    report = tmp_path / "non-compose-iac.json"
    report.write_text(
        json.dumps(
            {
                "SchemaVersion": 2,
                "Results": [
                    {
                        "Target": "security/trivy/fixtures/non-compose/insecure-pod.json",
                        "Misconfigurations": [{"Severity": "HIGH"}],
                    },
                    {
                        "Target": "security/trivy/fixtures/non-compose/insecure-pod.yaml",
                        "Misconfigurations": [{"Severity": "HIGH"}],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    args = type(
        "Args",
        (),
        {"action": "verify-iac-fixture", "report_dir": str(report)},
    )()

    cmd_trivy(args)


def test_docker_socket_fixture_requires_both_paths_and_compose_syntaxes(
    tmp_path: Path,
) -> None:
    report = tmp_path / "compose-policy.json"
    report.write_text(
        json.dumps(
            {
                "SchemaVersion": 2,
                "Results": [
                    {
                        "Misconfigurations": [
                            {
                                "ID": "ANY-COMPOSE-003",
                                "Message": ('Compose service "var-run-short-syntax" must not mount the Docker socket'),
                            },
                            {
                                "ID": "ANY-COMPOSE-003",
                                "Message": ('Compose service "run-short-syntax" must not mount the Docker socket'),
                            },
                            {
                                "ID": "ANY-COMPOSE-003",
                                "Message": ('Compose service "var-run-long-syntax" must not mount the Docker socket'),
                            },
                            {
                                "ID": "ANY-COMPOSE-003",
                                "Message": ('Compose service "run-long-syntax" must not mount the Docker socket'),
                            },
                        ]
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    args = type(
        "Args",
        (),
        {"action": "verify-compose-fixture", "report_dir": str(report)},
    )()

    cmd_trivy(args)
