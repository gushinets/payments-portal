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
    ProductionImageManifest,
    ProductionScanTarget,
    cmd_trivy,
    production_image_manifests,
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
    image = "-image" in path.stem
    service = path.stem.split("-image", 1)[0]
    reference = f"example/{service}@{_FIXTURE_IMAGE_ID}" if service in {"postgres", "caddy"} else path.stem
    return {
        "SchemaVersion": 2,
        "ArtifactName": reference if image else ".",
        "ArtifactType": "container_image" if image else "repository",
        "Metadata": {"ImageID": _FIXTURE_IMAGE_ID} if image else {},
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
_FIXTURE_IMAGE_ID = "sha256:" + "a" * 64
_OCI_MANIFEST = "application/vnd.oci.image.manifest.v1+json"


def write_provenance(directory: Path, service: str, *, arm64: bool = False) -> None:
    scans = [
        {
            "report": f"{service}-image.json",
            "platform": "linux/amd64",
            "scanned_reference": f"example/{service}@{_FIXTURE_IMAGE_ID}",
            "platform_manifest_digest": _FIXTURE_IMAGE_ID,
            "image_config_digest": _FIXTURE_IMAGE_ID,
        }
    ]
    if arm64:
        scans.append({**scans[0], "report": f"{service}-image-linux-arm64-v8.json", "platform": "linux/arm64/v8"})
    path = directory / "provenance" / f"{service}.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps({"scans": scans}), encoding="utf-8")


def complete_reports(directory: Path) -> None:
    for name in _SCAN_REPORTS:
        write_report(directory / name)
    for service in ("postgres", "caddy"):
        write_provenance(directory, service)


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
    amd64 = {
        "mediaType": _OCI_MANIFEST,
        "digest": selected_digest,
        "platform": {"os": "linux", "architecture": "amd64"},
    }
    arm64 = {
        "mediaType": _OCI_MANIFEST,
        "digest": "sha256:" + "c" * 64,
        "platform": {"os": "linux", "architecture": "arm64"},
    }

    assert production_image_manifests(
        {"schemaVersion": 2, "manifests": [arm64, amd64]},
        target,
    ) == (ProductionImageManifest(selected_digest, "linux/amd64"),)
    assert production_image_manifests(
        {"schemaVersion": 2, "config": {}, "layers": []},
        ProductionScanTarget(target.requested_reference, None),
    ) == (ProductionImageManifest(requested_digest, None),)
    for descriptors, error in (
        ([arm64], "No matching image manifests"),
        ([amd64, amd64], "Duplicate linux/amd64 image manifest"),
        ([{**amd64, "mediaType": "application/vnd.oci.image.index.v1+json"}], "Invalid runtime descriptor"),
    ):
        with pytest.raises(HarnessError, match=error):
            production_image_manifests({"schemaVersion": 2, "manifests": descriptors}, target)


@pytest.mark.parametrize("platform", [None, "linux/arm64", "linux/amd64/v1"])
def test_scan_production_image_covers_every_selected_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    platform: str | None,
) -> None:
    from scripts import repo

    image = "example/postgres@sha256:" + "a" * 64
    amd64 = "sha256:" + "b" * 64
    arm64 = "sha256:" + "c" * 64
    scanned_digests = []

    def run_scan(command: list[str], **kwargs: object) -> CompletedProcess[str]:
        if command[:2] == ["docker", "compose"]:
            service = {"image": image}
            if platform is not None:
                service["platform"] = platform
            output = {"services": {"postgres": service}}
        elif command[:2] == ["docker", "buildx"]:
            output = {
                "schemaVersion": 2,
                "manifests": [
                    {
                        "mediaType": _OCI_MANIFEST,
                        "digest": arm64,
                        "platform": {"os": "linux", "architecture": "arm64", "variant": "v8"},
                    },
                    {"mediaType": _OCI_MANIFEST, "digest": amd64, "platform": {"os": "linux", "architecture": "amd64"}},
                    {
                        "digest": "sha256:" + "d" * 64,
                        "platform": {"os": "unknown", "architecture": "unknown"},
                        "annotations": {"vnd.docker.reference.type": "attestation-manifest"},
                    },
                ],
            }
        elif command[0] == "trivy":
            reference = command[-1]
            digest = reference.split("@")[1]
            scanned_digests.append(digest)
            path = Path(command[command.index("--output") + 1])
            payload = report_payload(path, None)
            payload.update(
                {
                    "ArtifactName": reference,
                    "ArtifactType": "container_image",
                    "Metadata": {
                        "ImageID": digest,
                        "RepoDigests": [reference],
                        "ImageConfig": {"os": "linux", "architecture": "arm64" if digest == arm64 else "amd64"},
                    },
                }
            )
            path.write_text(json.dumps(payload), encoding="utf-8")
            return CompletedProcess(command, 0)
        else:
            assert command[:3] == ["git", "rev-parse", "HEAD"]
            return CompletedProcess(command, 0, stdout="e" * 40)
        return CompletedProcess(command, 0, stdout=json.dumps(output))

    monkeypatch.setattr(repo, "tool", lambda name: name)
    monkeypatch.setattr(repo, "run", run_scan)
    repo.scan_production_image(tmp_path, "postgres")

    expected = {None: {amd64, arm64}, "linux/arm64": {arm64}, "linux/amd64/v1": {amd64}}
    assert set(scanned_digests) == expected[platform]


