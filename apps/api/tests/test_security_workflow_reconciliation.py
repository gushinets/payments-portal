from __future__ import annotations

import json
import re
from argparse import Namespace
from pathlib import Path

import pytest
import yaml

from scripts import repo


ROOT = Path(__file__).resolve().parents[3]


def workflow_steps() -> list[dict]:
    workflow = yaml.safe_load((ROOT / ".github/workflows/security.yml").read_text(encoding="utf-8"))
    return workflow["jobs"]["trivy"]["steps"]


def test_reconciliation_retains_both_security_contracts() -> None:
    names = {step["name"] for step in workflow_steps()}
    assert {
        "Scan production PostgreSQL image",
        "Scan production Caddy image",
        "Verify required Trivy reports",
        "Verify scanned API image PostgreSQL readiness and migration cycle",
        "Verify API deployment privilege and excluded-tool boundaries",
        "Compare API privilege hardening with one vulnerability database",
    } <= names


def test_actual_api_inventory_destination_does_not_break_strict_redaction(tmp_path: Path) -> None:
    step = next(s for s in workflow_steps() if s["name"] == "Collect production API component evidence")
    match = re.search(r'"\$TRIVY_REPORT_DIR/([^"]+)"', step["run"])
    assert match is not None
    inventory = tmp_path / match[1]
    inventory.parent.mkdir(parents=True, exist_ok=True)
    inventory.write_text(json.dumps({"complete": True, "uid": 999}), encoding="utf-8")
    scan = tmp_path / "api-image.json"
    scan.write_text(
        json.dumps(
            {
                "SchemaVersion": 2,
                "ArtifactType": "container_image",
                "ArtifactName": "api",
                "Metadata": {"ImageID": "sha256:" + "1" * 64},
                "Results": [
                    {
                        "Target": "api",
                        "Class": "secret",
                        "Secrets": [{"Severity": "HIGH", "Match": "CANARY", "Code": {"Lines": ["CANARY"]}}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    repo.cmd_trivy(Namespace(action="redact", report_dir=str(tmp_path)))
    assert "CANARY" not in scan.read_text()
    assert json.loads(inventory.read_text()) == {"complete": True, "uid": 999}


def test_comparison_upload_requires_successful_scoped_redaction() -> None:
    steps = workflow_steps()
    upload = next(s for s in steps if s["name"] == "Retain sanitized API comparison evidence")
    redactor = next(s for s in steps if s.get("id") == "redact_comparison")
    assert redactor["if"] == "always()"
    assert redactor["run"].endswith(".harness/any674-comparison/reports")
    assert "steps.redact_comparison.outcome == 'success'" in upload["if"]
    assert steps.index(redactor) < steps.index(upload)


@pytest.mark.parametrize(
    "step_name",
    [
        "Verify scanned API image PostgreSQL readiness and migration cycle",
        "Collect production API component evidence",
        "Verify API deployment privilege and excluded-tool boundaries",
        "Simulate API package removal options without changing packages",
        "Check supported Debian candidates in disposable build base",
    ],
)
def test_non_trivy_api_evidence_uses_its_own_directory(step_name: str) -> None:
    step = next(s for s in workflow_steps() if s["name"] == step_name)
    paths = re.findall(r'\$TRIVY_REPORT_DIR/([^"\s]+\.json)', step["run"])
    for path in paths:
        if path != "api-build-base.json":
            assert path.startswith("api-evidence/")
