"""Operational documentation stays tied to shared recovery kinds and limits."""

from pathlib import Path

from app.domains.billing import background_recovery
from app.domains.billing.work import URGENT_SECONDS
from app.integrations.lbx.client import MAX_FINANCIAL_INVENTORY_ROWS
from app.composition.purchases import MAX_RELEVANT_SUBSCRIPTIONS


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
