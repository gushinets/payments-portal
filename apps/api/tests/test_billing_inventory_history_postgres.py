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
from app.domains.billing.inventory_history import retained_subscription_relationships
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation
from app.domains.billing.reconciliation_contracts import ReconciliationResult
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseInventoryIncomplete, PurchaseRefused
from app.domains.purchases.inventory_contracts import InventoryStale
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
        complete_point = (
            interleave == "after-complete-point" and fn is apply_reconciliation and args[1].purchase.id == first.id
        )
        if (history and interleave in {"after-read", "busy-after-read"}) or complete_point:
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

    if interleave in {"after-read", "after-persist", "busy-after-read", "after-complete-point"}:
        error = PurchaseRefused if mode == "audited" else InventoryStale
        code = "billing_review_stale" if mode == "audited" else "purchase_inventory_incomplete"
        with pytest.raises(error, match=code):
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
