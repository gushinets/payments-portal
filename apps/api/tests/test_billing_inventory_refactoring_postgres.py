"""Inventory ordering and product isolation through actual PostgreSQL writers."""

import asyncio
from copy import deepcopy
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.composition.reconciliation import read_subscription_proof, reconcile_subscription
from app.domains.billing.discovery import apply_inventory, persist_discoveries
from app.domains.billing.inventory_history import (
    LEGACY_INVENTORY_RELATIONSHIP_SCHEMA,
    retain_candidate_relationship,
    retained_subscription_relationships,
)
from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation, read_source_time
from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    IdentityProof,
    ReadInterval,
    SubscriptionProof,
    SubscriptionRelationship,
)
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import PurchaseInventoryIncomplete
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.errors import LbxAuthenticationFailed, LbxScopeForbidden, LbxUnavailable
from app.integrations.lbx.financial import Subscription
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    BillingWorkItem,
    ExternalCreateOperationKind as Kind,
    ManualReviewCase,
    PurchaseIntentState,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.factories.original_operation import advance_deadlines, financial_claim_clock
from apps.api.tests.test_billing_scoped_inventory_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    bound_point_relationship_scenario as bound_point_relationship_scenario,
    inventory,
)
from apps.api.tests.test_paid_access_rebase_postgres import claim_inventory
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario
from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("bound_point_relationship_scenario", [False], indirect=True)
@pytest.mark.parametrize("concurrent", [False, True], ids=["serial-control", "new-fact-after-full-proof"])
async def test_new_discovery_fact_survives_a_previous_full_point(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    concurrent: bool,
) -> None:
    transport, sources, first, _, third, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    client = sources.require_lbx()
    read, discover = client.get_subscription, client.discover_subscriptions
    first_id, third_id = (service.linked_subscription_id(factory, item) for item in (first, third))
    transport.subscriptions[0]["tariff_id"] = 701
    captured, completed = asyncio.Event(), asyncio.Event()

    async def delegate(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        result = await run_in_threadpool(fn, *args, **kwargs)
        if fn is retained_subscription_relationships and args[1].id == first.id and concurrent:
            captured.set()
            await completed.wait()
        return result

    async def newer_point() -> None:
        await captured.wait()
        result = await reconcile_subscription(
            client, sources.billing, config, factory=factory, subscription_id=first_id
        )
        assert result.proof.complete and result.proof.identity == IdentityProof.MATCH
        assert result.proof.point_relationship == SubscriptionRelationship("456", 701)
        completed.set()

    async def conflicting_listing(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        if concurrent:
            assert completed.is_set()
        return tuple(
            row.model_copy(update={"tariff_id": 703}) if row.subscription_id == 567 else row
            for row in await discover(user_id=user_id, budget=budget)
        )

    monkeypatch.setattr(client, "discover_subscriptions", conflicting_listing)
    if concurrent:
        initial, _ = await asyncio.wait_for(
            asyncio.gather(inventory(sources, factory, first, delegate=delegate), newer_point()), timeout=60
        )
    else:
        initial = await inventory(sources, factory, first, delegate=delegate)
    assert not next(item for item in initial.products if item.product_id == "acceptance_builder").complete

    async def unavailable(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxUnavailable()
        return await read(subscription_id=subscription_id, budget=budget)

    async def omitted(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        return tuple(row for row in await discover(user_id=user_id, budget=budget) if row.subscription_id != 567)

    monkeypatch.setattr(client, "get_subscription", unavailable)
    monkeypatch.setattr(client, "discover_subscriptions", omitted)
    claim = claim_inventory(Scenario(factory, config, transport, sources, third_id))
    result = await inventory(sources, factory, first, claim=claim)
    result = persist_discoveries(factory, claim, result)
    apply_inventory(factory, claim, result, "inventory_incomplete", clock_skew_seconds=10)
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == "acceptance_builder"
                )
            )
            is None
        )


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
@pytest.mark.parametrize("change", ["unrelated-tariff", "operation-review", "terminal-owner-review", "queue-hint"])
async def test_other_product_change_preserves_valid_primary_and_retry(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    change: str,
) -> None:
    transport, sources, first, second, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    first_id, second_id = (service.linked_subscription_id(factory, item) for item in (first, second))
    transport.subscriptions[0]["tariff_id"] = 701
    if change != "queue-hint":
        transport.subscriptions[0]["services"][0]["price"] = 15
    if change == "terminal-owner-review":
        extra = deepcopy(transport.subscriptions[1])
        extra.update(subscription_id=9999, agreement_id=456, state=3)
        transport.subscriptions.append(extra)
    claim = claim_inventory(Scenario(factory, config, transport, sources, second_id))
    result = await inventory(sources, factory, first, claim=claim)
    result = persist_discoveries(factory, claim, result)
    assert next(item for item in result.products if item.product_id == "brief_decoder").complete
    if change in {"operation-review", "terminal-owner-review"}:
        current = service.read_purchase(factory, first.user_id, first.id)
        operation = next(op for op in current.operations if op.kind == Kind.SUBSCRIPTION)
        financial.financial_pending(factory, current, operation, conflict=True)
    else:
        if change == "unrelated-tariff":
            transport.subscriptions[0]["tariff_id"] = 999
        await reconcile_subscription(
            sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=first_id
        )
    apply_inventory(factory, claim, result, None, clock_skew_seconds=10)
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == "brief_decoder"
                )
            )
            == second_id
        )
        queue = db.get(BillingWorkItem, claim.id)
        assert queue.work_state == "pending" and queue.lease_owner is None
        if change == "queue-hint":
            assert queue.enqueue_generation > claim.generation and queue.priority == 1
        else:
            assert queue.last_error_classification == "inventory_incomplete"


