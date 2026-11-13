"""Retained point history must remain current through the final primary writer."""

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.composition import billing_operator
from app.composition.billing_operator import resolve_review
from app.composition.reconciliation import read_subscription_proof, reconcile_subscription
from app.domains.billing.discovery import apply_inventory, persist_discoveries
from app.domains.billing.inventory_history import retain_inventory_relationship, retained_subscription_relationships
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation, read_source_time
from app.domains.billing.reconciliation_contracts import ReadInterval, ReconciliationResult, SubscriptionRelationship
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseInventoryIncomplete, PurchaseRefused
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.errors import LbxUnavailable
from app.integrations.lbx.financial import Subscription
from app.models import BillingProductAccessScope, BillingStateObservation, ExternalSubscription, ManualReviewCase
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_scoped_inventory_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    bound_point_relationship_scenario as bound_point_relationship_scenario,
    inventory,
)
from apps.api.tests.test_paid_access_rebase_postgres import claim_inventory, run_inventory
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("bound_point_relationship_scenario", [False], indirect=True)
@pytest.mark.parametrize(
    "relationship_source", ["terminal", "agreement-unavailable", "discovery-first", "discovery-final"]
)
async def test_inventory_relationship_survives_next_failed_scan(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    relationship_source: str,
) -> None:
    transport, sources, first, _, third, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    client = sources.require_lbx()
    read, agreement_read, discover = client.get_subscription, client.get_agreement, client.discover_subscriptions
    first_id, third_id = (service.linked_subscription_id(factory, item) for item in (first, third))
    scenario = Scenario(factory, config, transport, sources, third_id)
    point_reads = 0
    listing_reads = 0
    discovery_only = relationship_source.startswith("discovery-")
    if discovery_only:
        transport.subscriptions[0]["tariff_id"] = 701

    async def changing_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        nonlocal point_reads
        point = await read(subscription_id=subscription_id, budget=budget)
        if subscription_id == 567:
            point_reads += 1
            if not discovery_only:
                point = point.model_copy(
                    update={
                        "agreement_id": 457 if point_reads == 1 else 458,
                        "tariff_id": 702 if point_reads == 1 else 703,
                        "state": 3 if point_reads > 1 and relationship_source == "terminal" else 2,
                    }
                )
        return point

    async def unavailable_agreement(*, agreement_id: int, budget: PreflightBudget) -> Any:
        if agreement_id == 458 and point_reads >= 2 and relationship_source == "agreement-unavailable":
            raise LbxUnavailable()
        return await agreement_read(agreement_id=agreement_id, budget=budget)

    async def conflicting_listing(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        nonlocal listing_reads
        listing_reads += 1
        rows = await discover(user_id=user_id, budget=budget)
        conflict = listing_reads == (1 if relationship_source == "discovery-first" else 2)
        return tuple(
            row.model_copy(update={"tariff_id": 703}) if row.subscription_id == 567 and conflict else row
            for row in rows
        )

    monkeypatch.setattr(client, "get_subscription", changing_point)
    monkeypatch.setattr(client, "get_agreement", unavailable_agreement)
    if discovery_only:
        monkeypatch.setattr(client, "discover_subscriptions", conflicting_listing)
    await run_inventory(scenario)
    assert point_reads == (1 if discovery_only else 2)

    async def unavailable_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxUnavailable()
        return await read(subscription_id=subscription_id, budget=budget)

    async def omitted_listing(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        return tuple(row for row in await discover(user_id=user_id, budget=budget) if row.subscription_id != 567)

    monkeypatch.setattr(client, "get_subscription", unavailable_point)
    monkeypatch.setattr(client, "get_agreement", agreement_read)
    monkeypatch.setattr(client, "discover_subscriptions", omitted_listing)
    claim = claim_inventory(scenario)
    result = await inventory(sources, factory, first, claim=claim)
    result = persist_discoveries(factory, claim, result)
    apply_inventory(factory, claim, result, "inventory_incomplete", clock_skew_seconds=10)
    with factory() as db:
        primary = db.scalar(
            select(BillingProductAccessScope.primary_subscription_id).where(
                BillingProductAccessScope.product_id == third.accepted.selection.product_id
            )
        )
        assert primary is None
    assert not next(
        product for product in result.products if product.product_id == third.accepted.selection.product_id
    ).complete
    # A fresh complete owned point clears old restrictions even while A's
    # separate commercial/identity review remains open.
    transport.subscriptions[0]["tariff_id"] = 701
    monkeypatch.setattr(client, "get_subscription", read)
    await run_inventory(scenario)
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == third.accepted.selection.product_id
                )
            )
            == third_id
        )
    assert service.linked_subscription_id(factory, first) == first_id
    assert all(request.method == "GET" for request in transport.requests)


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
@pytest.mark.parametrize("late_poll", ["unrelated-unavailable", "unrelated-same-point", "selected-unavailable"])
async def test_primary_receipt_is_strict_but_unrelated_relationships_are_semantic(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    late_poll: str,
) -> None:
    transport, sources, first, second, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    client = sources.require_lbx()
    point_read = client.get_subscription
    first_id, second_id = (service.linked_subscription_id(factory, item) for item in (first, second))
    transport.subscriptions[0]["tariff_id"] = 701
    transport.subscriptions[0]["services"][0]["price"] = 15
    claim = claim_inventory(Scenario(factory, config, transport, sources, second_id))
    result = await inventory(sources, factory, first, claim=claim)
    result = persist_discoveries(factory, claim, result)
    assert not next(
        product for product in result.products if product.product_id == first.accepted.selection.product_id
    ).complete
    assert next(
        product for product in result.products if product.product_id == second.accepted.selection.product_id
    ).complete
    assert service.read_purchase(factory, first.user_id, first.id).state == "manual_review"

    async def unavailable_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == (568 if late_poll == "selected-unavailable" else 567):
            raise LbxUnavailable()
        return await point_read(subscription_id=subscription_id, budget=budget)

    if late_poll != "unrelated-same-point":
        monkeypatch.setattr(client, "get_subscription", unavailable_point)
    late = await reconcile_subscription(
        client,
        sources.billing,
        config,
        factory=factory,
        subscription_id=second_id if late_poll == "selected-unavailable" else first_id,
    )
    assert late.proof.complete == (late_poll == "unrelated-same-point")
    apply_inventory(factory, claim, result, "inventory_incomplete", clock_skew_seconds=10)
    with factory() as db:
        assert db.scalar(
            select(BillingProductAccessScope.primary_subscription_id).where(
                BillingProductAccessScope.product_id == second.accepted.selection.product_id
            )
        ) == (None if late_poll == "selected-unavailable" else second_id)
    assert all(request.method == "GET" for request in transport.requests)


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
@pytest.mark.parametrize(
    ("mode", "interleave"),
    [
        ("automatic", "after-read"),
        ("automatic", "after-persist"),
        ("automatic", "busy-after-read"),
        ("automatic", "after-complete-point"),
        ("automatic", "before-read"),
        ("automatic", "no-change"),
        ("audited", "after-read"),
        ("audited", "before-read"),
        ("audited", "no-change"),
    ],
)
async def test_retained_point_history_change_rejects_primary_selection(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    interleave: str,
) -> None:
    transport, sources, first, second, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    client = sources.require_lbx()
    point_read, tariff_read = client.get_subscription, client.get_tariff
    first_id, second_id = (service.linked_subscription_id(factory, item) for item in (first, second))
    scenario = Scenario(factory, config, transport, sources, second_id)
    request = None
    if mode == "audited":
        with factory() as db:
            db.add(
                BillingProductAccessScope(
                    user_id=second.user_id, product_id="brief_decoder", primary_retired_at=datetime.now(UTC)
                )
            )
            db.commit()
        transport.subscriptions[0]["tariff_id"] = 701
        await run_inventory(scenario)

    async def unavailable_policy(*, tariff_id: int, budget: PreflightBudget) -> Any:
        if tariff_id == 701:
            raise LbxUnavailable()
        return await tariff_read(tariff_id=tariff_id, budget=budget)

    monkeypatch.setattr(client, "get_tariff", unavailable_policy)
    transport.subscriptions[0]["tariff_id"] = 703
    initial = await inventory(sources, factory, first)
    initial_source = next(source for source in initial.sources if source.purchase.id == first.id)
    assert not initial_source.proof.complete
    assert service.read_purchase(factory, first.user_id, first.id).state == "linked"
    if mode == "audited":
        target = service.read_purchase(factory, second.user_id, second.id)
        request = resolution_request(target, inspect_evidence(factory, config, target.user_id, target.id)).model_copy(
            update={"resolution": "select-primary"}
        )

    async def unavailable_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxUnavailable()
        return await point_read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(client, "get_subscription", unavailable_point)
    transport.subscriptions[0]["tariff_id"] = 702
    pending = None
    if interleave == "busy-after-read":
        pending = claim_reconciliation(
            factory, config, first_id, io_timeout_seconds=sources.billing.policy.total_timeout_seconds
        )
    if interleave == "after-complete-point":
        transport.subscriptions[0]["tariff_id"] = 701
        monkeypatch.setattr(client, "get_tariff", tariff_read)
        monkeypatch.setattr(client, "get_subscription", point_read)
    history_read, late_committed = asyncio.Event(), asyncio.Event()
    newer: list[ReconciliationResult] = []

    async def delegate(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        history = fn is retained_subscription_relationships and args[1].id == first.id
        if history and interleave == "before-read":
            history_read.set()
            await late_committed.wait()
        result = await run_in_threadpool(fn, *args, **kwargs)
        # Complete points now capture relationship history too. Interleave after
        # that snapshot to exercise the actual final semantic guard.
        if history and interleave in {"after-read", "busy-after-read", "after-complete-point"}:
            history_read.set()
            await late_committed.wait()
        return result

    async def competing_read(*, wait: bool) -> None:
        if wait:
            await history_read.wait()
        monkeypatch.setattr(client, "get_subscription", point_read)
        monkeypatch.setattr(client, "get_tariff", unavailable_policy)
        transport.subscriptions[0]["tariff_id"] = 702
        async with sources.billing.operation(bound_scope=False) as budget:
            if pending is None:
                result = await reconcile_subscription(
                    client, sources.billing, config, factory=factory, subscription_id=first_id, budget=budget
                )
            else:
                proof = await read_subscription_proof(client, pending, config, factory=factory, budget=budget)
                result = apply_reconciliation(factory, pending, proof, clock_skew_seconds=10)
        assert not result.proof.complete and result.proof.point_relationship.tariff_id == 702
        newer.append(result)
        late_committed.set()

    async def delegated_reconciliation(*args: Any, **kwargs: Any) -> ReconciliationResult:
        return await reconcile_subscription(*args, **kwargs, delegate=delegate)

    monkeypatch.setattr(billing_operator, "reconcile_subscription", delegated_reconciliation)

    async def attempt() -> None:
        if mode == "audited":
            assert request is not None
            await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
            return
        claim = claim_inventory(scenario)
        result = await inventory(sources, factory, first, claim=claim, delegate=delegate)
        result = persist_discoveries(factory, claim, result)
        if interleave == "after-persist":
            await competing_read(wait=False)
        apply_inventory(factory, claim, result, "inventory_incomplete", clock_skew_seconds=10)

    async def run() -> None:
        if interleave in {"after-read", "before-read", "busy-after-read", "after-complete-point"}:
            await asyncio.wait_for(asyncio.gather(attempt(), competing_read(wait=True)), timeout=60)
        else:
            await attempt()

    if mode == "audited" and interleave in {"after-read", "after-persist", "busy-after-read", "after-complete-point"}:
        with pytest.raises(PurchaseRefused, match="billing_review_stale"):
            await run()
    elif mode == "audited" and interleave == "before-read":
        with pytest.raises(PurchaseInventoryIncomplete):
            await run()
    else:
        await run()
    with factory() as db:
        selected = db.scalar(
            select(BillingProductAccessScope.primary_subscription_id).where(
                BillingProductAccessScope.product_id == "brief_decoder"
            )
        )
        assert selected == (second_id if interleave == "no-change" else None)
        if newer:
            observation = db.get(BillingStateObservation, newer[0].observation_id)
            assert observation.evidence_document["point_relationship"]["tariff_id"] == 702
            assert db.get(ExternalSubscription, first_id).latest_observation_id != observation.observation_id
        if request is not None:
            case = db.get(ManualReviewCase, request.case_id)
            assert case.case_state == ("resolved" if interleave == "no-change" else "open")
            if interleave != "no-change":
                assert case.resolution_document is None
    assert service.linked_subscription_id(factory, first) == first_id
    assert all(request.method == "GET" for request in transport.requests)


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_refused_operator_proof_retains_relationship_without_applying_source(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, first, _, third, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    client = sources.require_lbx()
    point_read = client.get_subscription
    first_id, third_id = (service.linked_subscription_id(factory, item) for item in (first, third))
    transport.subscriptions[0]["tariff_id"] = 701
    transport.subscriptions[0]["services"][0]["price"] = 15
    # Establish the real commercial review without selecting any primary.
    await inventory(sources, factory, first)
    target = service.read_purchase(factory, first.user_id, first.id)
    evidence = inspect_evidence(factory, config, target.user_id, target.id)
    request = resolution_request(target, evidence)
    transport.subscriptions[0]["tariff_id"] = 703
    with pytest.raises(PurchaseInventoryIncomplete):
        await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    with factory() as db:
        assert db.get(ManualReviewCase, request.case_id).case_state == "open"
        assert db.get(ExternalSubscription, first_id).latest_observation_id == request.expected_observation_id
        # The refused attempt leaves a finite lease. Expire only this test's
        # lease so the next real scan can record its unavailable canonical read.
        db.get(ExternalSubscription, first_id).reconciliation_lease_expires_at = datetime(2020, 1, 1, tzinfo=UTC)
        db.commit()

    async def unavailable_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxUnavailable()
        return await point_read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(client, "get_subscription", unavailable_point)
    scenario = Scenario(factory, config, transport, sources, third_id)
    await run_inventory(scenario)
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == third.accepted.selection.product_id
                )
            )
            is None
        )
        assert db.get(ManualReviewCase, request.case_id).case_state == "open"
    assert all(request.method == "GET" for request in transport.requests)


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_new_complete_claim_supersedes_late_inventory_fact_from_older_claim(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, first, _, third, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings(paid_access_clock_skew_seconds=10)
    client = sources.require_lbx()
    point_read = client.get_subscription
    first_id, third_id = (service.linked_subscription_id(factory, item) for item in (first, third))
    transport.subscriptions[0]["tariff_id"] = 701
    initial = await inventory(sources, factory, first)
    old = next(history for history in initial.point_history if history.purchase_id == first.id)
    transport.subscriptions[0].update(agreement_id=458, tariff_id=703)
    started = read_source_time(factory)
    async with sources.billing.operation(bound_scope=False) as budget:
        point = await client.get_subscription(subscription_id=567, budget=budget)
    interval = ReadInterval(started, read_source_time(factory))
    transport.subscriptions[0].update(agreement_id=456, tariff_id=701)
    newer = await reconcile_subscription(client, sources.billing, config, factory=factory, subscription_id=first_id)
    assert newer.subject.fence > old.fence and newer.proof.complete
    # Arrival is late; the actual contradicting point was read before the full proof.
    retain_inventory_relationship(
        factory,
        first,
        first_id,
        old.fence,
        SubscriptionRelationship(str(point.agreement_id), point.tariff_id),
        interval=interval,
    )
    retained = retained_subscription_relationships(factory, first)
    assert retained.relationships == (SubscriptionRelationship("456", 701),)

    async def unavailable_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxUnavailable()
        return await point_read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(client, "get_subscription", unavailable_point)
    await run_inventory(Scenario(factory, config, transport, sources, third_id))
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == third.accepted.selection.product_id
                )
            )
            == third_id
        )


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
async def test_expired_operator_lease_cannot_clear_retained_relationships(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, first, _, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings()
    initial = await inventory(sources, factory, first)
    source = next(source for source in initial.sources if source.purchase.id == first.id)
    assert source.proof.point_relationship == SubscriptionRelationship("456", 702)
    transport.subscriptions[0]["tariff_id"] = 701
    subject = claim_reconciliation(
        factory, config, source.subject.subscription_id, io_timeout_seconds=sources.billing.policy.total_timeout_seconds
    )
    async with sources.billing.operation(bound_scope=False) as budget:
        proof = await read_subscription_proof(sources.require_lbx(), subject, config, factory=factory, budget=budget)
    assert proof.complete
    with factory() as db:
        db.get(ExternalSubscription, subject.subscription_id).reconciliation_lease_expires_at = datetime(
            2020, 1, 1, tzinfo=UTC
        )
        db.commit()
    retain_inventory_relationship(
        factory,
        first,
        subject.subscription_id,
        subject.fence,
        proof.point_relationship,
        proof=proof,
        subject=subject,
        interval=ReadInterval(proof.read_started_at, proof.read_finished_at),
    )
    assert SubscriptionRelationship("456", 702) in retained_subscription_relationships(factory, first).relationships
