"""Audited primary recovery uses relevant proof without weakening financial admission."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import resolve_review
from app.composition.backend_consumers import initialize_backend_consumers
from app.composition.purchase_inventory import collect_inventory
from app.composition.purchases import advance_purchase, confirm_purchase, recover_financial
from app.composition.sources import SourceResources
from app.core.errors import AppError
from app.domains.billing import late_purchase_reviews as late, terminal_resolution as terminal
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.errors import LbxUnavailable
from app.integrations.lbx.financial import Subscription
from app.models import AccessInvalidationOutbox, BillingProductAccessScope, ExternalSubscription, ManualReviewCase
from apps.api.tests.factories.billing_operator import resolution_request, terminal_request
from apps.api.tests.support.any709_step3 import PORTAL_TOKEN as TOKEN, PurchaseTransport
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


async def test_open_late_case_fences_first_primary_even_with_existing_binding(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, old = background_scenario
    factory = postgres_session_factory
    config = step1_settings(paid_access_clock_skew_seconds=10)
    initialize_backend_consumers(config.model_copy(update={"backend_consumers": (backend_consumer(),)}), factory)
    old = synthetic_prepare(factory, transport, old, uncertain=True)
    transport.agreements[0]["close_date"] = "2026-10-27"
    agreement, subscription = old.operations
    # The later canonical subscription must have its own identity evidence.
    transport.subscriptions.clear()
    command = terminal_request(
        factory,
        config,
        old,
        terminal.OperationEvidence(
            operation_id=agreement.id,
            outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
            external_object_id=agreement.bound_id,
        ),
        terminal.OperationEvidence(
            operation_id=subscription.id, outcome=terminal.TerminalEvidenceKind.NO_EXTERNAL_EFFECT
        ),
        confirmed=True,
    )
    terminal.resolve_purchase(factory, config, command, "os-euid:1000")
    replacement = await confirm_purchase(
        sources, config, factory=factory, token=TOKEN, key="canonical-before-dispute", meaning=old.accepted.meaning
    )
    replacement = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert replacement.held and replacement.operations[1].bound_id == "567"
    transport.agreements[0]["close_date"] = None
    independent = historical_link(factory, replacement, transport, "brief_decoder", 2)
    point = transport.subscriptions[0]
    actual_agreement = point["agreement_id"]
    point["agreement_id"] = 456
    try:
        await recover_financial(
            sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id, operation_id=old.operations[1].id
        )
    finally:
        point["agreement_id"] = actual_agreement
    for row in transport.subscriptions:
        row.update(
            state=2,
            subscription_start_date="2026-10-01",
            subscription_instance_start_date="2026-10-01",
            last_tariffication_period_start="2026-10-01",
            last_tariffication_period_end="2026-10-31",
        )
    client = sources.require_lbx()
    discover = client.discover_subscriptions

    async def omitted(
        *, user_id: int, budget: PreflightBudget, agreement_id: int | None = None
    ) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget, agreement_id=agreement_id)
        return tuple(row for row in rows if row.subscription_id != 567)

    monkeypatch.setattr(client, "discover_subscriptions", omitted)
    with factory() as db:
        sub_id = db.scalar(
            select(ExternalSubscription.subscription_id).where(
                ExternalSubscription.purchase_intent_id == replacement.id
            )
        )
        case = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).one()
        assert case.case_state == "open" and case.scope_reference == str(old.id)
        case_id = case.review_case_id
    scenario = Scenario(factory, config, transport, sources, sub_id)
    await run_inventory(scenario)
    assert {entry["product_id"] for entry in effective(factory)[1]["grants"]} == {"brief_decoder"}
    assert service.read_purchase(factory, replacement.user_id, replacement.id).held
    assert service.read_purchase(factory, independent.user_id, independent.id).held
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == replacement.accepted.selection.product_id
                )
            )
            is None
        )
        assert db.get(ManualReviewCase, case_id).case_state == "open"
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
