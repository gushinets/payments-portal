"""Recovery documentation, limits and attempt-local inventory deadlines."""

from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from sqlalchemy.orm import Session

from app.composition.purchases import MAX_RELEVANT_SUBSCRIPTIONS, _inventory
from app.composition.sources import source_resources
from app.domains.billing import background_recovery
from app.domains.billing.work import URGENT_SECONDS
from app.domains.purchases.contracts import FinancialOperation
from app.infrastructure.preflight import PreflightAdmission, PreflightBudget, PreflightDeadlineExceeded, PreflightPolicy
from app.integrations.lbx.client import MAX_FINANCIAL_INVENTORY_ROWS
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from apps.api.tests.factories.reconciliation import agreement_factory, subject_factory, subscription_factory
from apps.api.tests.support.any709_step1 import step1_settings


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.anyio
async def test_cached_inventory_still_obeys_attempt_deadline() -> None:
    subject = subject_factory()
    operation = FinancialOperation(
        subject.customer.operation_id, Kind.SUBSCRIPTION, State.BOUND, "subscription-key", None, "567", None, None
    )
    purchase = replace(subject.purchase, operations=(operation,))
    budget = PreflightBudget(PreflightAdmission(PreflightPolicy(10, 0.25, 1, 0)))
    point, agreement = subscription_factory(), agreement_factory()

    def no_database() -> Session:
        raise AssertionError("own cached subscription requires no database read")

    def no_http(request: httpx.Request) -> httpx.Response:
        raise AssertionError("cached points require no source I/O")

    async with source_resources(step1_settings(), lbx_transport=httpx.MockTransport(no_http)) as sources:

        async def check() -> None:
            await _inventory(
                sources.require_lbx(),
                purchase,
                subject.customer,
                no_database,
                budget=budget,
                inventory=(point,),
                subscription_points={point.subscription_id: point},
                agreement_points={agreement.agreement_id: agreement},
            )

        await check()  # A live budget can validate the same cached points.
        budget._work_deadline = 0
        with pytest.raises(PreflightDeadlineExceeded):
            await check()


def test_billing_background_recovery_documented_contract() -> None:
    runbook = (Path(__file__).resolve().parents[3] / "docs/engineering/ANY-715-billing-operations.md").read_text()
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
        "SIMULATED",
        "NOT_RUN",
    ):
        assert policy in runbook
