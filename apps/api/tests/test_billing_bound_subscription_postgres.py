"""Stage 2: real Portal HTTP/claims and PostgreSQL; only SIMULATED LBX I/O."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition import reconciliation as orchestration
from app.composition.billing_operator import reconcile_purchase, resolve_review
from app.domains.billing import work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import apply_customer_read, reserve_customer
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation
from app.domains.billing.reconciliation_contracts import ReconciliationSubject, SubscriptionProof
from app.domains.billing.work_contracts import WorkClaim, WorkLane
from app.domains.purchases.contracts import Purchase
from app.infrastructure.persistence.billing_work import coalesce
from app.domains.purchases import financial
from app.integrations.lbx.errors import LbxUnavailable
from app.integrations.lbx.reconciliation import read_subscription_proof
from app.jobs.billing import BillingWorker
from app.models import BillingStateObservation, BillingWorkItem, ExternalSubscription, ManualReviewCase
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN
from apps.api.tests.test_billing_subscription_reconciliation_postgres import (
    activate,
    run,
    scenario as scenario,
    snapshot,
)
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def portal(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    from app.domains.billing import router as billing_routes
    from app.domains.purchases import router as purchase_routes
    from app.http.dependencies import get_session_factory
    from app.main import create_app

    configuration = step1_settings()
    monkeypatch.setattr(billing_routes, "settings", configuration)
    monkeypatch.setattr(purchase_routes, "settings", configuration)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: postgres_session_factory
    app.state.sources = scenario[1]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://portal.test",
        headers={"Authorization": "Bearer " + TOKEN},
    ) as client:
        yield client


def observation_count(factory: sessionmaker[Session], schema: str) -> int:
    with factory() as db:
        return db.scalar(
            select(func.count())
            .select_from(BillingStateObservation)
            .where(BillingStateObservation.evidence_schema_version == schema)
        )


async def payment(portal: httpx.AsyncClient, purchase_id: UUID) -> httpx.Response:
    return await portal.post("/api/billing/widget-bootstrap", json={"purchase_intent_id": str(purchase_id)})


@pytest.mark.parametrize("entrypoint", ["payment", "advance", "worker", "operator"])
async def test_bound_callers_commit_one_claimed_negative_without_rebinding(
    scenario: tuple,
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    await run(sources, factory)
    original = sources.require_lbx().get_subscription
    claimed_reads = 0

    async def claimed(**kwargs: object) -> object:
        nonlocal claimed_reads
        with factory() as db:
            sub = db.get(ExternalSubscription, snapshot(factory)[0])
            assert sub.reconciliation_lease_owner is not None
            assert sub.reconciliation_lease_expires_at > datetime.now(UTC)
        claimed_reads += 1
        return await original(**kwargs)

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", claimed)
    transport.subscriptions[0]["current_blocking"] = 1
    before = len(transport.requests)
    if entrypoint == "payment":
        response = await payment(portal, purchase.id)
        assert response.status_code == 200 and response.json()["presentation"] == "payment"
    elif entrypoint == "advance":
        response = await portal.post(f"/api/purchase-intents/{purchase.id}/advance")
        assert response.status_code == 200 and response.json()["state"] == "linked"
    elif entrypoint == "operator":
        await reconcile_purchase(
            sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
    else:
        with factory() as db:
            job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
            job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            job.priority = 1
            db.commit()
        worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
        try:
            assert await worker.tick(WorkLane.URGENT)
        finally:
            await worker.aclose()
    assert claimed_reads == 1 and snapshot(factory)[1:3] == ("active", "blocked")
    assert observation_count(factory, "prepared-subscription:v1") == 1
    assert all(request.method == "GET" for request in transport.requests[before:])
    assert any(request.url.path.endswith("/subscriptions") for request in transport.requests[before:]) is (
        entrypoint == "payment"
    )
    with factory() as db:
        latest = db.get(BillingStateObservation, snapshot(factory)[-1])
        assert latest.evidence_schema_version == "subscription-reconciliation:v1"
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0


@pytest.mark.parametrize("case", ["same_tariff", "other_tariff", "ended", "other_agreement", "clean"])
async def test_payment_checks_dedicated_agreement_before_background_inventory(
    scenario: tuple,
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    case: str,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    await run(sources, factory)
    if case != "clean":
        extra = {**transport.subscriptions[0], "subscription_id": 9999}
        if case == "other_tariff":
            extra["tariff_id"] = 999
        elif case == "ended":
            extra["state"] = 3
        elif case == "other_agreement":
            extra["agreement_id"] = 999
            transport.agreements.append({**transport.agreements[0], "agreement_id": 999})
        transport.subscriptions.append(extra)
    before = len(transport.requests)
    response = await payment(portal, purchase.id)
    conflict = case in {"same_tariff", "other_tariff"}
    assert response.status_code == (409 if conflict else 200)
    if conflict:
        assert response.json()["detail"]["code"] == "purchase_not_prepared"
        assert "credential" not in response.json()
        assert snapshot(factory)[2:4] == ("blocked", "ineligible")
        with factory() as db:
            case_row = db.scalar(select(ManualReviewCase))
            assert case_row.reason_code == "subscription_identity_conflict" and case_row.case_state == "open"
            observation = db.get(BillingStateObservation, snapshot(factory)[-1])
            assert "dedicated_agreement_conflict" in observation.evidence_document["reasons"]
    else:
        assert response.json()["presentation"] == "payment"
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
    requests = transport.requests[before:]
    assert all(request.method == "GET" for request in requests)
    assert sum(request.url.path.endswith("/subscriptions/567") for request in requests) == 1
    assert any(request.url.path.endswith("/client/user") for request in requests) is not conflict
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("failure", ["unavailable", "unstable", "unknown_lifecycle"])
async def test_payment_incomplete_agreement_inventory_never_mints_or_renews_trust(
    scenario: tuple,
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    await run(sources, factory)
    trusted = snapshot(factory)
    if failure == "unknown_lifecycle":
        transport.subscriptions.append({**transport.subscriptions[0], "subscription_id": 9999, "state": 99})
    else:
        discover = sources.require_lbx().discover_subscriptions
        calls = 0

        async def incomplete(**kwargs: object) -> object:
            nonlocal calls
            calls += 1
            if failure == "unavailable":
                raise LbxUnavailable()
            rows = await discover(**kwargs)
            return rows if calls == 1 else ()

        monkeypatch.setattr(sources.require_lbx(), "discover_subscriptions", incomplete)
    before = len(transport.requests)
    response = await payment(portal, purchase.id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "purchase_not_prepared"
    assert "credential" not in response.json() and snapshot(factory) == trusted
    assert not any(request.url.path.endswith("/client/user") for request in transport.requests[before:])
    with factory() as db:
        attempt = db.scalar(
            select(BillingStateObservation)
            .where(BillingStateObservation.evidence_schema_version == "subscription-reconciliation:v1")
            .order_by(BillingStateObservation.observed_at.desc())
        )
        assert "agreement_inventory_incomplete" in attempt.evidence_document["reasons"]
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0


@pytest.mark.parametrize(
    "negative", ["ended", "incomplete", "slow_policy", "closed_without_subscription", "invalid_agreement_blocked"]
)
async def test_payment_refuses_unproven_or_terminal_but_keeps_committed_negative(
    scenario: tuple,
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    negative: str,
) -> None:
    from app.infrastructure.preflight import PreflightPolicy

    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    await run(sources, factory)
    trusted = snapshot(factory)
    if negative == "ended":
        transport.subscriptions[0].update(state=3, current_blocking=3)
    elif negative == "incomplete":
        transport.subscriptions[0]["total_price"] = None
    elif negative == "invalid_agreement_blocked":
        transport.agreements[0]["close_date"] = "unknown"
        transport.subscriptions[0]["current_blocking"] = 1
    elif negative == "closed_without_subscription":
        transport.agreements[0]["close_date"] = "2026-11-05"

        async def unavailable(**kwargs: object) -> None:
            raise LbxUnavailable()

        monkeypatch.setattr(sources.require_lbx(), "get_subscription", unavailable)
    else:
        transport.subscriptions[0]["current_blocking"] = 1
        monkeypatch.setattr(sources.billing, "policy", PreflightPolicy(1.0, 0.1, 1, 0))

        async def slow(**kwargs: object) -> None:
            await asyncio.sleep(1.1)
            raise LbxUnavailable()

        monkeypatch.setattr(sources.require_lbx(), "get_tariff", slow)
    response = await payment(portal, purchase.id)
    assert response.status_code == 409 and response.json()["detail"]["code"] == "purchase_not_prepared"
    assert "credential" not in response.json()
    assert response.headers["cache-control"] == "no-store"
    current = snapshot(factory)
    if negative == "incomplete":
        assert current == trusted
    else:
        assert current[2] == "blocked" and current[-1] != trusted[-1]
        if negative != "ended":
            assert current[4:6] == trusted[4:6]
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0


@pytest.mark.parametrize("established_trust", [False, True])
async def test_payment_with_incomplete_paid_calendar_does_not_require_or_extend_paid_trust(
    scenario: tuple,
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    established_trust: bool,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    if established_trust:
        await run(sources, factory)
    trusted = snapshot(factory)
    transport.subscriptions[0]["last_tariffication_period_start"] = None
    transport.subscriptions[0]["last_tariffication_period_end"] = None
    response = await payment(portal, purchase.id)
    assert response.status_code == 200 and response.json()["presentation"] == "payment"
    assert snapshot(factory) == trusted
    with factory() as db:
        attempt = db.scalar(
            select(BillingStateObservation)
            .where(BillingStateObservation.evidence_schema_version == "subscription-reconciliation:v1")
            .order_by(BillingStateObservation.observed_at.desc())
        )
        assert attempt.completeness_classification == "incomplete"
        assert "current_calendar_incomplete" in attempt.evidence_document["reasons"]
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0


@pytest.mark.parametrize("entrypoint", ["payment", "advance"])
async def test_bound_http_busy_is_pending_and_preserves_work(
    scenario: tuple,
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    entrypoint: str,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    claim_reconciliation(factory, step1_settings(), snapshot(factory)[0], io_timeout_seconds=60)
    before = len(transport.requests)
    response = (
        await payment(portal, purchase.id)
        if entrypoint == "payment"
        else await portal.post(f"/api/purchase-intents/{purchase.id}/advance")
    )
    assert response.status_code == 409 and response.json()["detail"]["code"] == "purchase_pending"
    assert "credential" not in response.json() and len(transport.requests) == before
    with factory() as db:
        job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        assert job.work_state == "pending" and job.enqueue_generation == 0
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
    # C2: an independent account opening needs no subscription lease.
    account = await portal.post("/api/billing/widget-bootstrap", json={})
    assert account.status_code == 200 and account.json()["presentation"] == "account"


async def test_old_active_cannot_overwrite_later_http_block(
    scenario: tuple,
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    old = claim_reconciliation(factory, step1_settings(), snapshot(factory)[0], io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        positive = await read_subscription_proof(sources.require_lbx(), old, step1_settings(), budget=budget)
    with factory() as db:
        db.get(ExternalSubscription, old.subscription_id).reconciliation_lease_expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        db.commit()
    transport.subscriptions[0]["current_blocking"] = 3
    assert (await payment(portal, purchase.id)).status_code == 200
    before = snapshot(factory)
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        apply_reconciliation(factory, old, positive)
    assert snapshot(factory) == before and before[2] == "blocked"


async def test_customer_restriction_is_atomic_across_products_and_survives_key_restore(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    second = historical_link(factory, purchase, transport, "brief_decoder", 1)
    for item in (purchase, second):
        await reconcile_purchase(sources, step1_settings(), factory=factory, user_id=item.user_id, purchase_id=item.id)
    with factory() as db:
        identities = list(db.scalars(select(ExternalSubscription.subscription_id)))
    old = claim_reconciliation(factory, step1_settings(), identities[0], io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        proof = await read_subscription_proof(sources.require_lbx(), old, step1_settings(), budget=budget)
    customer = reserve_customer(factory, step1_settings(), TOKEN)
    with factory() as db:
        history = {
            sub.subscription_id: (sub.last_authoritative_read_at, sub.projection_valid_until, sub.latest_observation_id)
            for sub in db.scalars(select(ExternalSubscription))
        }
    with pytest.raises(BillingRefused, match="billing_identity_conflict"):
        apply_customer_read(factory, customer, provider_id="345", outer_key="foreign-original-key")
    restored = reserve_customer(factory, step1_settings(), TOKEN)
    apply_customer_read(factory, restored, provider_id="345", outer_key=restored.outer_key)
    with pytest.raises(BillingRefused):
        apply_reconciliation(factory, old, proof)
    with factory() as db:
        for sub in db.scalars(select(ExternalSubscription)):
            assert (sub.financial_access_status, sub.commercial_access_status) == ("blocked", "ineligible")
            assert (sub.last_authoritative_read_at, sub.projection_valid_until, sub.latest_observation_id) == history[
                sub.subscription_id
            ]
            assert sub.reconciliation_lease_owner is None


async def test_operator_restore_keeps_old_active_stale_and_financial_conflict_product_scoped(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    second = historical_link(factory, purchase, transport, "brief_decoder", 1)
    await reconcile_purchase(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    await reconcile_purchase(sources, step1_settings(), factory=factory, user_id=second.user_id, purchase_id=second.id)
    with factory() as db:
        target = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchase.id))
        target_id = target.subscription_id
        sibling = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == second.id))
        sibling_before = (
            sibling.financial_access_status,
            sibling.commercial_access_status,
            sibling.latest_observation_id,
        )
    old = claim_reconciliation(factory, step1_settings(), target_id, io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        proof = await read_subscription_proof(sources.require_lbx(), old, step1_settings(), budget=budget)
    operation = next(op for op in purchase.operations if op.kind == "subscription")
    financial.financial_pending(factory, purchase, operation, conflict=True)
    with factory() as db:
        target = db.get(ExternalSubscription, target_id)
        assert (target.financial_access_status, target.commercial_access_status) == ("blocked", "ineligible")
        sibling = db.get(ExternalSubscription, sibling.subscription_id)
        assert (
            sibling.financial_access_status,
            sibling.commercial_access_status,
            sibling.latest_observation_id,
        ) == sibling_before
    evidence = inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id)
    request = resolution_request(purchase, evidence)
    await resolve_review(sources, step1_settings(), factory=factory, request=request, principal="os-euid:1000")
    with pytest.raises(BillingRefused):
        apply_reconciliation(factory, old, proof)
    with factory() as db:
        assert db.get(ExternalSubscription, target_id).financial_access_status == "allowed"
        assert db.get(ManualReviewCase, request.case_id).case_state == "resolved"


@pytest.mark.parametrize("failure", ["commit", "cancel"])
async def test_failed_or_cancelled_http_proof_never_returns_payment_or_rebinds(
    scenario: tuple,
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    before = snapshot(factory)
    initial_count = observation_count(factory, "subscription-reconciliation:v1")
    if failure == "commit":
        apply = orchestration.apply_reconciliation

        def fail(factory: object, subject: ReconciliationSubject, proof: SubscriptionProof, **kwargs: object) -> UUID:
            def reject_commit(self: Session) -> None:
                raise RuntimeError("simulated apply commit failure")

            with monkeypatch.context() as scoped:
                scoped.setattr(Session, "commit", reject_commit)
                return apply(factory, subject, proof, **kwargs)

        with monkeypatch.context() as scoped:
            scoped.setattr(orchestration, "apply_reconciliation", fail)
            response = await payment(portal, purchase.id)
        assert response.status_code == 500 and "credential" not in response.json()
    else:
        entered = asyncio.Event()

        async def waiting(**kwargs: object) -> None:
            entered.set()
            await asyncio.Event().wait()

        with monkeypatch.context() as scoped:
            scoped.setattr(sources.require_lbx(), "get_subscription", waiting)
            opening = asyncio.create_task(payment(portal, purchase.id))
            await asyncio.wait_for(entered.wait(), timeout=5)
            opening.cancel()
            with pytest.raises(asyncio.CancelledError):
                await opening
        assert sources.billing.active_count == 0
    assert snapshot(factory) == before
    assert observation_count(factory, "subscription-reconciliation:v1") == initial_count
    with factory() as db:
        sub = db.get(ExternalSubscription, before[0])
        assert sub.reconciliation_lease_owner is not None
        sub.reconciliation_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert (await payment(portal, purchase.id)).status_code == 200
    assert [transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")] == [1, 1, 1]


def inventory_claim(factory: sessionmaker[Session], purchase: Purchase) -> WorkClaim:
    with factory() as db:
        coalesce(
            db,
            kind="customer_inventory",
            key=f"{purchase.account_id}:{purchase.customer_id}",
            scope_kind="customer",
            reference=str(purchase.customer_id),
            due=datetime.now(UTC) - timedelta(seconds=1),
            priority=0,
            payload={},
        )
        db.commit()
    claim = work.claim_work(factory, step1_settings(), WorkLane.NORMAL)
    assert claim is not None and claim.kind == "customer_inventory"
    return claim


@pytest.mark.parametrize("incomplete", [False, True])
async def test_inventory_origin_apply_does_not_finish_customer_or_other_subscription_queue_owner(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    incomplete: bool,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    inventory = inventory_claim(factory, purchase)
    subscription_claim = work.claim_work(factory, step1_settings(), WorkLane.URGENT)
    assert subscription_claim is not None and subscription_claim.kind == work.RECONCILIATION
    if incomplete:
        transport.subscriptions[0]["total_price"] = None
    await orchestration.reconcile_subscription(
        sources.require_lbx(),
        sources.billing,
        step1_settings(),
        factory=factory,
        subscription_id=snapshot(factory)[0],
        work_claim=inventory,
    )
    with factory() as db:
        for claim in (inventory, subscription_claim):
            row = db.get(BillingWorkItem, claim.id)
            assert row.work_state == "running" and row.lease_owner == claim.owner
            assert row.lease_expires_at == claim.expires_at
        row = db.get(BillingWorkItem, subscription_claim.id)
        assert row.enqueue_generation == subscription_claim.generation + int(incomplete)
        hinted_due = row.next_attempt_at
        work.finish(
            db,
            work.verify_claim(db, subscription_claim),
            subscription_claim,
            due=datetime.now(UTC) + timedelta(minutes=15),
        )
        db.commit()
        if incomplete:
            assert row.next_attempt_at == hinted_due and row.work_state == "pending"


async def test_stale_inventory_claim_cannot_commit_subscription_facts(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    inventory = inventory_claim(factory, purchase)
    before = snapshot(factory)
    subject = claim_reconciliation(factory, step1_settings(), before[0], io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        proof = await read_subscription_proof(sources.require_lbx(), subject, step1_settings(), budget=budget)
    with factory() as db:
        db.get(BillingWorkItem, inventory.id).lease_owner = "replacement-owner"
        db.commit()
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        apply_reconciliation(factory, subject, proof, work_claim=inventory)
    assert snapshot(factory) == before
    with factory() as db:
        assert db.get(BillingWorkItem, inventory.id).lease_owner == "replacement-owner"
