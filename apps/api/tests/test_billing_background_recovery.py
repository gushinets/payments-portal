"""Recovery documentation, limits and attempt-local inventory deadlines."""

from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from app.composition.purchase_inventory import MAX_RELEVANT_SUBSCRIPTIONS, collect_inventory
from app.composition.sources import source_resources
from app.domains.billing import background_recovery
from app.domains.billing.work import URGENT_SECONDS
from app.infrastructure.preflight import PreflightAdmission, PreflightBudget, PreflightDeadlineExceeded, PreflightPolicy
from app.integrations.lbx.client import MAX_FINANCIAL_INVENTORY_ROWS
from apps.api.tests.factories.reconciliation import subject_factory
from apps.api.tests.support.any709_step1 import step1_settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_inventory_obeys_attempt_deadline_before_claims() -> None:
    subject = subject_factory()
    budget = PreflightBudget(PreflightAdmission(PreflightPolicy(10, 0.25, 1, 0)))

    def no_database() -> Session:
        raise AssertionError("an expired inventory must not claim or read")

    def no_http(request: httpx.Request) -> httpx.Response:
        raise AssertionError("an expired inventory must not read sources")

    async with source_resources(step1_settings(), lbx_transport=httpx.MockTransport(no_http)) as sources:
        budget._work_deadline = 0
        with pytest.raises(PreflightDeadlineExceeded):
            await collect_inventory(
                sources.require_lbx(),
                sources.billing,
                step1_settings(),
                factory=no_database,
                customer=subject.customer,
                budget=budget,
            )


def test_billing_background_recovery_documented_contract() -> None:
    runbook = (Path(__file__).resolve().parents[3] / "docs/engineering/billing-background-operations.md").read_text()
    for kind in (background_recovery.RECOVERY, background_recovery.DEADLINE, background_recovery.INVENTORY):
        assert f"`{kind}`" in runbook
    assert f"fewer than {MAX_FINANCIAL_INVENTORY_ROWS}" in runbook
    assert f"most {MAX_RELEVANT_SUBSCRIPTIONS}" in runbook
    assert URGENT_SECONDS == 5 * 60
    assert background_recovery.INVENTORY_SECONDS == 6 * 60 * 60
    for policy in (
        "unknown_since + 2h",
        "PROVEN_NOT_SENT",
        "billing_busy",
        "customer-send:",
        "customer-inventory:v1",
        "customer_inventory_conflict",
        "proposal_ai",
        "brief_decoder",
        "DISABLED/POLLING-ONLY",
    ):
        assert policy in runbook
