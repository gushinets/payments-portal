"""Paid review visibility stays scoped and does not grant resolution authority."""

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.composition.billing_operator import resolve_review
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseRefused
from app.models import ExternalSubscription, ManualReviewCase
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.test_any709_subscription_inventory_postgres import add_external_subscription
from apps.api.tests.test_paid_access_rebase_postgres import (
    inventory_scenario as inventory_scenario,
    run_inventory,
)
from apps.api.tests.test_paid_access_reconciliation_postgres import (
    Scenario,
    paid_source as paid_source,
    reconcile,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("scope", ["product_competitor", "subscription_metric"])
async def test_paid_reviews_are_visible_but_do_not_authorize_original_resolution(
    inventory_scenario: Scenario, scope: str
) -> None:
    scenario = inventory_scenario
    await run_inventory(scenario)
    if scope == "product_competitor":
        add_external_subscription(scenario.transport, 2)
        await run_inventory(scenario)
    else:
        scenario.transport.subscriptions[0]["last_tariffication_period_end"] = "2026-09-01"
        await reconcile(scenario)
    with scenario.factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        user_id, purchase_id = sub.user_id, sub.purchase_intent_id
        case = db.scalars(select(ManualReviewCase)).one()
        assert case.scope_kind == scope and case.case_state == "open"
        case_id = str(case.review_case_id)
        # Another access scope and a different subscription must stay invisible.
        for kind, reference in (
            ("product_competitor", str(uuid4())),
            ("subscription_metric", f"{uuid4()}:proposal_ai.test_generations"),
            ("subscription_metric", f"{sub.subscription_id}0:proposal_ai.test_generations"),
        ):
            db.add(
                ManualReviewCase(
                    reason_code="unrelated-review",
                    scope_kind=kind,
                    scope_reference=reference,
                    evidence_schema_version="v1",
                    evidence_document={},
                    case_state="open",
                )
            )
        db.commit()
    evidence = inspect_evidence(scenario.factory, scenario.config, user_id, purchase_id)
    assert [row["review_case_id"] for row in evidence["reviews"]] == [case_id]
    assert evidence["reviews"][0]["expected_case_digest"].startswith("sha256:")
    purchase = service.read_purchase(scenario.factory, user_id, purchase_id)
    request = resolution_request(purchase, evidence)
    with pytest.raises(PurchaseRefused, match="billing_review_unrelated_cases"):
        await resolve_review(
            scenario.sources,
            scenario.config,
            factory=scenario.factory,
            request=request,
            principal="os-euid:1000",
        )
    assert inspect_evidence(scenario.factory, scenario.config, user_id, purchase_id)["reviews"] == evidence["reviews"]


async def test_cycle_review_history_remains_visible_after_automatic_original_cycle_recovery(
    paid_source: Scenario,
) -> None:
    scenario = paid_source
    await reconcile(scenario)
    end = scenario.transport.subscriptions[0]["last_tariffication_period_end"]
    scenario.transport.subscriptions[0]["last_tariffication_period_end"] = "2026-09-01"
    await reconcile(scenario)
    with scenario.factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        user_id, purchase_id = sub.user_id, sub.purchase_intent_id
    before = inspect_evidence(scenario.factory, scenario.config, user_id, purchase_id)
    assert before["reviews"][0]["state"] == "open"
    scenario.transport.subscriptions[0]["last_tariffication_period_end"] = end
    await reconcile(scenario)
    after = inspect_evidence(scenario.factory, scenario.config, user_id, purchase_id)
    assert after["reviews"][0]["review_case_id"] == before["reviews"][0]["review_case_id"]
    assert after["reviews"][0]["state"] == "resolved"
