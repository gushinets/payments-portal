"""CLI authorization, option contracts, safe failures and entrypoint dispatch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.cli import billing_purchases as cli
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.operator_contracts import ResolutionRequest
from app.domains.catalog.mapping_evidence import MappingRefused
from app.composition.mapping_operator import resolve_operator_principal
from app.core.settings import Settings
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.factories.reconciliation import subject_factory
from apps.api.tests.support.any709_step1 import step1_settings
from scripts import repo

ROOT = Path(__file__).resolve().parents[3]


def request_factory() -> ResolutionRequest:
    purchase = subject_factory().purchase
    return resolution_request(
        purchase,
        {
            "reviews": [
                {"state": "open", "review_case_id": str(uuid4()), "expected_case_digest": "sha256:" + "a" * 64}
            ],
            "subscription": {"supporting_observation_id": str(uuid4()), "reconciliation_fence": 1},
        },
    )


def arguments(request: ResolutionRequest) -> list[str]:
    return [
        "resolve-review",
        *(
            part
            for key, value in request.model_dump(mode="json").items()
            if value is not None
            for part in ("--" + key.replace("_", "-"), str(value))
        ),
    ]


@pytest.mark.parametrize("command", ["release-terminal", "force-release", "mark-paid", "rebind"])
def test_billing_recovery_cli_has_no_unsafe_command(command: str) -> None:
    with pytest.raises(SystemExit):
        cli.parser().parse_args([command, "--user-id", str(uuid4()), "--purchase-id", str(uuid4())])


@pytest.mark.parametrize("field", ["reason", "reference", "expected_observation_id", "expected_reconciliation_fence"])
def test_billing_recovery_cli_requires_valid_resolution_expectations(
    field: str, capsys: pytest.CaptureFixture[str]
) -> None:
    request = request_factory()
    request = request.model_copy(update={field: " " if field in {"reason", "reference"} else None})
    assert cli.main(arguments(request)) == 1
    assert "billing_review_arguments_invalid" in capsys.readouterr().err


@pytest.mark.parametrize("command", ["inspect", "recover", "reconcile", "resolve-review"])
def test_billing_recovery_cli_requires_os_principal_before_execution(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    def fail() -> str:
        raise MappingRefused("mapping_operator_identity_unavailable")

    monkeypatch.setattr(cli, "resolve_operator_principal", fail)
    args = (
        arguments(request_factory())
        if command == "resolve-review"
        else [command, "--user-id", str(uuid4()), "--purchase-id", str(uuid4())]
    )
    assert cli.main(args) == 1
    assert "mapping_operator_identity_unavailable" in capsys.readouterr().err


def test_billing_recovery_cli_os_identity_failure() -> None:
    def fail() -> int:
        raise OSError("PRIVATE")

    with pytest.raises(MappingRefused, match="mapping_operator_identity_unavailable"):
        resolve_operator_principal(resolve_uid=fail)


@pytest.mark.parametrize("command", ["inspect", "recover", "reconcile", "resolve-review"])
def test_billing_recovery_cli_dispatches_shared_use_cases(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    calls = []

    def inspect(*args: object) -> dict:
        calls.append("inspect")
        return {"scope_held": True}

    async def recover(*args: object, **kwargs: object) -> None:
        calls.append("recover")

    async def reconcile(*args: object, **kwargs: object) -> None:
        calls.append("reconcile")

    async def resolve(*args: object, **kwargs: object) -> dict:
        calls.append("resolve-review")
        assert kwargs["principal"] == "os-euid:1000"
        return {"outcome": "resolved"}

    monkeypatch.setattr(cli, "inspect_evidence", inspect)
    monkeypatch.setattr(cli, "recover_financial", recover)
    monkeypatch.setattr(cli, "reconcile_purchase", reconcile)
    monkeypatch.setattr(cli, "resolve_review", resolve)
    monkeypatch.setattr(cli, "Settings", step1_settings)
    monkeypatch.setattr(cli, "resolve_operator_principal", lambda: "os-euid:1000")
    args = (
        arguments(request_factory())
        if command == "resolve-review"
        else [command, "--user-id", str(uuid4()), "--purchase-id", str(uuid4())]
    )
    assert cli.main(args) == 0
    assert calls == ([command, "inspect"] if command in {"recover", "reconcile"} else [command])
    assert json.loads(capsys.readouterr().out)["operator_principal"] == "os-euid:1000"


def test_billing_recovery_cli_inspect_opens_no_source_resources(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def forbidden(*args: object) -> None:
        raise AssertionError("inspect opened source resources")

    monkeypatch.setattr(cli, "source_resources", forbidden)
    monkeypatch.setattr(cli, "inspect_evidence", lambda *args: {})
    monkeypatch.setattr(cli, "Settings", step1_settings)
    monkeypatch.setattr(cli, "resolve_operator_principal", lambda: "os-euid:1000")
    assert cli.main(["inspect", "--user-id", str(uuid4()), "--purchase-id", str(uuid4())]) == 0


def test_billing_recovery_cli_safe_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def fail(*args: object) -> None:
        raise BillingRefused("billing_review_stale", 409)

    monkeypatch.setattr(cli, "inspect_evidence", fail)
    monkeypatch.setattr(cli, "Settings", step1_settings)
    monkeypatch.setattr(cli, "resolve_operator_principal", lambda: "os-euid:1000")
    assert cli.main(["inspect", "--user-id", str(uuid4()), "--purchase-id", str(uuid4())]) == 1
    assert json.loads(capsys.readouterr().err) == {"detail": {"code": "billing_review_stale"}}


def subparsers(parser: argparse.ArgumentParser) -> dict:
    return next(action.choices for action in parser._actions if isinstance(action, argparse._SubParsersAction))


def test_billing_recovery_cli_runbook_parser_and_settings_contract() -> None:
    text = (ROOT / "docs/engineering/ANY-715-billing-operations.md").read_text()
    actions = subparsers(cli.parser())
    wrapper = subparsers(repo.build_parser())["billing-purchase"]
    assert set(next(action.choices for action in wrapper._actions if action.dest == "action")) == set(actions)
    wrapper_options = {option for action in wrapper._actions for option in action.option_strings}
    for name, parser in actions.items():
        assert f"`{name}`" in text
        for action in parser._actions:
            for option in action.option_strings:
                if option not in {"-h", "--help"}:
                    assert option in text and option in wrapper_options
    for field in (
        "billing_worker_enabled",
        "billing_worker_urgent_concurrency",
        "billing_worker_normal_concurrency",
        "billing_worker_io_timeout_seconds",
        "billing_worker_scan_batch_size",
    ):
        default = str(Settings.model_fields[field].default).lower()
        assert f"`{field.upper()}={default}`" in text
    for term in (
        "restore-original",
        "bind-original",
        "billing-operator-resolution:v1",
        "Step 9 handoff",
        "release-terminal",
        "DISABLED/POLLING-ONLY",
        "queue age",
        "per-process",
        "last_progress_at",
    ):
        assert term in text


def test_billing_recovery_cli_unexpected_failure_is_reported_once_without_raw_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    reports = []

    def fail(*args: object) -> None:
        raise RuntimeError("PRIVATE token and payload")

    monkeypatch.setattr(cli, "inspect_evidence", fail)
    monkeypatch.setattr(cli, "Settings", step1_settings)
    monkeypatch.setattr(cli, "resolve_operator_principal", lambda: "os-euid:1000")
    monkeypatch.setattr(cli, "report_exception", lambda error, **kwargs: reports.append(kwargs))
    assert cli.main(["inspect", "--user-id", str(uuid4()), "--purchase-id", str(uuid4())]) == 1
    assert len(reports) == 1
    assert json.loads(capsys.readouterr().err) == {"detail": {"code": "purchase_internal_error"}}
