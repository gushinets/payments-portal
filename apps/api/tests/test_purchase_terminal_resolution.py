"""Operator completion is explicit and never inferred from empty discovery."""

from uuid import uuid4
import json
from pathlib import Path

import pytest

from app.cli import billing_purchases
from apps.api.tests.support.any709_step1 import step1_settings


def test_terminal_resolution_has_an_explicit_audited_cli_action() -> None:
    args = billing_purchases.parser().parse_args(
        [
            "resolve-purchase",
            "--user-id",
            str(uuid4()),
            "--purchase-id",
            str(uuid4()),
            "--expected-digest",
            "sha256:" + "a" * 64,
            "--reason",
            "Customer requests restart",
            "--reference",
            "LBX support case 821",
            "--evidence-file",
            "confirmation.json",
        ]
    )
    assert args.command == "resolve-purchase"
    assert args.reference == "LBX support case 821"


@pytest.mark.parametrize("invalid", ["duplicate", "incomplete", "extra", "oversized"])
def test_terminal_cli_rejects_invalid_evidence_without_opening_sources(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], invalid: str
) -> None:
    operations = [{"operation_id": str(uuid4()), "outcome": "not_sent"} for _ in range(2)]
    evidence = {"schema_version": "purchase-terminal-resolution:v1", "operations": operations}
    if invalid == "duplicate":
        operations[1] = operations[0]
    elif invalid == "incomplete":
        operations.pop()
    elif invalid == "extra":
        evidence["force"] = True
    file = tmp_path / "evidence.json"
    file.write_text(json.dumps(evidence) + (" " * 32768 if invalid == "oversized" else ""))

    def forbidden_sources(*args: object) -> None:
        pytest.fail("terminal completion must not open provider resources")

    monkeypatch.setattr(billing_purchases, "source_resources", forbidden_sources)
    monkeypatch.setattr(billing_purchases, "resolve_operator_principal", lambda: "os-euid:1000")
    monkeypatch.setattr(billing_purchases, "Settings", step1_settings)
    assert (
        billing_purchases.main(
            [
                "resolve-purchase",
                "--user-id",
                str(uuid4()),
                "--purchase-id",
                str(uuid4()),
                "--expected-digest",
                "sha256:" + "a" * 64,
                "--reason",
                "Restart",
                "--reference",
                "Support 821",
                "--evidence-file",
                str(file),
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().err) == {"detail": {"code": "purchase_resolution_arguments_invalid"}}
