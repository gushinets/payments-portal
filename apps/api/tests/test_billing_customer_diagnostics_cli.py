"""Small operator interface: diagnosis only and safe JSON failure output."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.cli import billing_customers
from app.domains.billing.contracts import BillingRefused
from apps.api.tests.support.any709_step1 import step1_settings


@pytest.mark.parametrize("extra", [["repair"], ["diagnose", "--apply"], ["diagnose", "--provider-customer-id", "345"]])
def test_customer_cli_rejects_mutation_switches(extra: list[str]) -> None:
    with pytest.raises(SystemExit) as error:
        billing_customers.parser().parse_args([*extra, "--user-id", str(uuid4())])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "diagnosis,exit_status", [("binding_verified", 0), ("not_provisioned", 0), ("email_conflict", 2)]
)
def test_customer_cli_json_and_exit_status(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], diagnosis: str, exit_status: int
) -> None:
    async def diagnose(*args: object, **kwargs: object) -> dict[str, object]:
        return {"diagnosis": diagnosis}

    monkeypatch.setattr(billing_customers, "diagnose_customer", diagnose)
    monkeypatch.setattr(billing_customers, "Settings", step1_settings)
    monkeypatch.setattr(billing_customers, "resolve_operator_principal", lambda: "os-euid:1000")
    assert billing_customers.main(["diagnose", "--user-id", str(uuid4())]) == exit_status
    assert diagnosis in capsys.readouterr().out


def test_customer_cli_returns_safe_error(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    async def diagnose(*args: object, **kwargs: object) -> dict[str, object]:
        raise BillingRefused("billing_customer_user_not_found", 404)

    monkeypatch.setattr(billing_customers, "diagnose_customer", diagnose)
    monkeypatch.setattr(billing_customers, "Settings", step1_settings)
    monkeypatch.setattr(billing_customers, "resolve_operator_principal", lambda: "os-euid:1000")
    assert billing_customers.main(["diagnose", "--user-id", str(uuid4())]) == 1
    assert capsys.readouterr().err.strip() == '{"detail": {"code": "billing_customer_user_not_found"}}'
