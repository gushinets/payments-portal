"""Primary selection consumes shared inventory receipts, never a second fact writer."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.composition.billing_background import inventory_customer
from app.composition.purchase_inventory import collect_inventory
from app.domains.billing.discovery import apply_inventory
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.discovery import DISCOVERY_SCHEMA, persist_discoveries
from app.domains.billing.work_contracts import WorkClaim, WorkLane
from app.domains.purchases.inventory_contracts import InventoryResult, InventoryStale
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalSubscription,
    ManualReviewCase,
    PaidAccessState,
    PurchasedAllowance,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
)
from apps.api.tests.test_paid_access_reconciliation_postgres import (
    Scenario,
    paid_source as paid_source,
    reconcile,
)
from apps.api.tests.test_any709_subscription_inventory_postgres import add_external_subscription
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    synthetic_prepare,
)
from apps.api.tests.test_billing_worker_postgres import historical_link
from apps.api.tests.support.any709_step1 import step1_settings

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def inventory_scenario(paid_source: Scenario) -> Scenario:
    with paid_source.factory() as db:
        db.scalar(select(BillingProductAccessScope)).primary_subscription_id = None
        db.commit()
    return paid_source


def effective(factory: sessionmaker[Session]) -> tuple[int, dict]:
    with factory() as db:
        state = db.scalar(select(PaidAccessState))
        return (
            (state.access_revision, state.effective_state_document) if state else (0, {"grants": [], "allowances": []})
        )


def claim_inventory(scenario: Scenario) -> WorkClaim:
    with scenario.factory() as db:
        # Select the existing customer job deterministically, through the real claim path.
        db.execute(
            update(BillingWorkItem)
            .where(BillingWorkItem.work_kind != recovery.INVENTORY)
            .values(next_attempt_at=datetime.now(UTC) + timedelta(days=10))
        )
        recovery.hint_inventory(db, db.scalar(select(ExternalBillingCustomer)))
        db.commit()
    claim = work.claim_work(scenario.factory, scenario.config, WorkLane.URGENT)
    assert claim and claim.kind == recovery.INVENTORY
    return claim


async def run_inventory(scenario: Scenario, claim: WorkClaim | None = None) -> None:
    claim = claim or claim_inventory(scenario)
    async with scenario.sources.billing.operation(bound_scope=False) as budget:
        await inventory_customer(
            scenario.sources.require_lbx(),
            scenario.sources.billing,
            scenario.config,
            factory=scenario.factory,
            claim=claim,
            budget=budget,
            delegate=run_in_threadpool,
        )


async def collect(scenario: Scenario, claim: WorkClaim) -> InventoryResult:
    customer, _ = recovery.customer_snapshot(scenario.factory, scenario.config, UUID(claim.reference))
    async with scenario.sources.billing.operation(bound_scope=False) as budget:
        return await collect_inventory(
            scenario.sources.require_lbx(),
            scenario.sources.billing,
            scenario.config,
            factory=scenario.factory,
            customer=customer,
            budget=budget,
            work_claim=claim,
        )


async def test_eligible_proof_hints_inventory_and_primary_uses_committed_receipt(inventory_scenario: Scenario) -> None:
    scenario = inventory_scenario
    scenario.transport.requests.clear()
    await reconcile(scenario)
    assert effective(scenario.factory)[0] == 0
    assert not any(request.url.path.endswith("/subscriptions") for request in scenario.transport.requests)
    with scenario.factory() as db:
        job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == recovery.INVENTORY))
        assert job.priority == 1 and job.work_state == "pending"
    scenario.transport.requests.clear()
    await run_inventory(scenario)
    revision, document = effective(scenario.factory)
    assert revision == 1 and document["allowances"][0]["quantity"] == 100
    counts = Counter(request.url.path for request in scenario.transport.requests)
    assert counts["/api/rest/v1/subscriptions/567"] == 1
    assert counts["/api/rest/v1/subscriptions"] == 2
    with scenario.factory() as db:
        scope = db.scalar(select(BillingProductAccessScope))
        source = db.get(ExternalSubscription, scenario.subscription_id)
        selected = db.get(BillingStateObservation, scope.access_basis_observation_id)
        discovery = db.get(BillingStateObservation, selected.basis_observation_id)
        assert scope.primary_subscription_id == scenario.subscription_id
        assert selected.observation_kind == "primary_selection" and selected.resulting_access_revision == 1
        assert discovery.evidence_schema_version == DISCOVERY_SCHEMA
        candidate = discovery.evidence_document["candidates"][0]
        assert candidate["observation_id"] == str(source.latest_observation_id)
        assert candidate["fence"] == source.reconciliation_fencing_token
        original = db.get(BillingStateObservation, source.latest_observation_id)
        assert source.last_authoritative_read_at.isoformat() == original.evidence_document["read_started_at"]
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == 1
    before = effective(scenario.factory)
    await reconcile(scenario)
    assert effective(scenario.factory) == before


@pytest.mark.parametrize("missing", ["price", "lifecycle", "lease"])
async def test_incomplete_relevant_proof_never_selects_first_primary(
    inventory_scenario: Scenario, missing: str
) -> None:
    scenario = inventory_scenario
    if missing == "price":
        scenario.transport.subscriptions[0]["total_price"] = None
    elif missing == "lifecycle":
        scenario.transport.subscriptions[0]["state"] = None
    else:
        with scenario.factory() as db:
            sub = db.get(ExternalSubscription, scenario.subscription_id)
            sub.reconciliation_lease_owner = "another-owner"
            sub.reconciliation_lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
            db.commit()
    await run_inventory(scenario)
    assert effective(scenario.factory)[0] == 0
    with scenario.factory() as db:
        assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) is None
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0


@pytest.mark.parametrize("selected", [False, True])
@pytest.mark.parametrize("foreign_first", [False, True])
async def test_newcomer_cannot_replace_or_restrict_existing_primary(
    inventory_scenario: Scenario,
    selected: bool,
    foreign_first: bool,
) -> None:
    scenario = inventory_scenario
    if selected:
        await run_inventory(scenario)
    before = effective(scenario.factory)
    add_external_subscription(scenario.transport, 2)
    if foreign_first:
        scenario.transport.subscriptions.reverse()
    await run_inventory(scenario)
    assert effective(scenario.factory) == before
    with scenario.factory() as db:
        scope = db.scalar(select(BillingProductAccessScope))
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        if selected:
            assert scope.primary_subscription_id == scenario.subscription_id
            assert sub.commercial_access_status == "eligible" and sub.financial_access_status == "allowed"
            case = db.scalars(select(ManualReviewCase)).one()
            assert case.scope_kind == "product_competitor" and case.reason_code == "customer_inventory_competitor"
        else:
            assert scope.primary_subscription_id is None
            assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0
    if selected:
        await reconcile(scenario)
        assert effective(scenario.factory) == before


async def test_hidden_local_source_is_unioned_with_discovered_candidates(inventory_scenario: Scenario) -> None:
    scenario = inventory_scenario
    with scenario.factory() as db:
        original = db.get(ExternalSubscription, scenario.subscription_id)
        db.add(
            ExternalSubscription(
                subscription_id=uuid4(),
                customer_id=original.customer_id,
                user_id=original.user_id,
                external_billing_account_id=original.external_billing_account_id,
                product_id=original.product_id,
                external_subscription_id="888",
                external_agreement_id="888",
                lifecycle_status=Lifecycle.ACTIVE,
                financial_access_status=Financial.UNVERIFIED,
                commercial_access_status=Commercial.ELIGIBLE,
                last_authoritative_read_at=datetime.now(UTC),
                projection_valid_until=datetime.now(UTC),
            )
        )
        db.commit()
    await run_inventory(scenario)
    assert effective(scenario.factory)[0] == 0
    with scenario.factory() as db:
        assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) is None


async def test_retired_primary_never_promotes_an_old_candidate(inventory_scenario: Scenario) -> None:
    scenario = inventory_scenario
    with scenario.factory() as db:
        db.scalar(select(BillingProductAccessScope)).primary_retired_at = datetime.now(UTC)
        db.commit()
    await run_inventory(scenario)
    assert effective(scenario.factory)[0] == 0
    with scenario.factory() as db:
        assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) is None
        assert db.scalars(select(ManualReviewCase)).one().reason_code == "primary_selection_required"


async def test_newer_source_fence_rejects_persisted_selection_receipt(inventory_scenario: Scenario) -> None:
    scenario = inventory_scenario
    claim = claim_inventory(scenario)
    result = persist_discoveries(scenario.factory, claim, await collect(scenario, claim))
    from app.composition.reconciliation import reconcile_subscription

    await reconcile_subscription(
        scenario.sources.require_lbx(),
        scenario.sources.billing,
        scenario.config,
        factory=scenario.factory,
        subscription_id=scenario.subscription_id,
        work_claim=claim,
    )
    with pytest.raises(InventoryStale):
        apply_inventory(scenario.factory, claim, result, None, clock_skew_seconds=10)
    assert effective(scenario.factory)[0] == 0


async def test_primary_change_during_inventory_cannot_become_fresh_selection(inventory_scenario: Scenario) -> None:
    scenario = inventory_scenario
    claim = claim_inventory(scenario)
    result = persist_discoveries(scenario.factory, claim, await collect(scenario, claim))
    with scenario.factory() as db:
        db.scalar(select(BillingProductAccessScope)).primary_retired_at = datetime.now(UTC)
        db.commit()
    apply_inventory(scenario.factory, claim, result, None, clock_skew_seconds=10)
    assert effective(scenario.factory)[0] == 0


async def test_other_product_binding_in_review_does_not_compete_for_eligible_product(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    historical_link(factory, first, transport, "brief_decoder", 1, tariff_id=702)
    transport.subscriptions[0]["services"][0]["price"] = 15
    transport.subscriptions[1].update(
        state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31"
    )
    with factory() as db:
        identity = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.product_id == "brief_decoder")
        )
    scenario = Scenario(factory, step1_settings(paid_access_clock_skew_seconds=10), transport, sources, identity)
    await run_inventory(scenario)
    _, document = effective(factory)
    assert document["grants"] == [{"product_id": "brief_decoder", "valid_until": None}]
    with factory() as db:
        scopes = {
            scope.product_id: scope.primary_subscription_id for scope in db.scalars(select(BillingProductAccessScope))
        }
        assert scopes == {"proposal_ai": None, "brief_decoder": identity}
    await run_inventory(scenario)
    assert effective(factory)[1] == document


async def test_primary_discovery_uses_database_clock_when_application_clock_lags(
    inventory_scenario: Scenario,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.queries import billing_reconciliation

    scenario = inventory_scenario
    database_now = billing_reconciliation.database_now
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: database_now(db) + timedelta(seconds=5))
    await run_inventory(scenario)
    assert effective(scenario.factory)[0] == 1
    with scenario.factory() as db:
        scope = db.scalar(select(BillingProductAccessScope))
        selected = db.get(BillingStateObservation, scope.access_basis_observation_id)
        discovery = db.get(BillingStateObservation, selected.basis_observation_id)
        assert discovery.evidence_schema_version == DISCOVERY_SCHEMA
        document = discovery.evidence_document
        assert (
            datetime.fromisoformat(document["read_started_at"])
            <= datetime.fromisoformat(document["read_finished_at"])
            <= selected.observed_at
        )


@pytest.mark.parametrize("omitted", [False, True])
async def test_known_sibling_on_another_dedicated_agreement_never_selects_first_primary(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    omitted: bool,
) -> None:
    from app.integrations.lbx.financial import Subscription
    from app.models import PurchaseIntent, PurchaseIntentState

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    second = historical_link(factory, first, transport, "brief_decoder", 1)
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31")
    transport.subscriptions[1].update(agreement_id=456, tariff_id=999)
    if omitted:
        discover = sources.require_lbx().discover_subscriptions

        async def omit_known(**kwargs: object) -> tuple[Subscription, ...]:
            return tuple(row for row in await discover(**kwargs) if row.subscription_id != 568)

        monkeypatch.setattr(sources.require_lbx(), "discover_subscriptions", omit_known)
    with factory() as db:
        identity = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.product_id == "proposal_ai")
        )
    scenario = Scenario(factory, step1_settings(paid_access_clock_skew_seconds=10), transport, sources, identity)
    await run_inventory(scenario)
    assert effective(factory) == (0, {"grants": [], "allowances": []})
    with factory() as db:
        assert all(scope.primary_subscription_id is None for scope in db.scalars(select(BillingProductAccessScope)))
        assert all(
            db.get(PurchaseIntent, saved.id).state == PurchaseIntentState.MANUAL_REVIEW for saved in (first, second)
        )
        discoveries = list(
            db.scalars(
                select(BillingStateObservation).where(
                    BillingStateObservation.evidence_schema_version == DISCOVERY_SCHEMA
                )
            )
        )
        assert len(discoveries) == 2
        assert all(not item.evidence_document["complete"] for item in discoveries)
