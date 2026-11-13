"""PR #164: real local transactions with synthetic, product-scoped source inputs."""

import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import resolve_review
from app.core.errors import AppError
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing import paid_access, work
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.infrastructure.queries import billing_reconciliation
from app.integrations.lbx.errors import LbxAuthenticationFailed, LbxResponseInvalid, LbxUnavailable
from app.integrations.lbx.financial import Agreement, Subscription
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    BillingWorkItem,
    ExternalSubscription,
    ManualReviewCase,
    PurchasedAllowance,
)
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    synthetic_prepare,
)
from apps.api.tests.test_billing_worker_postgres import historical_link
from apps.api.tests.test_billing_scoped_inventory_postgres import (
    bound_point_relationship_scenario as bound_point_relationship_scenario,
)
from apps.api.tests.test_paid_access_rebase_postgres import effective, run_inventory
from apps.api.tests.test_paid_access_reconciliation_postgres import (
    Scenario,
    paid_source as paid_source,
    persisted,
    reconcile,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("bound_point_relationship_scenario", [False, True], indirect=True, ids=["old", "omitted"])
async def test_bound_point_tariff_refuses_audited_primary_selection(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, first, second, third, listings = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    with factory() as db:
        identity = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.purchase_intent_id == second.id)
        )
        db.add(
            BillingProductAccessScope(
                user_id=second.user_id,
                product_id=second.accepted.selection.product_id,
                primary_retired_at=datetime.now(UTC),
            )
        )
        db.commit()
    # Establish the existing audited-selection review while inventory is
    # healthy; incomplete later discovery must leave that review open.
    transport.subscriptions[0]["tariff_id"] = 701
    await run_inventory(Scenario(factory, config, transport, sources, identity))
    transport.subscriptions[0]["tariff_id"] = 702
    listings.clear()
    target = service.read_purchase(factory, second.user_id, second.id)
    request = resolution_request(target, inspect_evidence(factory, config, target.user_id, target.id)).model_copy(
        update={"resolution": "select-primary"}
    )
    with pytest.raises(AppError, match="purchase_inventory_incomplete"):
        await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    with factory() as db:
        case = db.get(ManualReviewCase, request.case_id)
        assert case.case_state == "open" and case.resolution_document is None
        scopes = {scope.product_id: scope for scope in db.scalars(select(BillingProductAccessScope))}
        assert scopes[second.accepted.selection.product_id].primary_subscription_id is None
        assert scopes[third.accepted.selection.product_id].primary_subscription_id is not None
        assert any(
            case.reason_code == "subscription_commercial_mismatch" and case.case_state == "open"
            for case in db.scalars(select(ManualReviewCase))
        )
    assert len(listings) == 2 and listings[0] == listings[1]
    assert all(req.method == "GET" for req in transport.requests)


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_retained_point_relationship_refuses_later_audited_selection(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, first, second, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    identity = service.linked_subscription_id(factory, second)
    scenario = Scenario(factory, config, transport, sources, identity)
    with factory() as db:
        db.add(
            BillingProductAccessScope(
                user_id=second.user_id, product_id="brief_decoder", primary_retired_at=datetime.now(UTC)
            )
        )
        db.commit()
    transport.subscriptions[0]["tariff_id"] = 701
    await run_inventory(scenario)  # Establish B's audited-primary review.
    transport.subscriptions[0]["tariff_id"] = 702
    await run_inventory(scenario)  # Persist the contradictory A -> B point.
    read = sources.require_lbx().get_subscription

    async def unavailable(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxUnavailable()
        return await read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", unavailable)
    target = service.read_purchase(factory, second.user_id, second.id)
    request = resolution_request(target, inspect_evidence(factory, config, target.user_id, target.id)).model_copy(
        update={"resolution": "select-primary"}
    )
    with pytest.raises(AppError, match="purchase_inventory_incomplete"):
        await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    with factory() as db:
        case = db.get(ManualReviewCase, request.case_id)
        assert case.case_state == "open" and case.resolution_document is None
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == "brief_decoder"
                )
            )
            is None
        )
    assert all(req.method == "GET" for req in transport.requests)


