from __future__ import annotations

import json
from argparse import Namespace
from datetime import date
from pathlib import Path
from subprocess import CompletedProcess

import pytest
import yaml
from scripts.repo import (
    ROOT,
    HarnessError,
    ProductionScanTarget,
    cmd_trivy,
    production_manifest_digest,
    redact_trivy_report,
    summarize_trivy_report,
)


def write_report(path: Path, result: dict[str, object] | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_payload(path, result)),
        encoding="utf-8",
    )


def report_payload(path: Path, result: dict[str, object] | None) -> dict[str, object]:
    image = path.name.endswith("-image.json")
    return {
        "SchemaVersion": 2,
        "ArtifactName": path.stem if image else ".",
        "ArtifactType": "container_image" if image else "filesystem",
        "Metadata": {"ImageID": "sha256:" + "a" * 64} if image else {},
        "Results": [{"Target": path.stem, "Class": "os-pkgs", **(result or {})}],
    }


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
    complete_reports(tmp_path)
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
            r"web-image\.json, postgres-image\.json, caddy-image\.json"
        ),
    ):
        args = type("Args", (), {"action": "gate", "report_dir": str(tmp_path)})()
        cmd_trivy(args)


@pytest.mark.parametrize("name", ["filesystem.json", "postgres-image.json", "caddy-image.json"])
def test_report_redaction_removes_secret_match_and_code(tmp_path: Path, name: str) -> None:
    report = tmp_path / name
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
            ],
            "Misconfigurations": [
                {
                    "Severity": "HIGH",
                    "CauseMetadata": {"Resource": "test", "Code": {"Lines": ["sensitive-value"]}},
                }
            ],
        },
    )

    assert redact_trivy_report(report) == 1
    redacted = report.read_text(encoding="utf-8")
    assert "sensitive-value" not in redacted
    assert '"RuleID": "test-secret"' in redacted


def test_trivy_ignore_entries_are_scoped_explained_and_unexpired() -> None:
    policy = yaml.safe_load((ROOT / ".trivyignore.yaml").read_text(encoding="utf-8"))

    for section in ("vulnerabilities", "misconfigurations", "secrets"):
        entries = policy.get(section, [])
        assert isinstance(entries, list)
        for entry in entries:
            assert {"id", "statement", "expired_at"} <= entry.keys()
            assert entry["id"].strip()
            statement = entry["statement"].strip()
            assert statement
            assert "Owner:" in statement
            assert "Affected image:" in statement or "Affected path:" in statement
            scopes = []
            for scope_key in ("paths", "purls"):
                section_scopes = entry.get(scope_key, [])
                assert isinstance(section_scopes, list)
                assert all(isinstance(scope, str) and scope.strip() for scope in section_scopes)
                scopes.extend(section_scopes)
            assert scopes
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


_IMAGE_REPORTS = ("api-image.json", "web-image.json", "postgres-image.json", "caddy-image.json")
_SCAN_REPORTS = ("filesystem.json", "compose.json", *_IMAGE_REPORTS)


def complete_reports(directory: Path) -> None:
    for name in _SCAN_REPORTS:
        write_report(directory / name)


@pytest.mark.parametrize("action", ["verify-reports", "gate"])
def test_complete_six_report_set(tmp_path: Path, action: str) -> None:
    complete_reports(tmp_path)
    cmd_trivy(Namespace(action=action, report_dir=str(tmp_path)))


@pytest.mark.parametrize("image", ["postgres", "caddy"])
@pytest.mark.parametrize("action", ["verify-reports", "gate"])
def test_requires_each_production_image_report(tmp_path: Path, image: str, action: str) -> None:
    complete_reports(tmp_path)
    (tmp_path / f"{image}-image.json").unlink()

    with pytest.raises(HarnessError, match=rf"Missing Trivy reports: {image}-image\.json"):
        cmd_trivy(Namespace(action=action, report_dir=str(tmp_path)))


@pytest.mark.parametrize("image", ["postgres", "caddy"])
@pytest.mark.parametrize("action", ["verify-reports", "gate"])
@pytest.mark.parametrize(
    "invalid",
    [
        "{",
        "[]",
        "{}",
        '{"SchemaVersion":2,"Results":[]}',
        '{"SchemaVersion":2,"ArtifactType":"filesystem","ArtifactName":"."}',
    ],
)
def test_rejects_malformed_production_report(
    tmp_path: Path,
    image: str,
    action: str,
    invalid: str,
) -> None:
    complete_reports(tmp_path)
    (tmp_path / f"{image}-image.json").write_text(invalid, encoding="utf-8")

    with pytest.raises(HarnessError, match=rf"Trivy report .*{image}-image\.json"):
        cmd_trivy(Namespace(action=action, report_dir=str(tmp_path)))


