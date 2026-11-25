"""CLI authorization, option contracts, safe failures and entrypoint dispatch."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.cli import billing_purchases as cli
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.operator_contracts import ResolutionRequest
from app.domains.billing.terminal_resolution import TerminalRequest, TerminalResult
from app.domains.billing.late_purchase_reviews import ClosureRequest
from app.domains.catalog.mapping_evidence import MappingRefused
from app.composition.mapping_operator import resolve_operator_principal
from app.core.settings import Settings
from app.models import PurchaseIntentState
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


def test_operation_lookup_requires_os_access_and_uses_no_source_resources(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    identity = uuid4()

    def forbidden(*args: object) -> None:
        raise AssertionError("operation lookup opened source resources")

    def inspect(factory: object, configuration: Settings, operation_id: object) -> dict:
        assert operation_id == identity
        return {"create_operation_id": str(identity)}

    monkeypatch.setattr(cli, "source_resources", forbidden)
    monkeypatch.setattr(cli, "inspect_operation", inspect)
    monkeypatch.setattr(cli, "Settings", step1_settings)
    monkeypatch.setattr(cli, "resolve_operator_principal", lambda: "os-euid:1000")
    assert cli.main(["inspect-operation", "--operation-id", str(identity)]) == 0
    assert json.loads(capsys.readouterr().out)["operator_principal"] == "os-euid:1000"

    def denied() -> str:
        raise MappingRefused("mapping_operator_identity_unavailable")

    monkeypatch.setattr(cli, "resolve_operator_principal", denied)
    assert cli.main(["inspect-operation", "--operation-id", str(identity)]) == 1
    assert "mapping_operator_identity_unavailable" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        cli.parser().parse_args(["inspect-operation"])


def test_operation_lookup_harness_forwards_only_its_operation_reference(monkeypatch: pytest.MonkeyPatch) -> None:
    identity = str(uuid4())
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(repo, "direct_api_environment", lambda: {})
    monkeypatch.setattr(repo.subprocess, "run", run)
    arguments = repo.build_parser().parse_args(["billing-purchase", "inspect-operation", "--operation-id", identity])
    with pytest.raises(SystemExit) as outcome:
        arguments.func(arguments)
    assert outcome.value.code == 0
    assert calls == [
        [repo.sys.executable, "-m", "app.cli.billing_purchases", "inspect-operation", "--operation-id", identity]
    ]


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "duplicate",
        "incomplete",
        "extra",
        "wrong_object",
        "oversized",
        "case_closure",
        "case_without_confirmation",
        "unsupported_case_outcome",
    ],
)
def test_terminal_evidence_is_local_to_the_operator_cli(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    user_id, purchase_id = uuid4(), uuid4()
    review_case_id = uuid4()
    closing = case in {"case_closure", "case_without_confirmation", "unsupported_case_outcome"}
    operations = [{"operation_id": str(uuid4()), "outcome": "not_sent"} for _ in range(2)]
    evidence: dict[str, object] = {"operations": operations}
    if case == "duplicate":
        operations[1] = operations[0]
    elif case == "incomplete":
        operations.pop()
    elif case == "extra":
        evidence["force"] = True
    elif case == "wrong_object":
        operations[0]["external_object_id"] = "456"
    if closing:
        evidence = {"outcome": "external_terminal", "external_object_id": "456"}
        if case == "unsupported_case_outcome":
            evidence["outcome"] = "canonical_binding"
        if case == "case_closure":
            evidence["confirmed_at"] = "2026-11-23T00:00:00Z"
    (tmp_path / "confirmation.json").write_text(
        json.dumps(evidence) + (" " * 32768 if case == "oversized" else ""), encoding="utf-8"
    )

    def resolve(factory: object, config: Settings, request: TerminalRequest, principal: str) -> TerminalResult:
        assert case == "valid" and request.user_id == user_id and request.purchase_id == purchase_id
        assert principal == "os-euid:1000" and request.reference == "ANY-821"
        return TerminalResult(
            review_case_id=uuid4(),
            purchase_intent_id=purchase_id,
            state=PurchaseIntentState.RESOLVED_NO_EXTERNAL_EFFECT,
            already_resolved=False,
        )

    def close(factory: object, config: Settings, request: ClosureRequest, principal: str) -> TerminalResult:
        assert case == "case_closure" and request.case_id == review_case_id
        assert request.evidence.external_object_id == "456" and principal == "os-euid:1000"
        return TerminalResult(
            review_case_id=review_case_id,
            purchase_intent_id=purchase_id,
            state=PurchaseIntentState.RESOLVED_NO_EXTERNAL_EFFECT,
            already_resolved=False,
        )

    def run(command: list[str], *, cwd: Path, **kwargs: object) -> SimpleNamespace:
        assert "--evidence-file" in command and Path(command[-1]).is_absolute()
        monkeypatch.chdir(cwd)
        return SimpleNamespace(returncode=cli.main(command[3:]))

    def forbidden(*args: object) -> None:
        pytest.fail("terminal completion must not open source resources")

    monkeypatch.setattr(cli, "source_resources", forbidden)
    monkeypatch.setattr(cli, "resolve_operator_principal", lambda: "os-euid:1000")
    monkeypatch.setattr(cli, "Settings", step1_settings)
    monkeypatch.setattr(cli, "resolve_purchase", resolve)
    monkeypatch.setattr(cli, "close_case", close)
    monkeypatch.setattr(repo, "direct_api_environment", lambda: {})
    monkeypatch.setattr(repo.subprocess, "run", run)
    monkeypatch.chdir(tmp_path)
    arguments = repo.build_parser().parse_args(
        [
            "billing-purchase",
            "resolve-purchase",
            "--user-id",
            str(user_id),
            "--purchase-id",
            str(purchase_id),
            "--expected-digest",
            "sha256:" + "a" * 64,
            "--reason",
            "Restart",
            "--reference",
            "ANY-821",
            "--evidence-file",
            "confirmation.json",
            *(["--case-id", str(review_case_id)] if closing else []),
        ]
    )
    with pytest.raises(SystemExit) as outcome:
        arguments.func(arguments)
    output = capsys.readouterr()
    if case in {"valid", "case_closure"}:
        assert outcome.value.code == 0
        assert json.loads(output.out)["state"] == "resolved_no_external_effect"
    else:
        assert outcome.value.code == 1
        assert json.loads(output.err) == {"detail": {"code": "purchase_resolution_arguments_invalid"}}


@pytest.mark.parametrize("action", ["inspect-invalidation", "retry-invalidation"])
def test_invalidation_harness_forwards_user_and_recipient(monkeypatch: pytest.MonkeyPatch, action: str) -> None:
    user_id = str(uuid4())
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(repo, "direct_api_environment", lambda: {})
    monkeypatch.setattr(repo.subprocess, "run", run)
    arguments = repo.build_parser().parse_args(
        [
            "billing-purchase",
            action,
            "--user-id",
            user_id,
            "--recipient-id",
            "platform-kernel",
        ]
    )
    with pytest.raises(SystemExit) as outcome:
        arguments.func(arguments)
    assert outcome.value.code == 0
    assert len(calls) == 1
    forwarded = cli.parser().parse_args(calls[0][3:])
    assert forwarded.command == action
    assert str(forwarded.user_id) == user_id
    assert forwarded.recipient_id == "platform-kernel"


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
    text = (ROOT / "docs/engineering/billing-background-operations.md").read_text()
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
        "billing_worker_delivery_concurrency",
        "billing_worker_io_timeout_seconds",
        "billing_worker_scan_batch_size",
    ):
        default = str(Settings.model_fields[field].default).lower()
        assert f"`{field.upper()}={default}`" in text
    for term in (
        "restore-original",
        "bind-original",
        "billing-operator-resolution:v1",
        "projection_valid_until",
        "release-terminal",
        "Polling-only operation",
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


def test_billing_recovery_cli_select_primary_uses_reconciliation_expectations() -> None:
    request = ResolutionRequest.model_validate({**request_factory().model_dump(), "resolution": "select-primary"})
    args = cli.parser().parse_args(arguments(request))
    assert args.resolution == "select-primary"
    assert args.expected_observation_id == request.expected_observation_id
    wrapper = repo.build_parser().parse_args(["billing-purchase", *arguments(request)])
    assert wrapper.resolution == "select-primary" and wrapper.expected_observation_id == request.expected_observation_id
    invalid = {**request.model_dump(), "expected_observation_id": None}
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ResolutionRequest.model_validate(invalid)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires a POSIX FIFO")
def test_terminal_evidence_refuses_a_fifo_without_waiting_for_a_writer(tmp_path: Path) -> None:
    fifo = tmp_path / "evidence"
    os.mkfifo(fifo)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.cli.billing_purchases",
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
            "ANY-821",
            "--evidence-file",
            str(fifo),
        ],
        cwd=ROOT / "apps/api",
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert json.loads(result.stderr) == {"detail": {"code": "purchase_resolution_arguments_invalid"}}
