"""SIMULATED source objects, disposable PostgreSQL, no background CREATE."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchase_observation import prepared_subscription_observation as _observation
from app.composition.sources import SourceResources, source_resources
from app.domains.billing import background_recovery as recovery, customers, work
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase
from app.integrations.lbx.financial import NewAgreement, NewSubscription, Subscription
from app.jobs.billing import BillingWorker
from app.models import (
    BillingPurchaseScopeHold,
    BillingStateObservation,
    BillingWorkItem,
    ManualReviewCase,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    PaidAccessState,
    PurchasedAllowance,
    AccessInvalidationOutbox,
)
from apps.api.tests.factories.reconciliation import agreement_factory, subscription_factory
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_step3_postgres import TOKEN, accept, setup_purchase
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def background_scenario(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[PurchaseTransport, SourceResources, Purchase]]:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    factory = postgres_session_factory
    config = step1_settings()
    transport = setup_purchase(factory)
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        customer = customers.reserve_customer(factory, config, TOKEN)
        customer = customers.claim_customer_send(factory, config, TOKEN, customer)
        transport.customer = {"user_id": 345, "outer_id": customer.outer_key}
        customers.apply_customer_read(factory, customer, provider_id="345", outer_key=customer.outer_key)
        yield transport, sources, purchase


def synthetic_prepare(
    factory: sessionmaker[Session], transport: PurchaseTransport, purchase: Purchase, *, uncertain: bool
) -> Purchase:
    """Original possible-send history plus synthetic GET objects; no source POST."""
    config = step1_settings()
    for kind in (Kind.AGREEMENT, Kind.SUBSCRIPTION):
        purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
        op = next(op for op in purchase.operations if op.kind == kind)
        if kind == Kind.AGREEMENT:
            command = NewAgreement(
                user_id=345, organization_id=21, agreement_number=op.key, create_date=date(2026, 10, 27)
            )
            point = agreement_factory().model_dump()
            point["agreement_number"] = op.key
            transport.agreements.append(point)
            provider_id = 456
        else:
            command = NewSubscription(
                agreement_id=456, tariff_id=701, period_id=901, tariff_service_id=1001, quantity=1, outer_id=op.key
            )
            point = subscription_factory().model_dump()
            point["total_price"] = 100
            point["services"][0].update(multiplicator=1, price=100)
            transport.subscriptions.append(point)
            provider_id = 567
        claimed = financial.claim_financial(
            factory, purchase, op, command.request_document(), configuration=config, token=TOKEN
        )
        if kind == Kind.SUBSCRIPTION and uncertain:
            pass  # Simulated lost reply/crash after possible-send commit.
        else:
            financial.bind_financial(
                factory,
                purchase,
                claimed,
                provider_id,
                observation=_observation(Subscription.model_validate(point), purchase)
                if kind == Kind.SUBSCRIPTION
                else None,
            )
    return service.read_purchase(factory, purchase.user_id, purchase.id)


def job(factory: sessionmaker[Session], kind: str, reference: UUID) -> BillingWorkItem:
    with factory() as db:
        return db.scalar(
            select(BillingWorkItem).where(
                BillingWorkItem.work_kind == kind, BillingWorkItem.scope_reference == str(reference)
            )
        )


def due(factory: sessionmaker[Session], kind: str, reference: UUID) -> None:
    with factory() as db:
        row = db.get(BillingWorkItem, job(factory, kind, reference).work_item_id)
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()


def original(factory: sessionmaker[Session], operation_id: UUID) -> tuple:
    with factory() as db:
        op = db.get(ExternalCreateOperation, operation_id)
        return op.request_correlation_key, op.recovery_hint_document, op.unknown_since, op.unknown_recovery_deadline_at


@pytest.mark.parametrize("candidates", [0, 1, 2])
async def test_billing_background_recovery_zero_one_multiple_and_delayed_visibility(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    candidates: int,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    before = original(factory, op.id)
    if candidates == 0:
        transport.hide.add("/subscriptions")
    if candidates == 2:
        transport.subscriptions.append({**transport.subscriptions[0], "subscription_id": 999})
    count = len(transport.requests)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    target = next(item for item in saved.operations if item.id == op.id)
    assert target.state == {0: State.UNKNOWN, 1: State.BOUND, 2: State.MANUAL_REVIEW}[candidates]
    assert original(factory, op.id) == before and saved.held
    assert all(req.method == "GET" for req in transport.requests[count:])
    if candidates == 1:
        with factory() as db:
            sub = db.scalar(select(ExternalSubscription))
            assert job(factory, work.RECONCILIATION, sub.subscription_id) is not None
        assert job(factory, recovery.RECOVERY, op.id).work_state == "completed"
    if candidates == 0:
        transport.hide.clear()
        due(factory, recovery.RECOVERY, op.id)
        restarted = BillingWorker(step1_settings(), factory, sources.require_lbx())
        assert await restarted.tick(WorkLane.URGENT)
        assert (
            next(
                item
                for item in service.read_purchase(factory, purchase.user_id, purchase.id).operations
                if item.id == op.id
            ).state
            == State.BOUND
        )
    if candidates == 2:
        transport.subscriptions.pop()
        due(factory, recovery.RECOVERY, op.id)
        assert await worker.tick(WorkLane.URGENT)
        saved = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert next(item for item in saved.operations if item.id == op.id).state == State.MANUAL_REVIEW
    with factory() as db:
        for model in (PaidAccessState, PurchasedAllowance, AccessInvalidationOutbox):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert all(obs.resulting_access_revision is None for obs in db.scalars(select(BillingStateObservation)))
    await worker.aclose()


@pytest.mark.parametrize("unsent", [False, True])
async def test_billing_background_recovery_independent_deadline_and_no_send(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    unsent: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    # Set original time before claiming; the permanent two-hour pair is immutable.
    past = datetime.now(UTC) - timedelta(hours=3)
    monkeypatch.setattr(financial, "utc_now", lambda: past)
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    if unsent:
        # A separate original completed typed result; no background authority.
        with factory() as db:
            row = db.get(ExternalCreateOperation, op.id)
            row.operation_state = State.POSSIBLE_SEND
            db.commit()
        from dataclasses import replace

        financial.proven_not_sent(factory, purchase, replace(op, may_send=True))
    before = original(factory, op.id)
    count = len(transport.requests)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.LOCAL)  # Provider outage cannot block this.
    # The bound agreement deadline may run first.
    await worker.tick(WorkLane.LOCAL)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    state = next(item for item in saved.operations if item.id == op.id).state
    assert state == (State.PROVEN_NOT_SENT if unsent else State.MANUAL_REVIEW)
    assert original(factory, op.id) == before and saved.held
    assert len(transport.requests) == count
    if not unsent:
        await worker.tick(WorkLane.URGENT)  # Late original object may still bind.
        assert (
            next(
                item
                for item in service.read_purchase(factory, purchase.user_id, purchase.id).operations
                if item.id == op.id
            ).state
            == State.BOUND
        )
    await worker.aclose()


@pytest.mark.parametrize("uncertain_product", ["proposal_ai", "brief_decoder"])
async def test_billing_background_recovery_two_products_same_tariff_isolated(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    uncertain_product: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=uncertain_product == "proposal_ai")
    second = historical_link(
        factory, first, transport, "brief_decoder", 1, uncertain_subscription=uncertain_product == "brief_decoder"
    )
    target, other = (first, second) if uncertain_product == "proposal_ai" else (second, first)
    op = next(item for item in target.operations if item.kind == Kind.SUBSCRIPTION)
    preserved = service.read_purchase(factory, other.user_id, other.id)
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == other.id))
        other_job = db.get(BillingWorkItem, job(factory, work.RECONCILIATION, sub.subscription_id).work_item_id)
        other_job.next_attempt_at = datetime.now(UTC) + timedelta(minutes=15)
        db.commit()
        untouched = (
            sub.latest_observation_id,
            sub.projection_valid_until,
            other_job.next_attempt_at,
            other_job.enqueue_generation,
        )
    count = len(transport.requests)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    assert service.read_purchase(factory, other.user_id, other.id) == preserved
    with factory() as db:
        sub = db.get(ExternalSubscription, sub.subscription_id)
        other_job = db.get(BillingWorkItem, other_job.work_item_id)
        assert (
            sub.latest_observation_id,
            sub.projection_valid_until,
            other_job.next_attempt_at,
            other_job.enqueue_generation,
        ) == untouched
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 2
    assert (
        next(
            item for item in service.read_purchase(factory, target.user_id, target.id).operations if item.id == op.id
        ).state
        == State.BOUND
    )
    recovery.repair_batch(factory, step1_settings())
    assert await worker.tick(WorkLane.NORMAL)
    inventory = job(factory, recovery.INVENTORY, target.customer_id)
    assert inventory.last_error_classification is None
    assert (
        (datetime.now(UTC) + timedelta(hours=4)) < inventory.next_attempt_at <= (datetime.now(UTC) + timedelta(hours=6))
    )
    assert all(req.method == "GET" for req in transport.requests[count:])
    await worker.aclose()


@pytest.mark.parametrize("product", ["proposal_ai", "brief_decoder"])
@pytest.mark.parametrize("failure", ["swapped", "foreign", "incomplete", "ambiguous"])
async def test_billing_background_recovery_two_product_original_candidate_refusals(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    product: str,
    failure: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=product == "proposal_ai")
    second = historical_link(
        factory, first, transport, "brief_decoder", 1, uncertain_subscription=product == "brief_decoder"
    )
    index = 0 if product == "proposal_ai" else 1
    target, other = (first, second) if index == 0 else (second, first)
    op = next(op for op in target.operations if op.kind == Kind.SUBSCRIPTION)
    before = original(factory, op.id)
    preserved = service.read_purchase(factory, other.user_id, other.id)
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == other.id))
        row = db.get(BillingWorkItem, job(factory, work.RECONCILIATION, sub.subscription_id).work_item_id)
        row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=15)
        db.commit()
        untouched = (sub.latest_observation_id, sub.projection_valid_until, row.next_attempt_at, row.enqueue_generation)
    if failure == "swapped":
        transport.subscriptions[index]["agreement_id"] = transport.agreements[1 - index]["agreement_id"]
    elif failure == "foreign":
        transport.agreements[index]["user_id"] = 999
    elif failure == "incomplete":
        transport.subscriptions[index]["services"] = None
    else:
        transport.subscriptions.append({**transport.subscriptions[index], "subscription_id": 999})
    count = len(transport.requests)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    saved = service.read_purchase(factory, target.user_id, target.id)
    target_op = next(item for item in saved.operations if item.id == op.id)
    assert target_op.bound_id is None
    assert target_op.state == (State.MANUAL_REVIEW if failure in {"foreign", "ambiguous"} else State.UNKNOWN)
    assert original(factory, op.id) == before and saved.held
    assert service.read_purchase(factory, other.user_id, other.id) == preserved
    with factory() as db:
        sub = db.get(ExternalSubscription, sub.subscription_id)
        row = db.get(BillingWorkItem, row.work_item_id)
        assert (
            sub.latest_observation_id,
            sub.projection_valid_until,
            row.next_attempt_at,
            row.enqueue_generation,
        ) == untouched
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 2
    assert all(req.method == "GET" for req in transport.requests[count:])
    await worker.aclose()


@pytest.mark.parametrize("key", [None, "foreign-key"])
async def test_billing_background_recovery_customer_identity_incomplete_or_conflict(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    key: str | None,
) -> None:
    from app.models import ExternalBillingCustomer, ExternalBillingCustomerBindingState as Binding

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    original_key = transport.customer["outer_id"]
    transport.customer["outer_id"] = key
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    with factory() as db:
        customer = db.get(ExternalBillingCustomer, purchase.customer_id)
        assert customer.binding_state == (Binding.BOUND if key is None else Binding.IDENTITY_CONFLICT)
    transport.customer["outer_id"] = original_key
    due(factory, recovery.RECOVERY, op.id)
    assert await worker.tick(WorkLane.URGENT)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert next(item for item in saved.operations if item.id == op.id).state == (
        State.BOUND if key is None else State.POSSIBLE_SEND
    )
    assert saved.held
    await worker.aclose()


async def test_billing_background_recovery_bound_terminal_uses_lifecycle_not_preparation(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.composition.reconciliation import reconcile_subscription
    from app.composition.purchases import recover_financial
    from app.models import ExternalSubscriptionLifecycleStatus as Lifecycle

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    transport.subscriptions[0]["state"] = 3
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
    await reconcile_subscription(
        sources.require_lbx(), sources.billing, step1_settings(), factory=factory, subscription_id=sub.subscription_id
    )
    with factory() as db:
        ended = db.get(ExternalSubscription, sub.subscription_id)
        assert ended.lifecycle_status == Lifecycle.ENDED
        before = ended.latest_observation_id, ended.projection_valid_until
    count = len(transport.requests)
    result = await recover_financial(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    assert result == purchase and result.held
    assert not any("/subscriptions" in request.url.path for request in transport.requests[count:])
    recovery.repair_batch(factory, step1_settings())
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.NORMAL)
    with factory() as db:
        ended = db.get(ExternalSubscription, sub.subscription_id)
        assert (ended.latest_observation_id, ended.projection_valid_until) == before
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
    await worker.aclose()


async def test_billing_background_recovery_resumed_unsent_uses_active_window_and_exact_deadline(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.queries import billing_reconciliation

    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    now = datetime.now(UTC)
    op = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    request = NewAgreement(
        user_id=345, organization_id=21, agreement_number=op.key, create_date=date(2026, 10, 27)
    ).request_document()
    monkeypatch.setattr(financial, "utc_now", lambda: now - timedelta(hours=3))
    claimed = financial.claim_financial(factory, purchase, op, request, configuration=step1_settings(), token=TOKEN)
    financial.proven_not_sent(factory, purchase, claimed)
    before = original(factory, op.id)
    purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    op = next(op for op in purchase.operations if op.id == claimed.id)
    monkeypatch.setattr(financial, "utc_now", lambda: now)
    resumed = financial.claim_financial(factory, purchase, op, request, configuration=step1_settings(), token=TOKEN)
    assert resumed.fence != claimed.fence and resumed.key == claimed.key
    active = job(factory, recovery.RECOVERY, op.id).active_recovery_deadline_at
    assert active == now + timedelta(hours=2) and before[3] < now
    assert job(factory, recovery.DEADLINE, op.id).next_attempt_at == active
    # Reconstruct missing local scheduling after restart using the same helper.
    with factory() as db:
        db.delete(db.get(BillingWorkItem, job(factory, recovery.DEADLINE, op.id).work_item_id))
        db.flush()
        recovery.enroll_operation(db, db.get(ExternalCreateOperation, op.id), purchase.account_id)
        db.commit()
    assert job(factory, recovery.DEADLINE, op.id).next_attempt_at == active
    count = len(transport.requests)
    for instant, state in ((active - timedelta(microseconds=1), State.POSSIBLE_SEND), (active, State.MANUAL_REVIEW)):
        monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: instant)
        with factory() as db:
            row = db.get(BillingWorkItem, job(factory, recovery.DEADLINE, op.id).work_item_id)
            row.next_attempt_at = instant
            db.commit()
        for _ in range(3):
            claim = work.claim_work(factory, step1_settings(), WorkLane.LOCAL)
            assert claim is not None and claim.kind == recovery.DEADLINE
            recovery.apply_deadline(factory, claim)
            if claim.reference == str(op.id):
                break
        else:
            pytest.fail("financial deadline was not processed")
        current = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert next(item for item in current.operations if item.id == op.id).state == state
        assert job(factory, recovery.RECOVERY, op.id).active_recovery_deadline_at == active
        assert original(factory, op.id) == before
    assert len(transport.requests) == count and current.held


async def test_billing_background_recovery_legacy_null_window_uses_original_deadline(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    with factory() as db:
        row = db.get(BillingWorkItem, job(factory, recovery.RECOVERY, op.id).work_item_id)
        row.active_recovery_deadline_at = None  # Existing pre-0004 financial work.
        db.delete(db.get(BillingWorkItem, job(factory, recovery.DEADLINE, op.id).work_item_id))
        db.flush()
        recovery.enroll_operation(db, db.get(ExternalCreateOperation, op.id), purchase.account_id)
        db.commit()
    assert job(factory, recovery.DEADLINE, op.id).next_attempt_at == original(factory, op.id)[3]