@pytest.mark.parametrize("less_precise", ["date", "naive", "missing"])
@pytest.mark.parametrize("recover", [False, True], ids=["reread", "block-recovery"])
async def test_proven_finite_end_survives_less_precise_complete_proof(
    paid_source: Scenario, less_precise: str, recover: bool
) -> None:
    scenario = paid_source
    end = datetime.now(UTC) + timedelta(hours=1)
    point = scenario.transport.subscriptions[0]
    point["subscription_end_date"] = end.isoformat()
    original = await reconcile(scenario)
    first = effective(scenario.factory)
    if recover:
        point["current_blocking"] = 1
        original = await reconcile(scenario)
        assert original.proof.complete  # An owned complete block can still prove the same finite end.
        assert effective(scenario.factory) == (2, {"grants": [], "allowances": []})
        point["current_blocking"] = 0
    if less_precise == "missing":
        point.pop("subscription_end_date")
    else:
        point["subscription_end_date"] = (
            end.date().isoformat() if less_precise == "date" else end.replace(tzinfo=None).isoformat()
        )
    scenario.factory.kw["bind"].dispose()  # Recovery must use persisted evidence, not session/process memory.
    current = await reconcile(scenario)
    assert current.proof.complete and current.proof.access_end_at is None
    assert effective(scenario.factory) == (3 if recover else 1, first[1])
    with scenario.factory() as db:
        scope = db.scalar(select(BillingProductAccessScope))
        assert as_utc(scope.effective_access_until) == end - timedelta(seconds=10)
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        assert as_utc(sub.projection_valid_until) > end
        saved = db.get(BillingStateObservation, current.observation_id)
        assert saved.evidence_document["access_end_at"] is None
        assert saved.evidence_document["retained_access_end"] == {
            "observation_id": str(original.observation_id),
            "access_end_at": end.isoformat(),
        }
        deadline = db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY)).one()
        assert deadline.next_attempt_at == scope.effective_access_until


@pytest.mark.parametrize("hours", [-1, 2])
async def test_explicit_complete_end_can_shorten_or_extend_prior_boundary(paid_source: Scenario, hours: int) -> None:
    scenario = paid_source
    end = datetime.now(UTC) + timedelta(hours=1)
    scenario.transport.subscriptions[0]["subscription_end_date"] = end.isoformat()
    await reconcile(scenario)
    before = effective(scenario.factory)
    revised = datetime.now(UTC) + timedelta(hours=hours)
    scenario.transport.subscriptions[0]["subscription_end_date"] = revised.isoformat()
    result = await reconcile(scenario)
    assert result.proof.complete
    revision, state = effective(scenario.factory)
    assert revision == 2
    if hours < 0:
        assert state == {"grants": [], "allowances": []}
    else:
        assert state["grants"][0]["valid_until"] == (revised - timedelta(seconds=10)).isoformat()
        assert state["allowances"] == before[1]["allowances"]


@pytest.mark.parametrize("complete", [False, True])
async def test_retained_end_uses_latest_accepted_proof_and_ignores_incomplete_extension(
    paid_source: Scenario, complete: bool
) -> None:
    scenario = paid_source
    point = scenario.transport.subscriptions[0]
    end = datetime.now(UTC) + timedelta(hours=1)
    point["subscription_end_date"] = end.isoformat()
    original = await reconcile(scenario)
    extended = end + timedelta(hours=1)
    point["subscription_end_date"] = extended.isoformat()
    price = point["total_price"]
    if not complete:
        point["total_price"] = None
    newer = await reconcile(scenario)
    assert newer.proof.complete is complete
    point["total_price"] = price
    point.pop("subscription_end_date")
    final = await reconcile(scenario)
    assert final.proof.complete
    chosen = extended if complete else end
    assert effective(scenario.factory)[1]["grants"][0]["valid_until"] == (chosen - timedelta(seconds=10)).isoformat()
    with scenario.factory() as db:
        observation = db.get(BillingStateObservation, final.observation_id)
        assert observation.evidence_document["retained_access_end"]["observation_id"] == str(
            newer.observation_id if complete else original.observation_id
        )