@pytest.mark.parametrize("image", ["postgres", "caddy"])
@pytest.mark.parametrize(
    ("severity", "fixed", "blocks"),
    [
        ("CRITICAL", "", True),
        ("HIGH", "1.0.1", True),
        ("HIGH", "", False),
        ("MEDIUM", "1.0.1", False),
    ],
)
def test_production_image_finding_policy(
    tmp_path: Path,
    image: str,
    severity: str,
    fixed: str,
    blocks: bool,
) -> None:
    complete_reports(tmp_path)
    write_report(
        tmp_path / f"{image}-image.json",
        {
            "Vulnerabilities": [{"Severity": severity, "FixedVersion": fixed}],
        },
    )
    cmd_trivy(Namespace(action="verify-reports", report_dir=str(tmp_path)))
    if blocks:
        with pytest.raises(HarnessError, match="policy rejected 1 finding"):
            cmd_trivy(Namespace(action="gate", report_dir=str(tmp_path)))
    else:
        cmd_trivy(Namespace(action="gate", report_dir=str(tmp_path)))


@pytest.mark.parametrize("service", ["postgres", "caddy"])
def test_production_reference_comes_from_compose(
    monkeypatch: pytest.MonkeyPatch,
    service: str,
) -> None:
    from scripts import repo

    compose = ROOT / "docker-compose.prod.yml"
    model = yaml.safe_load(compose.read_text(encoding="utf-8"))
    expected = model["services"][service]["image"]

    def read_compose(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        assert str(compose) in command
        assert {"--no-interpolate", "--no-env-resolution"} <= set(command)
        assert kwargs["capture"] is True
        return CompletedProcess(command, 0, stdout=json.dumps(model))

    monkeypatch.setattr(repo, "tool", lambda name: name)
    monkeypatch.setattr(repo, "run", read_compose)
    assert repo.production_scan_target(compose, service).requested_reference == expected


@pytest.mark.parametrize("service", ["postgres", "caddy"])
@pytest.mark.parametrize(
    "definition",
    [
        None,
        {},
        {"image": "test:latest"},
        {"image": "${IMAGE:?required}"},
        {"image": 12},
        {"image": "invalid image@sha256:" + "a" * 64},
    ],
)
def test_rejects_missing_or_invalid_production_reference(
    monkeypatch: pytest.MonkeyPatch,
    service: str,
    definition: dict[str, object] | None,
) -> None:
    from scripts import repo

    monkeypatch.setattr(repo, "tool", lambda name: name)
    monkeypatch.setattr(
        repo,
        "run",
        lambda *args, **kwargs: CompletedProcess(
            args,
            0,
            stdout=json.dumps({"services": {service: definition} if definition is not None else {}}),
        ),
    )
    with pytest.raises(HarnessError, match=service):
        repo.production_scan_target(ROOT / "docker-compose.prod.yml", service)


def test_workflow_uploads_only_after_redaction_and_checks_completeness() -> None:
    workflow = yaml.safe_load((ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"]["trivy"]["steps"]
    redact = next(step for step in steps if step.get("id") == "redact")
    upload = next(step for step in steps if step.get("uses", "").startswith("actions/upload-artifact@"))
    verify = next(step for step in steps if "trivy verify-reports " in step.get("run", ""))
    gate = next(step for step in steps if "trivy gate " in step.get("run", ""))
    assert steps.index(redact) < steps.index(upload) < steps.index(verify) < steps.index(gate)
    assert redact["if"] == "always()"
    assert "steps.redact.outcome == 'success'" in upload["if"]
    assert "TRIVY_ENFORCE" not in verify.get("if", "")
    assert "vars.TRIVY_ENFORCE == 'true'" in gate["if"]


def test_manifest_resolution_selects_the_platform_digest() -> None:
    requested_digest = "sha256:" + "a" * 64
    selected_digest = "sha256:" + "b" * 64
    target = ProductionScanTarget(f"example/image@{requested_digest}", "linux/amd64")
    amd64 = {"digest": selected_digest, "platform": {"os": "linux", "architecture": "amd64"}}
    arm64 = {"digest": "sha256:" + "c" * 64, "platform": {"os": "linux", "architecture": "arm64"}}

    assert (
        production_manifest_digest(
            {"schemaVersion": 2, "manifests": [arm64, amd64]},
            target,
        )
        == selected_digest
    )
    assert (
        production_manifest_digest(
            {"schemaVersion": 2, "config": {}, "layers": []},
            target,
        )
        == requested_digest
    )
    for descriptors in ([arm64], [amd64, amd64]):
        with pytest.raises(HarnessError, match="Cannot select one linux/amd64"):
            production_manifest_digest({"schemaVersion": 2, "manifests": descriptors}, target)
