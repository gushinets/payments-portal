"""Audited primary recovery uses relevant proof without weakening financial admission."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import resolve_review
from app.composition.backend_consumers import initialize_backend_consumers
from app.composition.purchase_inventory import collect_inventory
from app.core.errors import AppError
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseInventoryIncomplete
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.errors import LbxUnavailable
from app.integrations.lbx.financial import Subscription
from app.models import AccessInvalidationOutbox, BillingProductAccessScope, ExternalSubscription, ManualReviewCase
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.backend_consumers import backend_consumer
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    synthetic_prepare,
)
from apps.api.tests.test_billing_worker_postgres import historical_link
from apps.api.tests.test_paid_access_rebase_postgres import effective, run_inventory
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    "unrelated_incomplete,retired,refusal",
    [
        (False, False, None),
        (True, False, None),
        (False, True, None),
        (True, True, None),
        (True, True, "related_incomplete"),
        (True, True, "inventory_unavailable"),
    ],
)
async def test_primary_resolution_requires_complete_relevant_product(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    unrelated_incomplete: bool,
    retired: bool,
    refusal: str | None,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    second = historical_link(factory, first, transport, "brief_decoder", 1)
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31")
    if unrelated_incomplete:
        transport.subscriptions[0]["total_price"] = None
    config = step1_settings(paid_access_clock_skew_seconds=10)
    initialize_backend_consumers(config.model_copy(update={"backend_consumers": (backend_consumer(),)}), factory)
    with factory() as db:
        identity = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.product_id == "brief_decoder")
        )
        if retired:
            db.add(
                BillingProductAccessScope(
                    user_id=second.user_id, product_id="brief_decoder", primary_retired_at=datetime.now(UTC)
                )
            )
        db.commit()
    await run_inventory(Scenario(factory, config, transport, sources, identity))
    if unrelated_incomplete:
        customer = service.customer_for_purchase(factory, config, second)
        async with sources.billing.operation(bound_scope=False) as budget:
            inventory = await collect_inventory(
                sources.require_lbx(), sources.billing, config, factory=factory, customer=customer, budget=budget
            )
        assert not inventory.complete
        inventory.require_clear(second, original=True, primary=True)
        # A product-complete primary proof cannot authorize financial CREATE,
        # restore-original or bind-original against incomplete customer proof.
        for original in (False, True):
            with pytest.raises(PurchaseInventoryIncomplete):
                inventory.require_clear(second, original=original)
    if not retired:
        assert any(grant["product_id"] == "brief_decoder" for grant in effective(factory)[1]["grants"])
        return
    saved = service.read_purchase(factory, second.user_id, second.id)
    evidence = inspect_evidence(factory, config, second.user_id, second.id)
    request = resolution_request(saved, evidence).model_copy(update={"resolution": "select-primary"})
    assert any(case["reason"] == "primary_selection_required" for case in evidence["reviews"])
    if refusal == "related_incomplete":
        transport.subscriptions[1]["total_price"] = None
    elif refusal == "inventory_unavailable":

        async def unavailable(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
            raise LbxUnavailable()

        monkeypatch.setattr(sources.require_lbx(), "discover_subscriptions", unavailable)
    before = len(transport.requests)
    if refusal:
        with pytest.raises(AppError):
            await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    else:
        result = await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
        assert result["outcome"] == "resolved"
    granted = {grant["product_id"] for grant in effective(factory)[1]["grants"]}
    assert ("brief_decoder" in granted) is (refusal is None)
    with factory() as db:
        case = db.get(ManualReviewCase, request.case_id)
        scope = db.scalar(
            select(BillingProductAccessScope).where(BillingProductAccessScope.product_id == "brief_decoder")
        )
        assert case.case_state == ("open" if refusal else "resolved")
        assert scope.primary_subscription_id == (None if refusal else identity)
        if not refusal:
            assert case.resolved_by_principal == "os-euid:1000"
            assert case.resolution_document["inventory"]["complete"] is (not unrelated_incomplete)
            assert case.resolution_document["inventory"]["primary_product"]["complete"]
            assert db.scalar(select(AccessInvalidationOutbox)).pending_revision == effective(factory)[0]
    assert all(request.method == "GET" for request in transport.requests[before:])