@pytest.mark.parametrize("overdue", [False, True])
async def test_refresh_commits_overdue_boundary_before_same_cycle_restoration(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch, overdue: bool
) -> None:
    scenario = paid_source
    await reconcile(scenario)
    before = effective(scenario.factory)
    with scenario.factory() as db:
        scope = db.scalar(select(BillingProductAccessScope))
        previous_deadline = as_utc(scope.effective_access_until)
        outbox = db.scalar(select(AccessInvalidationOutbox))
        outbox.attempt_count = 4
        outbox.delivered_revision = 1
        db.commit()
    clock = billing_reconciliation.database_now
    if overdue:
        with scenario.factory() as db:
            delta = previous_deadline + timedelta(seconds=1) - as_utc(clock(db))
        monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock(db) + delta)
    refreshed = await reconcile(scenario)
    assert refreshed.proof.complete
    assert effective(scenario.factory) == (3 if overdue else 1, before[1])
    with scenario.factory() as db:
        boundaries = list(
            db.scalars(
                select(BillingStateObservation).where(
                    BillingStateObservation.observation_kind
                    == BillingStateObservationKind.DETERMINISTIC_ACCESS_BOUNDARY
                )
            )
        )
        assert len(boundaries) == int(overdue)
        if overdue:
            assert boundaries[0].resulting_access_revision == 2
            assert as_utc(boundaries[0].effective_at) == previous_deadline
            assert db.get(BillingStateObservation, refreshed.observation_id).resulting_access_revision == 3
        outbox = db.scalar(select(AccessInvalidationOutbox))
        assert (outbox.pending_revision, outbox.delivered_revision, outbox.attempt_count) == (3 if overdue else 1, 1, 4)
        assert len(list(db.scalars(select(PurchasedAllowance)))) == 1


async def test_failure_after_overdue_reduction_rolls_back_both_phases(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = paid_source
    await reconcile(scenario)
    before = persisted(scenario.factory)
    with scenario.factory() as db:
        end = as_utc(db.scalar(select(BillingProductAccessScope.effective_access_until)))
        clock = billing_reconciliation.database_now
        delta = end + timedelta(seconds=1) - as_utc(clock(db))
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock(db) + delta)
    commit = paid_access.commit_paid_state

    def fail_after_restoration(db: Session, *args: object, **kwargs: object) -> int:
        revision = commit(db, *args, **kwargs)
        if revision == 3:
            raise RuntimeError("failure after restored paid state")
        return revision

    monkeypatch.setattr("app.domains.billing.reconciliation.commit_paid_state", fail_after_restoration)
    with pytest.raises(RuntimeError, match="failure after restored"):
        await reconcile(scenario)
    assert persisted(scenario.factory) == before