@pytest.mark.parametrize("bound_point_relationship_scenario", [False], indirect=True)
@pytest.mark.parametrize("lifecycle", [2, 999], ids=["known-control", "unknown-lifecycle"])
async def test_candidate_normalization_failure_does_not_block_an_unrelated_product(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    lifecycle: int,
) -> None:
    transport, sources, first, second, _, listings = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    transport.subscriptions[0]["tariff_id"] = 701
    extra = deepcopy(transport.subscriptions[0])
    extra.update(subscription_id=9999, state=lifecycle)
    transport.subscriptions.append(extra)
    second_id = service.linked_subscription_id(factory, second)
    claim = claim_inventory(Scenario(factory, config, transport, sources, second_id))
    result = await inventory(sources, factory, first, claim=claim)
    result.require_clear(second, primary=True)
    if lifecycle == 999:
        with pytest.raises(PurchaseInventoryIncomplete):
            result.require_clear(second)
    result = persist_discoveries(factory, claim, result)
    apply_inventory(factory, claim, result, "inventory_incomplete", clock_skew_seconds=10)
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == "brief_decoder"
                )
            )
            == second_id
        )
    assert len(listings) == 2
    assert all(request.method == "GET" for request in transport.requests)


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
@pytest.mark.parametrize("failure", [LbxAuthenticationFailed, LbxScopeForbidden])
async def test_canonical_authentication_failure_keeps_discovery_globally_incomplete(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: type[LbxAuthenticationFailed | LbxScopeForbidden],
) -> None:
    transport, sources, first, second, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    transport.subscriptions[0]["tariff_id"] = 701
    client = sources.require_lbx()
    read = client.get_subscription

    async def denied(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise failure()
        return await read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(client, "get_subscription", denied)
    claim = claim_inventory(
        Scenario(factory, config, transport, sources, service.linked_subscription_id(factory, second))
    )
    result = persist_discoveries(factory, claim, await inventory(sources, factory, first, claim=claim))
    with pytest.raises(PurchaseInventoryIncomplete):
        result.require_clear(second, primary=True)
    apply_inventory(factory, claim, result, "inventory_incomplete", clock_skew_seconds=10)
    with factory() as db:
        assert all(scope.primary_subscription_id is None for scope in db.scalars(select(BillingProductAccessScope)))


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
@pytest.mark.parametrize("timing", ["older-late", "newer", "overlap", "rediscovered", "equal-boundary"])
async def test_only_a_provably_later_full_read_clears_a_relationship(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    timing: str,
) -> None:
    transport, sources, first, _, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings()
    transport.subscriptions[0]["tariff_id"] = 701
    await inventory(sources, factory, first)
    history = retained_subscription_relationships(factory, first)
    client = sources.require_lbx()
    read = client.get_subscription
    relationship = SubscriptionRelationship("456", 703)

    async def restriction() -> ReadInterval:
        transport.subscriptions[0]["tariff_id"] = 703
        started = read_source_time(factory)
        async with sources.billing.operation(bound_scope=False) as budget:
            point = await read(subscription_id=567, budget=budget)
        interval = ReadInterval(started, read_source_time(factory))
        assert point.tariff_id == 703
        transport.subscriptions[0]["tariff_id"] = 701
        return interval

    if timing in {"older-late", "rediscovered"}:
        interval = await restriction()
        if timing == "rediscovered":
            history = retain_candidate_relationship(factory, first, history, relationship, interval)
    if timing == "overlap":
        captured, release = asyncio.Event(), asyncio.Event()

        async def held_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
            point = await read(subscription_id=subscription_id, budget=budget)
            captured.set()
            await release.wait()
            return point

        monkeypatch.setattr(client, "get_subscription", held_point)
        subject = claim_reconciliation(factory, config, history.subscription_id, io_timeout_seconds=60)

        async def proof_read() -> SubscriptionProof:
            async with sources.billing.operation(bound_scope=False) as budget:
                return await read_subscription_proof(client, subject, config, factory=factory, budget=budget)

        task = asyncio.create_task(proof_read())
        await asyncio.wait_for(captured.wait(), timeout=60)
        interval = await restriction()
        release.set()
        proof = await asyncio.wait_for(task, timeout=60)
        assert proof.read_started_at < interval.started_at <= interval.finished_at < proof.read_finished_at
        result = apply_reconciliation(factory, subject, proof)
    else:
        result = await reconcile_subscription(
            client, sources.billing, config, factory=factory, subscription_id=history.subscription_id
        )
    assert result.proof.complete
    if timing in {"newer", "rediscovered"}:
        interval = await restriction()
        assert result.proof.read_finished_at < interval.started_at
    if timing == "equal-boundary":
        interval = ReadInterval(result.proof.read_started_at, result.proof.read_started_at)
    retain_candidate_relationship(factory, first, history, relationship, interval)
    current = retained_subscription_relationships(factory, first)
    assert (relationship in current.relationships) == (timing != "older-late")


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_legacy_supplement_cannot_clear_facts_and_fresh_proof_recovers(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, first, _, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings()
    transport.subscriptions[0]["tariff_id"] = 701
    initial = await inventory(sources, factory, first)
    source = next(item for item in initial.sources if item.purchase.id == first.id)
    history = retained_subscription_relationships(factory, first)
    started = read_source_time(factory)
    transport.subscriptions[0]["tariff_id"] = 702
    async with sources.billing.operation(bound_scope=False) as budget:
        await sources.require_lbx().get_subscription(subscription_id=567, budget=budget)
    retain_candidate_relationship(
        factory, first, history, SubscriptionRelationship("456", 702), ReadInterval(started, read_source_time(factory))
    )
    transport.subscriptions[0]["tariff_id"] = 701
    with factory() as db:
        original = db.get(BillingStateObservation, source.observation_id)
        document = {
            "identity": "match",
            "complete": True,
            "point_relationship": {"agreement_id": "456", "tariff_id": 703},
            "provenance": original.evidence_document["provenance"],
        }
        db.add(
            BillingStateObservation(
                observation_kind=BillingStateObservationKind.TARGET_PRODUCT_DISCOVERY,
                external_billing_account_id=first.account_id,
                user_id=first.user_id,
                product_id=first.accepted.selection.product_id,
                access_scope_id=original.access_scope_id,
                subscription_id=history.subscription_id,
                observed_at=read_source_time(factory),
                evidence_schema_version=LEGACY_INVENTORY_RELATIONSHIP_SCHEMA,
                evidence_document=document,
                completeness_classification="complete",
                result_classification="candidate_proof",
            )
        )
        db.commit()
    assert set(retained_subscription_relationships(factory, first).relationships) == {
        SubscriptionRelationship("456", tariff) for tariff in (701, 702, 703)
    }
    await reconcile_subscription(
        sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=history.subscription_id
    )
    assert retained_subscription_relationships(factory, first).relationships == (SubscriptionRelationship("456", 701),)


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_lost_inventory_lease_rolls_back_primary_selection(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.domains.billing.contracts import BillingRefused
    from apps.api.tests.test_paid_access_rebase_postgres import effective

    transport, sources, first, second, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    transport.subscriptions[0]["tariff_id"] = 701
    claim = claim_inventory(
        Scenario(factory, config, transport, sources, service.linked_subscription_id(factory, second))
    )
    result = await inventory(sources, factory, first, claim=claim)
    result = persist_discoveries(factory, claim, result)
    before = effective(factory)
    with factory() as db:
        db.get(BillingWorkItem, claim.id).lease_expires_at = datetime(2020, 1, 1, tzinfo=UTC)
        db.commit()
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        apply_inventory(factory, claim, result, None, clock_skew_seconds=10)
    assert effective(factory) == before
    with factory() as db:
        assert all(scope.primary_subscription_id is None for scope in db.scalars(select(BillingProductAccessScope)))


@pytest.mark.parametrize("change", ["send-window", "candidate"])
async def test_new_possible_external_effect_invalidates_all_product_decisions(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    change: str,
) -> None:
    from app.domains.purchases.inventory_contracts import InventoryStale

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    first = synthetic_prepare(factory, transport, purchase, uncertain=True)
    second = historical_link(factory, first, transport, "brief_decoder", 1, tariff_id=702)
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31")
    claim = claim_inventory(
        Scenario(factory, config, transport, sources, service.linked_subscription_id(factory, second))
    )
    result = await inventory(sources, factory, first, claim=claim)
    result = persist_discoveries(factory, claim, result)
    assert next(item for item in result.products if item.product_id == "brief_decoder").complete
    # Locate A explicitly: customer snapshots need not use creation order.
    operation = next(
        op for item in result.purchases if item.id == first.id for op in item.operations if op.kind == Kind.SUBSCRIPTION
    )
    with factory() as db:
        recovery = db.scalar(
            select(BillingWorkItem).where(
                BillingWorkItem.work_kind == "external_create_recovery",
                BillingWorkItem.coalescing_key == str(operation.id),
            )
        )
        assert recovery is not None
        if change == "send-window":
            # A repeated send can return to the same UNKNOWN state; its active window differs.
            recovery.active_recovery_deadline_at += timedelta(seconds=1)
        else:
            recovery.payload_document = {**recovery.payload_document, "candidate_id": "9999"}
        db.commit()
    with pytest.raises(InventoryStale):
        apply_inventory(factory, claim, result, None, clock_skew_seconds=10)
    with factory() as db:
        assert all(scope.primary_subscription_id is None for scope in db.scalars(select(BillingProductAccessScope)))


@pytest.mark.parametrize("tariff_id", [701, 702], ids=["shared-tariff", "distinct-tariff"])
@pytest.mark.parametrize("review", ["after-inventory", "before-inventory", "commercial-mismatch"])
async def test_review_of_a_conclusive_bound_sibling_does_not_block_primary(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    tariff_id: int,
    review: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    second = historical_link(factory, first, transport, "brief_decoder", 1, tariff_id=tariff_id)
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31")
    second_id = service.linked_subscription_id(factory, second)

    def open_operation_review() -> None:
        current = service.read_purchase(factory, first.user_id, first.id)
        operation = next(op for op in current.operations if op.kind == Kind.SUBSCRIPTION)
        financial.financial_pending(factory, current, operation, conflict=True)

    if review == "commercial-mismatch":
        point = transport.subscriptions[0]
        original_price = point["services"][0]["price"]
        point["services"][0]["price"] = 15
        negative = await reconcile_subscription(
            sources.require_lbx(),
            sources.billing,
            config,
            factory=factory,
            subscription_id=service.linked_subscription_id(factory, first),
        )
        assert negative.proof.commercial == CommercialProof.MISMATCH
        assert negative.purchase.state == PurchaseIntentState.MANUAL_REVIEW
        point["services"][0]["price"] = original_price
    elif review == "before-inventory":
        open_operation_review()
    claim = claim_inventory(Scenario(factory, config, transport, sources, second_id))
    result = persist_discoveries(factory, claim, await inventory(sources, factory, first, claim=claim))
    source = next(item for item in result.sources if item.purchase.id == first.id)
    assert source.proof.complete
    assert source.proof.identity == IdentityProof.MATCH
    assert source.proof.commercial == CommercialProof.MATCH
    assert source.proof.point_relationship == SubscriptionRelationship(
        next(op.bound_id for op in first.operations if op.kind == Kind.AGREEMENT), first.accepted.selection.tariff_id
    )
    product = next(item for item in result.products if item.product_id == "brief_decoder")
    assert product.complete and len(product.candidates) == 1
    assert product.candidates[0].purchase_id == second.id
    if review == "after-inventory":
        open_operation_review()
    with factory() as db:
        open_cases = set(
            db.scalars(select(ManualReviewCase.review_case_id).where(ManualReviewCase.case_state == "open"))
        )
        assert open_cases
    apply_inventory(factory, claim, result, None, clock_skew_seconds=10)
    assert service.read_purchase(factory, first.user_id, first.id).state == PurchaseIntentState.MANUAL_REVIEW
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == "brief_decoder"
                )
            )
            == second_id
        )
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == first.accepted.selection.product_id
                )
            )
            is None
        )
        assert all(db.get(ManualReviewCase, identity).case_state == "open" for identity in open_cases)


