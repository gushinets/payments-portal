"""Recovery fencing, local contention and bounded inventory; SIMULATED LBX."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.reconciliation import reconcile_subscription
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import service
from app.jobs.billing import BillingWorker
from app.models import (
    BillingPurchaseScopeHold,
    BillingStateObservation,
    BillingWorkItem,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ManualReviewCase,
    User,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    due,
    job,
    original,
    synthetic_prepare,
)
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("phase", ["before_claim", "during_apply"])
async def test_billing_background_recovery_billing_busy_retains_authority_and_eventual_retry(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    phase: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    before = original(factory, op.id)
    client = sources.require_lbx()
    holder = factory()
    transport.pool = None  # Another transaction deliberately holds the user lock.
    point_read = client.get_subscription

    async def locked_read(**kwargs: object) -> object:
        result = await point_read(**kwargs)
        holder.scalar(select(User).with_for_update())
        return result

    if phase == "during_apply":
        monkeypatch.setattr(client, "get_subscription", locked_read)
    else:
        holder.scalar(select(User).with_for_update())
    worker = BillingWorker(step1_settings(), factory, client)
    count = len(transport.requests)
    try:
        assert await worker.tick(WorkLane.URGENT)
    finally:
        holder.close()
        monkeypatch.setattr(client, "get_subscription", point_read)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert next(item for item in saved.operations if item.id == op.id) == op
    assert saved.held and original(factory, op.id) == before
    assert job(factory, recovery.RECOVERY, op.id).last_error_classification == "billing_busy"
    due(factory, recovery.RECOVERY, op.id)
    assert await worker.tick(WorkLane.URGENT)
    assert (
        next(
            item
            for item in service.read_purchase(factory, purchase.user_id, purchase.id).operations
            if item.id == op.id
        ).state
        == State.BOUND
    )
    assert original(factory, op.id) == before
    assert all(req.method == "GET" for req in transport.requests[count:])
    await worker.aclose()


@pytest.mark.parametrize("product", ["proposal_ai", "brief_decoder"])
async def test_billing_background_recovery_inventory_checks_all_affected_products(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    product: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    second = historical_link(factory, first, transport, "brief_decoder", 1)
    with factory() as db:
        identities = {sub.product_id: sub.subscription_id for sub in db.scalars(select(ExternalSubscription))}
    for identity in identities.values():
        await reconcile_subscription(
            sources.require_lbx(), sources.billing, step1_settings(), factory=factory, subscription_id=identity
        )
    with factory() as db:
        trust = {
            sub.product_id: (sub.last_authoritative_read_at, sub.projection_valid_until)
            for sub in db.scalars(select(ExternalSubscription))
        }
        assert all(
            (sub.commercial_access_status, sub.financial_access_status) == ("eligible", "allowed")
            for sub in db.scalars(select(ExternalSubscription))
        )
    # A third nonterminal object competes with both purchases sharing this tariff.
    index = 0 if product == "proposal_ai" else 1
    transport.subscriptions.append({**transport.subscriptions[index], "subscription_id": 999})
    recovery.repair_batch(factory, step1_settings())
    bindings = {p.id: tuple((op.id, op.bound_id, op.key) for op in p.operations) for p in (first, second)}
    count = len(transport.requests)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    try:
        for attempt in range(3):
            due(factory, recovery.INVENTORY, first.customer_id)
            assert await worker.tick(WorkLane.NORMAL)
            inventory_job = job(factory, recovery.INVENTORY, first.customer_id)
            assert inventory_job.attempt_count == attempt + 1
            assert inventory_job.work_state == "pending" and inventory_job.lease_owner is None
            assert inventory_job.last_error_classification == "inventory_conflict"
            with factory() as db:
                reviews = list(db.scalars(select(ManualReviewCase)))
                assert len(reviews) == 2
                assert {case.scope_reference for case in reviews} == {
                    str(op.id) for p in (first, second) for op in p.operations if op.kind == Kind.SUBSCRIPTION
                }
                assert all(
                    case.case_state == "open" and case.reason_code == "customer_inventory_conflict" for case in reviews
                )
                evidence = list(
                    db.scalars(
                        select(BillingStateObservation).where(
                            BillingStateObservation.evidence_schema_version == "customer-inventory:v1"
                        )
                    )
                )
                assert {row.product_id for row in evidence} == set(identities)
                assert all(
                    sub.commercial_access_status == "ineligible" for sub in db.scalars(select(ExternalSubscription))
                )
                assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 2
            for identity in identities.values():
                await reconcile_subscription(
                    sources.require_lbx(), sources.billing, step1_settings(), factory=factory, subscription_id=identity
                )
            with factory() as db:
                for sub in db.scalars(select(ExternalSubscription)):
                    assert (sub.commercial_access_status, sub.financial_access_status) == ("ineligible", "blocked")
                    assert (sub.last_authoritative_read_at, sub.projection_valid_until) == trust[sub.product_id]
            for identity, expected in bindings.items():
                saved = service.read_purchase(factory, first.user_id, identity)
                assert tuple((op.id, op.bound_id, op.key) for op in saved.operations) == expected
        assert all(req.method == "GET" for req in transport.requests[count:])
    finally:
        await worker.aclose()


@pytest.mark.parametrize("stale", ["operation", "claim"])
async def test_billing_background_recovery_inventory_batch_rejects_stale_apply_atomically(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    stale: str,
) -> None:
    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    second = historical_link(factory, first, transport, "brief_decoder", 1)
    recovery.repair_batch(factory, step1_settings())
    claim = work.claim_work(factory, step1_settings(), WorkLane.NORMAL)
    assert claim is not None and claim.kind == recovery.INVENTORY
    with factory() as db:
        if stale == "operation":
            op = next(op for op in second.operations if op.kind == Kind.SUBSCRIPTION)
            db.get(ExternalCreateOperation, op.id).send_fence = uuid4()
        else:
            db.get(BillingWorkItem, claim.id).lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        recovery.apply_inventory(factory, claim, (first, second), "inventory_conflict")
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillingStateObservation)
                .where(BillingStateObservation.evidence_schema_version == "customer-inventory:v1")
            )
            == 0
        )
        assert all(sub.commercial_access_status == "eligible" for sub in db.scalars(select(ExternalSubscription)))
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 2
        assert db.get(BillingWorkItem, claim.id).work_state == "running"
    for expected in (first, second):
        saved = service.read_purchase(factory, first.user_id, expected.id)
        assert all(op.state == State.BOUND for op in saved.operations)


async def test_billing_background_recovery_expired_claim_late_io_cannot_apply(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    client = sources.require_lbx()
    entered, release = asyncio.Event(), asyncio.Event()
    point_read = client.get_subscription
    calls = 0

    async def paused(**kwargs: object) -> object:
        nonlocal calls
        result = await point_read(**kwargs)
        calls += 1
        if calls == 1:
            entered.set()
            await release.wait()
        return result

    monkeypatch.setattr(client, "get_subscription", paused)
    first = BillingWorker(step1_settings(), factory, client)
    second = BillingWorker(step1_settings(), factory, client)
    task = asyncio.create_task(first.tick(WorkLane.URGENT))
    await asyncio.wait_for(entered.wait(), 5)
    with factory() as db:
        row = db.get(BillingWorkItem, job(factory, recovery.RECOVERY, op.id).work_item_id)
        row.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert first.admissions[WorkLane.URGENT].active_count == 1
    assert await second.tick(WorkLane.URGENT)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    release.set()
    assert await asyncio.wait_for(task, 5)
    assert service.read_purchase(factory, purchase.user_id, purchase.id) == saved
    assert next(item for item in saved.operations if item.id == op.id).state == State.BOUND
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 1
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
    await first.aclose()
    await second.aclose()


async def test_billing_background_recovery_lost_claim_ack_no_http(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    synthetic_prepare(factory, transport, purchase, uncertain=True)
    claim = work.claim_work

    def lost(*args: object) -> object:
        assert claim(*args) is not None
        raise RuntimeError("simulated lost claim acknowledgement")

    monkeypatch.setattr(work, "claim_work", lost)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    count = len(transport.requests)
    with pytest.raises(RuntimeError, match="lost claim"):
        await worker.tick(WorkLane.URGENT)
    assert len(transport.requests) == count
    await worker.aclose()


@pytest.mark.parametrize("bad", ["unknown", "incomplete", "foreign", "swapped", "cap", "unstable"])
@pytest.mark.parametrize("product", ["proposal_ai", "brief_decoder"])
async def test_billing_background_recovery_inventory_refuses_unsafe_other_product_exclusion(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    bad: str,
    product: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    second = historical_link(factory, first, transport, "brief_decoder", 1)
    index = 0 if product == "proposal_ai" else 1
    if bad == "unknown":
        transport.subscriptions.append({**transport.subscriptions[index], "subscription_id": 999})
    elif bad == "incomplete":
        transport.subscriptions[index]["services"] = None
    elif bad == "foreign":
        transport.agreements[index]["user_id"] = 999
    elif bad == "swapped":
        transport.subscriptions[index]["agreement_id"] = transport.agreements[1 - index]["agreement_id"]
    elif bad == "cap":
        transport.subscriptions.extend(
            {**transport.subscriptions[index], "subscription_id": 1000 + n} for n in range(98)
        )
    else:
        client = sources.require_lbx()
        discover = client.discover_subscriptions
        calls = 0

        async def changing(**kwargs: object) -> tuple:
            nonlocal calls
            calls += 1
            rows = await discover(**kwargs)
            return rows if calls == 1 else rows[:1]

        monkeypatch.setattr(client, "discover_subscriptions", changing)
    recovery.repair_batch(factory, step1_settings())
    bindings = [(p.id, tuple((op.id, op.bound_id, op.key) for op in p.operations)) for p in (first, second)]
    count = len(transport.requests)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.NORMAL)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 2
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 2
    for identity, expected in bindings:
        saved = service.read_purchase(factory, first.user_id, identity)
        assert tuple((op.id, op.bound_id, op.key) for op in saved.operations) == expected
    classification = job(factory, recovery.INVENTORY, first.customer_id).last_error_classification
    assert classification == (
        "inventory_incomplete" if bad in {"incomplete", "cap", "unstable"} else "inventory_conflict"
    )
    assert all(req.method == "GET" for req in transport.requests[count:])
    await worker.aclose()


@pytest.mark.parametrize("mode", ["empty", "one", "ambiguous", "foreign"])
async def test_billing_background_recovery_customer_send_lease_and_paired_proof(
    migrated_database: object,
    postgres_session_factory: sessionmaker[Session],
    mode: str,
) -> None:
    import httpx

    from app.composition.sources import source_resources
    from app.domains.billing import customers
    from app.models import ExternalCreateOperation
    from apps.api.tests.test_any709_step2_postgres import TOKEN, seed

    factory = postgres_session_factory
    config = step1_settings()
    seed(factory)
    customer = customers.reserve_customer(factory, config, TOKEN)
    customer = customers.claim_customer_send(factory, config, TOKEN, customer)
    saved = original(factory, customer.operation_id)
    calls: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        assert request.method == "GET"
        path = request.url.path
        if path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "synthetic-token", "expires_in": 600}})
        if path.endswith("/users"):
            data = (
                []
                if mode == "empty"
                else [{"user_id": 345}, {"user_id": 346}]
                if mode == "ambiguous"
                else [{"user_id": 345}]
            )
        else:
            data = {"user_id": 345, "outer_id": "foreign-key" if mode == "foreign" else customer.outer_key}
        return httpx.Response(200, json={"code": 200, "response": data})

    async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
        worker = BillingWorker(config, factory, sources.require_lbx())
        assert not await worker.tick(WorkLane.URGENT)
        assert calls == []  # The active explicit send retains its lease.
        customers.finish_customer_attempt(factory, customer)
        assert await worker.tick(WorkLane.URGENT)
        with factory() as db:
            op = db.get(ExternalCreateOperation, customer.operation_id)
            assert (
                op.operation_state
                == {
                    "empty": State.UNKNOWN,
                    "one": State.BOUND,
                    "ambiguous": State.MANUAL_REVIEW,
                    "foreign": State.MANUAL_REVIEW,
                }[mode]
            )
            assert op.bound_external_object_id == ("345" if mode == "one" else None)
        assert original(factory, customer.operation_id) == saved
        await worker.aclose()


async def test_billing_background_recovery_repair_preserves_completed_no_send_and_live_claims(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from dataclasses import replace
    from sqlalchemy import delete
    from app.domains.purchases import financial
    from app.models import ExternalCreateOperation

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    claim = work.claim_work(factory, step1_settings(), WorkLane.URGENT)
    assert claim.reference == str(op.id)
    before = job(factory, recovery.RECOVERY, op.id)
    recovery.repair_batch(factory, step1_settings())
    after = job(factory, recovery.RECOVERY, op.id)
    assert (after.lease_owner, after.enqueue_generation, after.next_attempt_at) == (
        before.lease_owner,
        before.enqueue_generation,
        before.next_attempt_at,
    )
    financial.proven_not_sent(factory, purchase, replace(op, may_send=True))
    with factory() as db:
        db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == recovery.DEADLINE))
        db.commit()
    recovery.repair_batch(factory, step1_settings())
    assert job(factory, recovery.RECOVERY, op.id).work_state == "done"
    assert job(factory, recovery.DEADLINE, op.id) is None
    with factory() as db:
        assert db.get(ExternalCreateOperation, op.id).operation_state == State.PROVEN_NOT_SENT