@pytest.mark.parametrize("failure", ["none", "subscription", "agreement", "budget", "auth"])
@pytest.mark.parametrize("mode", ["first_primary", "operator"])
@pytest.mark.parametrize("matching_tariff", [False, True], ids=["unrelated", "implicated"])
async def test_candidate_point_failure_is_scoped_to_its_product(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    mode: str,
    matching_tariff: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    historical_link(factory, first, transport, "brief_decoder", 1, tariff_id=702)
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31")
    config = step1_settings(paid_access_clock_skew_seconds=10)
    with factory() as db:
        identity = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.product_id == "proposal_ai")
        )
        if mode == "operator":
            db.add(
                BillingProductAccessScope(
                    user_id=first.user_id, product_id="proposal_ai", primary_retired_at=datetime.now(UTC)
                )
            )
        db.commit()
    scenario = Scenario(factory, config, transport, sources, identity)
    if mode == "operator":
        await run_inventory(scenario)
    # An agreement owner and every accepted tariff match are implicated. A
    # different tariff leaves Proposal AI genuinely unrelated to this candidate.
    extra = copy.deepcopy(transport.subscriptions[1])
    extra.update(
        subscription_id=9999, tariff_id=701 if matching_tariff else 999, state=3, outer_id="synthetic-extra-brief"
    )
    transport.subscriptions.append(extra)
    client, final_lists = sources.require_lbx(), []
    read, discover, agreement = client.get_subscription, client.discover_subscriptions, client.get_agreement
    reading_extra = False

    async def read_candidate(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        nonlocal reading_extra
        if subscription_id == 9999:
            if failure == "subscription":
                raise LbxResponseInvalid()
            if failure == "budget":
                raise PreflightDeadlineExceeded()
            if failure == "auth":
                raise LbxAuthenticationFailed()
            reading_extra = True
        return await read(subscription_id=subscription_id, budget=budget)

    async def read_agreement(*, agreement_id: int, budget: PreflightBudget) -> Agreement:
        if reading_extra and failure == "agreement":
            raise LbxResponseInvalid()
        return await agreement(agreement_id=agreement_id, budget=budget)

    async def record_listing(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        final_lists.append(user_id)
        return await discover(user_id=user_id, budget=budget)

    monkeypatch.setattr(client, "get_subscription", read_candidate)
    monkeypatch.setattr(client, "get_agreement", read_agreement)
    monkeypatch.setattr(client, "discover_subscriptions", record_listing)
    blocked = failure in {"budget", "auth"} or (matching_tariff and failure in {"subscription", "agreement"})
    if mode == "operator":
        saved = service.read_purchase(factory, first.user_id, first.id)
        evidence = inspect_evidence(factory, config, first.user_id, first.id)
        request = resolution_request(saved, evidence).model_copy(update={"resolution": "select-primary"})
        if blocked:
            with pytest.raises(AppError, match="purchase_inventory_incomplete"):
                await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
            with factory() as db:
                case = db.get(ManualReviewCase, request.case_id)
                assert case.case_state == "open" and case.resolution_document is None
        else:
            result = await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
            assert result["outcome"] == "resolved"
            with factory() as db:
                case = db.get(ManualReviewCase, request.case_id)
                assert case.resolution_document["inventory"]["complete"] is (failure == "none")
    else:
        await run_inventory(scenario)
    assert len(final_lists) == (1 if failure in {"budget", "auth"} else 2)
    granted = {grant["product_id"] for grant in effective(factory)[1]["grants"]}
    assert ("proposal_ai" in granted) is not blocked
    with factory() as db:
        scope = db.scalar(
            select(BillingProductAccessScope).where(BillingProductAccessScope.product_id == "proposal_ai")
        )
        assert (scope.primary_subscription_id is not None) is not blocked


async def test_less_precise_proof_cannot_restore_past_finite_end(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = paid_source
    end = datetime.now(UTC) + timedelta(hours=1)
    scenario.transport.subscriptions[0]["subscription_end_date"] = end.isoformat()
    await reconcile(scenario)
    scenario.transport.subscriptions[0].pop("subscription_end_date")
    clock = billing_reconciliation.database_now
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock(db) + timedelta(hours=2))
    result = await reconcile(scenario)
    assert result.proof.complete
    assert effective(scenario.factory) == (2, {"grants": [], "allowances": []})


async def test_overdue_refresh_preserves_independently_supported_product(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    historical_link(factory, first, transport, "brief_decoder", 1)
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31")
    with factory() as db:
        source_id = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.product_id == "proposal_ai")
        )
        sibling_id = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.product_id == "brief_decoder")
        )
    config = step1_settings(paid_access_clock_skew_seconds=10)
    scenario = Scenario(factory, config, transport, sources, source_id)
    sibling = Scenario(factory, config, transport, sources, sibling_id)
    await run_inventory(sibling)
    clock = billing_reconciliation.database_now
    delta = timedelta(hours=3)
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: clock(db) + delta)
    await reconcile(sibling)
    before = effective(scenario.factory)
    assert {grant["product_id"] for grant in before[1]["grants"]} == {"proposal_ai", "brief_decoder"}
    with scenario.factory() as db:
        scope = db.scalar(
            select(BillingProductAccessScope).where(BillingProductAccessScope.product_id == "proposal_ai")
        )
        delta = as_utc(scope.effective_access_until) + timedelta(seconds=1) - as_utc(clock(db))
    await reconcile(scenario)
    assert effective(scenario.factory) == (before[0] + 2, before[1])


async def test_first_primary_retains_its_own_end_without_borrowing_sibling_history(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    historical_link(factory, first, transport, "brief_decoder", 1)
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31")
    with factory() as db:
        identity = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.product_id == "proposal_ai")
        )
    config = step1_settings(paid_access_clock_skew_seconds=10)
    scenario = Scenario(factory, config, transport, sources, identity)
    end = datetime.now(UTC) + timedelta(hours=1)
    transport.subscriptions[0]["subscription_end_date"] = end.isoformat()
    basis = await reconcile(scenario)
    assert effective(factory) == (0, {"grants": [], "allowances": []})
    transport.subscriptions[0].pop("subscription_end_date")
    await run_inventory(scenario)
    grants = {item["product_id"]: item["valid_until"] for item in effective(factory)[1]["grants"]}
    assert grants == {"proposal_ai": (end - timedelta(seconds=10)).isoformat(), "brief_decoder": None}
    with factory() as db:
        selection = db.scalars(
            select(BillingStateObservation).where(
                BillingStateObservation.observation_kind == BillingStateObservationKind.PRIMARY_SELECTION,
                BillingStateObservation.product_id == "proposal_ai",
            )
        ).one()
        assert selection.evidence_document["retained_access_end"]["observation_id"] == str(basis.observation_id)