async def test_actual_deadline_review_does_not_cancel_an_independent_primary(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domains.billing import background_recovery
    from app.models import ExternalCreateOperation

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    past = datetime.now(UTC) - timedelta(hours=3)
    with monkeypatch.context() as clock:
        financial_claim_clock(clock, lambda: past)
        clock.setattr(financial, "utc_now", lambda: past)
        first = synthetic_prepare(factory, transport, purchase, uncertain=True)
    second = historical_link(factory, first, transport, "brief_decoder", 1, tariff_id=702)
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31")
    discover = sources.require_lbx().discover_subscriptions

    async def omitted(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        return tuple(row for row in await discover(user_id=user_id, budget=budget) if row.subscription_id != 567)

    monkeypatch.setattr(sources.require_lbx(), "discover_subscriptions", omitted)
    second_id = service.linked_subscription_id(factory, second)
    claim = claim_inventory(Scenario(factory, config, transport, sources, second_id))
    # claim_inventory postpones other jobs; restore the real pending deadline.
    operation = next(op for op in first.operations if op.kind == Kind.SUBSCRIPTION)
    with factory() as db:
        background_recovery.enroll_operation(db, db.get(ExternalCreateOperation, operation.id), first.account_id)
        db.commit()
    result = persist_discoveries(factory, claim, await inventory(sources, factory, first, claim=claim))
    assert service.read_purchase(factory, first.user_id, first.id).state != "manual_review"
    assert advance_deadlines(factory, now=datetime.now(UTC)) == 1
    assert service.read_purchase(factory, first.user_id, first.id).state == "manual_review"
    apply_inventory(factory, claim, result, None, clock_skew_seconds=10)
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == "brief_decoder"
                )
            )
            == second_id
        )


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_changed_receipt_of_an_implicated_sibling_defers_its_conflicts(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, first, second, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    extra = deepcopy(transport.subscriptions[1])
    extra.update(subscription_id=9999)
    transport.subscriptions.append(extra)
    claim = claim_inventory(
        Scenario(factory, config, transport, sources, service.linked_subscription_id(factory, second))
    )
    result = persist_discoveries(factory, claim, await inventory(sources, factory, first, claim=claim))
    assert second.id in result.conflicts
    product = next(item for item in result.products if item.product_id == "brief_decoder")
    assert any(item.purchase_id == first.id and item.subscription_id is not None for item in product.candidates)
    await reconcile_subscription(
        sources.require_lbx(),
        sources.billing,
        config,
        factory=factory,
        subscription_id=service.linked_subscription_id(factory, first),
    )
    apply_inventory(factory, claim, result, "inventory_conflict", clock_skew_seconds=10)
    assert service.read_purchase(factory, first.user_id, second.id).state == "linked"
    with factory() as db:
        assert db.get(BillingWorkItem, claim.id).last_error_classification == "inventory_incomplete"


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_legacy_canonical_history_keeps_its_product_implication(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, first, _, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings()
    transport.subscriptions[0]["tariff_id"] = 701
    initial = await inventory(sources, factory, first)
    source = next(item for item in initial.sources if item.purchase.id == first.id)
    transport.subscriptions[0]["tariff_id"] = 703

    async def unavailable_policy(*args: Any, **kwargs: Any) -> Any:
        raise LbxUnavailable()

    monkeypatch.setattr(sources.require_lbx(), "get_tariff", unavailable_policy)
    subject = claim_reconciliation(factory, config, source.subject.subscription_id, io_timeout_seconds=60)
    async with sources.billing.operation(bound_scope=False) as budget:
        proof = await read_subscription_proof(sources.require_lbx(), subject, config, factory=factory, budget=budget)
    assert not proof.complete and proof.point_relationship == SubscriptionRelationship("456", 703)
    with factory() as db:
        original = db.get(BillingStateObservation, source.observation_id)
        # Append historical v1 evidence; immutable existing observations are never rewritten.
        document = proof.document()
        document["provenance"] = {**original.evidence_document["provenance"], "fence": subject.fence}
        db.add(
            BillingStateObservation(
                observation_kind=BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ,
                external_billing_account_id=first.account_id,
                user_id=first.user_id,
                product_id=first.accepted.selection.product_id,
                access_scope_id=original.access_scope_id,
                subscription_id=subject.subscription_id,
                observed_at=proof.read_finished_at,
                evidence_schema_version="subscription-reconciliation:v1",
                evidence_document=document,
                completeness_classification="incomplete",
                result_classification="INCOMPLETE",
            )
        )
        db.commit()
    assert SubscriptionRelationship("456", 703) in retained_subscription_relationships(factory, first).relationships