@pytest.mark.parametrize("action", ["verify-reports", "gate"])
def test_requires_every_platform_report(tmp_path: Path, action: str) -> None:
    complete_reports(tmp_path)
    write_provenance(tmp_path, "postgres", arm64=True)

    with pytest.raises(HarnessError, match="Missing Trivy reports: postgres-image-linux-arm64-v8.json"):
        cmd_trivy(Namespace(action=action, report_dir=str(tmp_path)))


@pytest.mark.parametrize("action", ["verify-reports", "gate"])
def test_rejects_mismatched_platform_report(tmp_path: Path, action: str) -> None:
    complete_reports(tmp_path)
    write_provenance(tmp_path, "postgres", arm64=True)
    path = tmp_path / "postgres-image-linux-arm64-v8.json"
    payload = report_payload(path, None)
    payload["ArtifactName"] = "example/other@" + _FIXTURE_IMAGE_ID
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(HarnessError, match="does not match production scan provenance"):
        cmd_trivy(Namespace(action=action, report_dir=str(tmp_path)))


def test_secondary_platform_report_is_sanitized_and_gated(tmp_path: Path) -> None:
    complete_reports(tmp_path)
    write_provenance(tmp_path, "caddy", arm64=True)
    path = tmp_path / "caddy-image-linux-arm64-v8.json"
    write_report(path, {"Secrets": [{"Severity": "HIGH", "Match": "example-private-value"}]})

    cmd_trivy(Namespace(action="redact", report_dir=str(tmp_path)))
    assert "example-private-value" not in path.read_text(encoding="utf-8")
    cmd_trivy(Namespace(action="verify-reports", report_dir=str(tmp_path)))
    with pytest.raises(HarnessError, match="policy rejected 1 finding"):
        cmd_trivy(Namespace(action="gate", report_dir=str(tmp_path)))


def test_redact_accepts_custom_image_report_filenames(tmp_path: Path) -> None:
    payload = report_payload(
        tmp_path / "web-image.json",
        {
            "Secrets": [
                {"Severity": "HIGH", "Match": "synthetic-secret", "Code": {"Lines": [{"Content": "synthetic-secret"}]}}
            ],
        },
    )
    paths = [tmp_path / "before.json", tmp_path / "after.json"]
    for path in paths:
        path.write_text(json.dumps(payload), encoding="utf-8")

    cmd_trivy(Namespace(action="redact", report_dir=str(tmp_path)))

    for path in paths:
        redacted = json.loads(path.read_text(encoding="utf-8"))
        assert redacted["Results"][0]["Secrets"] == [{"Severity": "HIGH"}]
        assert redacted["ArtifactName"] == payload["ArtifactName"]


@pytest.mark.parametrize("action", ["verify-reports", "gate"])
@pytest.mark.parametrize("report", ["web-image.json", "caddy-image-linux-arm64-v8.json"])
def test_workflow_rejects_wrong_report_artifact_type(
    tmp_path: Path,
    action: str,
    report: str,
) -> None:
    complete_reports(tmp_path)
    write_provenance(tmp_path, "caddy", arm64=True)
    write_report(tmp_path / "caddy-image-linux-arm64-v8.json")
    wrong_type = report_payload(tmp_path / "filesystem.json", None)
    (tmp_path / report).write_text(json.dumps(wrong_type), encoding="utf-8")

    with pytest.raises(HarnessError, match="unexpected Trivy v2 report type or header"):
        cmd_trivy(Namespace(action=action, report_dir=str(tmp_path)))


@pytest.mark.parametrize(
    ("configured", "arch", "variant"),
    [
        ("linux/amd64/v1", "amd64", None),
        ("linux/amd64", "amd64", "v1"),
        ("linux/x86_64", "amd64", None),
        ("linux/arm64/v8", "arm64", None),
        ("linux/arm64", "arm64", "v8"),
        ("linux/armhf", "arm", "v7"),
    ],
)
def test_explicit_platform_matches_normalized_manifest(
    configured: str,
    arch: str,
    variant: str | None,
) -> None:
    selected = "sha256:" + "b" * 64
    platform = {"os": "linux", "architecture": arch}
    if variant is not None:
        platform["variant"] = variant
    descriptors = [
        {"mediaType": _OCI_MANIFEST, "digest": selected, "platform": platform},
        {
            "mediaType": _OCI_MANIFEST,
            "digest": "sha256:" + "c" * 64,
            "platform": {
                "os": "linux",
                "architecture": arch,
                "variant": {"amd64": "v2", "arm64": "v9", "arm": "v6"}[arch],
            },
        },
    ]
    target = ProductionScanTarget("example/image@sha256:" + "a" * 64, configured)

    assert production_image_manifests(
        {"schemaVersion": 2, "manifests": descriptors},
        target,
    ) == (ProductionImageManifest(selected, "/".join(platform.values())),)
