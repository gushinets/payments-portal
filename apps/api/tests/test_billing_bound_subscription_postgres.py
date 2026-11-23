"""Stage 2: real Portal HTTP/claims and PostgreSQL; only SIMULATED LBX I/O."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from time import monotonic
from uuid import UUID

import httpx
import pytest
from alembic import command
from fastapi import BackgroundTasks, FastAPI
from sqlalchemy import func, select
from sqlalchemy.engine import URL
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from starlette.types import Message, Receive, Scope, Send

from app.composition import reconciliation as orchestration
from app.composition.billing_operator import reconcile_purchase, resolve_review
from app.composition.paid_reads import paid_read_resources
from app.composition.sources import SourceResources
from app.domains.billing import paid_read, paid_router, work
from app.domains.billing import router as billing_routes
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import apply_customer_read, reserve_customer
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.reconciliation import (
    SOURCE_TRUST,
    apply_reconciliation,
    claim_reconciliation,
    read_source_time,
)
from app.domains.billing.reconciliation_contracts import ReconciliationSubject, SubscriptionProof
from app.domains.billing.work_contracts import DeliveryLane, WorkClaim, WorkLane
from app.domains.purchases.contracts import Purchase
from app.domains.purchases import widget_admission
from app.domains.purchases import widget_activation_poll
from app.domains.purchases import widget_activation_window as activation_windows
from app.domains.purchases.widget_activation import WidgetActivationOpening
from app.domains.purchases.widget_activation_window import (
    WidgetActivationCompletion,
    WidgetActivationCompletionReason,
    WidgetActivationWindow,
)
from app.infrastructure.persistence.billing_work import coalesce
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.infrastructure.queries import billing_reconciliation
from app.domains.purchases import financial
from app.integrations.lbx.errors import LbxUnavailable
from app.integrations.lbx.financial import Subscription
from app.integrations.lbx.reconciliation import read_subscription_proof
from app.jobs.billing import BillingWorker
from app.models import (
    BillingProductAccessScope,
    BillingPurchaseScopeHold,
    BillingStateObservation,
    BillingStateObservationKind,
    BillingWorkItem,
    BillingWorkKind,
    BillingWorkState,
    ExternalSubscription,
    ExternalSubscriptionCommercialAccessStatus,
    ExternalSubscriptionLifecycleStatus,
    ManualReviewCase,
    PaidAccessState,
    PurchasedAllowance,
    User,
)
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.postgres import alembic_test_config
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
def widget_app(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> FastAPI:
    from app.domains.purchases import router as purchase_routes
    from app.http.dependencies import get_session_factory
    from app.main import create_app

    configuration = step1_settings()
    monkeypatch.setattr(billing_routes, "settings", configuration)
    monkeypatch.setattr(purchase_routes, "settings", configuration)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: postgres_session_factory
    app.state.sources = scenario[1]
    return app


@pytest.fixture
async def portal(widget_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=widget_app, raise_app_exceptions=False),
        base_url="http://portal.test",
        headers={"Authorization": "Bearer " + TOKEN},
    ) as client:
        yield client


@pytest.fixture
async def cabinet(
    portal: httpx.AsyncClient,
    widget_app: FastAPI,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx.AsyncClient]:
    configuration = step1_settings()
    monkeypatch.setattr(paid_router, "settings", configuration)
    async with paid_read_resources(configuration, factory=postgres_session_factory) as reads:
        widget_app.state.paid_reads = reads
        yield portal


async def cabinet_status(client: httpx.AsyncClient) -> tuple[str | None, int]:
    response = await client.get("/api/paid-access")
    assert response.status_code == 200, response.json()
    body = response.json()
    (product,) = body["products"]
    assert product["product_id"] == "proposal_ai"
    return product["activation_check"], body["access_revision"]


def observation_count(factory: sessionmaker[Session], schema: str) -> int:
    with factory() as db:
        return db.scalar(
            select(func.count())
            .select_from(BillingStateObservation)
            .where(BillingStateObservation.evidence_schema_version == schema)
        )


async def payment(portal: httpx.AsyncClient, purchase_id: UUID) -> httpx.Response:
    return await portal.post("/api/billing/widget-bootstrap", json={"purchase_intent_id": str(purchase_id)})


async def payment_with_response_hook(
    app: FastAPI, purchase_id: UUID, on_sent: Callable[[], Awaitable[None]]
) -> httpx.Response:
    async def observe(scope: Scope, receive: Receive, send: Send) -> None:
        async def capture(message: Message) -> None:
            await send(message)
            if message["type"] == "http.response.body" and not message.get("more_body", False):
                await on_sent()

        await app(scope, receive, capture)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=observe),
        base_url="http://portal.test",
        headers={"Authorization": "Bearer " + TOKEN},
    ) as client:
        return await payment(client, purchase_id)


def activation_job(factory: sessionmaker[Session]) -> BillingWorkItem:
    with factory() as db:
        return db.scalars(
            select(BillingWorkItem).where(BillingWorkItem.work_kind == BillingWorkKind.WIDGET_ACTIVATION_CHECK)
        ).one()


def reconciliation_schedule(factory: sessionmaker[Session]) -> tuple[UUID, datetime, int]:
    with factory() as db:
        row = db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)).one()
        return row.work_item_id, row.next_attempt_at, row.enqueue_generation


def activation_schedule(row: BillingWorkItem) -> tuple[UUID, WidgetActivationWindow, datetime, int, datetime]:
    return (
        row.work_item_id,
        WidgetActivationWindow.from_work(row),
        row.next_attempt_at,
        row.enqueue_generation,
        row.updated_at,
    )


@dataclass
class ActivationPolling:
    factory: sessionmaker[Session]
    transport: PurchaseTransport
    worker: BillingWorker
    window: WidgetActivationWindow
    now: datetime

    async def tick(self, seconds_since_prepared: float, lane: WorkLane = WorkLane.NORMAL) -> bool:
        self.now = self.window.prepared_at + timedelta(seconds=seconds_since_prepared)
        return await self.worker.tick(lane)

    def job(self) -> BillingWorkItem:
        return activation_job(self.factory)


@pytest.fixture
async def activation_polling(
    scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[ActivationPolling]:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    has_terms = purchase.accepted.technical_terms is not None
    config = step1_settings(
        billing_widget_activation_window_seconds=110,
        purchase_test_terms_enabled=has_terms,
        paid_access_clock_skew_seconds=5 if has_terms else None,
    )
    monkeypatch.setattr(billing_routes, "settings", config)
    worker = BillingWorker(config, factory, sources.require_lbx())
    try:
        if has_terms:
            with factory() as db:
                for row in db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind != work.RECONCILIATION)):
                    row.next_attempt_at = billing_reconciliation.database_now(db) + timedelta(days=1)
                db.commit()
            assert await worker.tick(WorkLane.URGENT)  # Establish the ordinary cadence while still unpaid.
        assert (await payment(portal, purchase.id)).status_code == 200
        window = WidgetActivationWindow.from_work(activation_job(factory))
        if not has_terms:
            with factory() as db:
                for row in db.scalars(
                    select(BillingWorkItem).where(BillingWorkItem.work_kind != BillingWorkKind.WIDGET_ACTIVATION_CHECK)
                ):
                    row.next_attempt_at = window.deadline_at + timedelta(days=1)
                db.commit()

        transport.requests.clear()
        polling = ActivationPolling(factory, transport, worker, window, window.prepared_at)
        monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: polling.now)
        yield polling
    finally:
        await worker.aclose()


@pytest.mark.parametrize("scenario", [True], indirect=True)
@pytest.mark.parametrize("period_proven", [True, False], ids=["proven-period", "missing-period"])
@pytest.mark.parametrize("handoff_at", [40, 112], ids=["ordinary", "closing-grace"])
async def test_any897_activation_handoff_advances_real_reconciliation_and_first_grant(
    activation_polling: ActivationPolling,
    cabinet: httpx.AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    period_proven: bool,
    handoff_at: int,
) -> None:
    polling = activation_polling
    factory = polling.factory
    monkeypatch.setattr(paid_read, "database_now", lambda db: polling.now)
    assert await cabinet_status(cabinet) == ("checking", 0)
    with factory() as db:
        original = db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)).one()
        assert original.work_state == BillingWorkState.PENDING
    assert polling.window.prepared_at + timedelta(seconds=handoff_at + 2) < original.next_attempt_at
    assert await polling.tick(20)  # The unpaid subscription still reports waiting.
    waiting = snapshot(factory)
    point = polling.transport.subscriptions[0]
    point["state"] = 2
    if period_proven:
        start = polling.window.prepared_at.date().replace(day=1)
        next_month = (start + timedelta(days=32)).replace(day=1)
        point.update(
            subscription_start_date=start.isoformat(),
            subscription_instance_start_date=start.isoformat(),
            last_tariffication_period_start=start.isoformat(),
            last_tariffication_period_end=(next_month - timedelta(days=1)).isoformat(),
        )

    assert await polling.tick(handoff_at)
    with factory() as db:
        advanced = db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)).one()
        assert advanced.work_item_id == original.work_item_id
        assert advanced.next_attempt_at == polling.now < original.next_attempt_at
        assert advanced.enqueue_generation == original.enqueue_generation + 1
        assert db.scalar(select(PaidAccessState)) is None
        assert db.scalar(select(PurchasedAllowance)) is None
    assert snapshot(factory) == waiting
    assert WidgetActivationWindow.from_work(polling.job()).completion == WidgetActivationCompletion(
        reason=WidgetActivationCompletionReason.ACTIVATION_DETECTED,
        at=polling.now,
    )
    assert await cabinet_status(cabinet) == ("checking", 0)
    assert [(request.method, request.url.path) for request in polling.transport.requests] == [
        ("GET", "/api/rest/v1/subscriptions/567"),
        ("GET", "/api/rest/v1/subscriptions/567"),
    ]

    assert await polling.tick(handoff_at + 1, WorkLane.URGENT)
    with factory() as db:
        regular = db.get(BillingWorkItem, original.work_item_id)
        assert regular.last_attempt_started_at == polling.now
        assert regular.attempt_count == original.attempt_count + 1
        read = db.get(BillingStateObservation, db.get(ExternalSubscription, waiting[0]).latest_observation_id)
        assert read.observed_at == polling.now
        assert read.evidence_document["calendar_complete"] is period_proven
        assert db.scalar(select(PaidAccessState)) is None  # Inventory must select the first primary.
    assert await cabinet_status(cabinet) == ("checking", 0)

    assert await polling.tick(handoff_at + 2, WorkLane.URGENT)
    with factory() as db:
        state = db.scalars(select(PaidAccessState)).one()
        assert state.access_revision == 1 and state.committed_at == polling.now < original.next_attempt_at
        assert state.effective_state_document["grants"] == [{"product_id": "proposal_ai", "valid_until": None}]
        assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) == waiting[0]
        allowances = db.scalars(select(PurchasedAllowance)).all()
        assert len(allowances) == len(state.effective_state_document["allowances"]) == int(period_proven)
        if period_proven:
            (allowance,) = allowances
            assert allowance.subscription_id == waiting[0] and allowance.quantity == 100
    assert await cabinet_status(cabinet) == (None, 1)


@pytest.mark.parametrize("handoff", [False, True], ids=["closing-read", "handoff"])
async def test_any897_cabinet_uses_saved_window_and_handoff_cutoffs_without_writes(
    activation_polling: ActivationPolling, cabinet: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, handoff: bool
) -> None:
    polling = activation_polling
    monkeypatch.setattr(paid_read, "database_now", lambda db: polling.now)
    cutoff = polling.window.deadline_at + activation_windows.CLOSING_GRACE
    if handoff:
        polling.transport.subscriptions[0]["state"] = 2
        assert await polling.tick(20)
        cutoff = polling.now + activation_windows.HANDOFF_DISPLAY
        polling.transport.requests.clear()
    before = activation_schedule(polling.job())
    polling.now = cutoff - timedelta(microseconds=1)
    assert await cabinet_status(cabinet) == ("checking", 0)
    assert await cabinet_status(cabinet) == ("checking", 0)  # Reload under the same saved window.
    polling.now = cutoff
    assert await cabinet_status(cabinet) == ("unconfirmed", 0)
    assert activation_schedule(polling.job()) == before and polling.transport.requests == []


@pytest.mark.parametrize(
    "outcome", ["ineligible", "expired", "conflict", "ended", "mismatched-window", "invalid-window"]
)
async def test_any897_cabinet_distinguishes_terminal_outcomes_from_pending(
    activation_polling: ActivationPolling, cabinet: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    polling = activation_polling
    monkeypatch.setattr(paid_read, "database_now", lambda db: polling.now)
    assert await cabinet_status(cabinet) == ("checking", 0)
    with polling.factory() as db:
        job = db.get(BillingWorkItem, polling.job().work_item_id)
        sub = db.scalars(select(ExternalSubscription)).one()
        match outcome:
            case "conflict":
                db.add(
                    ManualReviewCase(
                        scope_kind="subscription",
                        scope_reference=str(sub.subscription_id),
                        case_state="open",
                        reason_code="subscription_identity_conflict",
                        evidence_schema_version="subscription-reconciliation:v2",
                        evidence_document={},
                    )
                )
            case "ended":
                sub.lifecycle_status = ExternalSubscriptionLifecycleStatus.ENDED
            case "mismatched-window":
                job.payload_document = {**job.payload_document, "purchase_id": str(sub.subscription_id)}
            case "invalid-window":
                job.payload_document = {**job.payload_document, "deadline_at": "invalid"}
            case _:
                reason = (
                    WidgetActivationCompletionReason.WINDOW_EXPIRED
                    if outcome == "expired"
                    else WidgetActivationCompletionReason.PURCHASE_INELIGIBLE
                )
                completion = WidgetActivationCompletion(reason=reason, at=polling.now)
                job.payload_document = {**job.payload_document, "completion": completion.model_dump(mode="json")}
                job.work_state = BillingWorkState.COMPLETED
        db.commit()
    expected = "unconfirmed" if outcome in {"expired", "mismatched-window", "invalid-window"} else None
    assert await cabinet_status(cabinet) == (expected, 0)
    assert polling.transport.requests == []


@pytest.mark.parametrize("scenario", [True], indirect=True)
async def test_any897_cabinet_reads_grant_when_activation_arrives_after_the_window(
    activation_polling: ActivationPolling, cabinet: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    polling = activation_polling
    monkeypatch.setattr(paid_read, "database_now", lambda db: polling.now)
    regular = reconciliation_schedule(polling.factory)
    assert await polling.tick(115)
    assert (
        WidgetActivationWindow.from_work(polling.job()).completion.reason
        == WidgetActivationCompletionReason.WINDOW_EXPIRED
    )
    assert await cabinet_status(cabinet) == ("unconfirmed", 0)
    assert reconciliation_schedule(polling.factory) == regular
    polling.transport.subscriptions[0]["state"] = 2
    due = (regular[1] - polling.window.prepared_at).total_seconds()
    assert due > 115
    assert await polling.tick(due, WorkLane.URGENT)
    assert await polling.tick(due + 1, WorkLane.URGENT)
    assert await cabinet_status(cabinet) == (None, 1)


async def test_any897_cabinet_without_window_requires_fresh_waiting_evidence(
    scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    cabinet: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    assert await cabinet_status(cabinet) == (None, 0)
    await run(sources, factory)
    transport.requests.clear()
    assert await cabinet_status(cabinet) == ("unconfirmed", 0)
    with factory() as db:
        sub = db.scalars(select(ExternalSubscription)).one()
        observed = db.get(BillingStateObservation, sub.latest_observation_id)
        stale_at = datetime.fromisoformat(observed.evidence_document["read_started_at"]) + SOURCE_TRUST
        assert (
            db.scalar(
                select(BillingWorkItem).where(BillingWorkItem.work_kind == BillingWorkKind.WIDGET_ACTIVATION_CHECK)
            )
            is None
        )
    monkeypatch.setattr(paid_read, "database_now", lambda db: stale_at)
    assert await cabinet_status(cabinet) == (None, 0)
    assert not transport.requests


async def test_any897_worker_reads_only_the_saved_subscription_once_per_current_slot(
    activation_polling: ActivationPolling,
) -> None:
    polling = activation_polling
    with polling.factory() as db:
        regular = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        reconciliation = (regular.work_item_id, regular.next_attempt_at, regular.enqueue_generation)
    assert not await polling.tick(19)
    assert await polling.tick(20)
    assert not await polling.tick(20)
    assert await polling.tick(83)
    assert not await polling.tick(83)
    assert [(request.method, request.url.path) for request in polling.transport.requests] == [
        ("GET", "/api/rest/v1/subscriptions/567"),
        ("GET", "/api/rest/v1/subscriptions/567"),
    ]
    job = polling.job()
    assert job.attempt_count == 2
    assert job.next_attempt_at == polling.window.prepared_at + timedelta(seconds=100)
    assert WidgetActivationWindow.from_work(job).completion is None
    with polling.factory() as db:
        regular = db.get(BillingWorkItem, reconciliation[0])
        assert (regular.next_attempt_at, regular.enqueue_generation) == reconciliation[1:]
        assert db.scalar(select(PaidAccessState)) is None


async def test_any897_worker_claims_activation_only_after_due_normal_work(
    activation_polling: ActivationPolling,
) -> None:
    polling = activation_polling
    polling.now += timedelta(seconds=45)
    with polling.factory() as db:
        regular = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        regular.next_attempt_at = polling.now
        regular.priority = 0
        sub = db.scalar(select(ExternalSubscription))
        sub.projection_valid_until = polling.now + timedelta(hours=1)
        db.commit()
    claim = work.claim_work(polling.factory, polling.worker.configuration, WorkLane.NORMAL)
    assert claim is not None and claim.kind == work.RECONCILIATION
    with polling.factory() as db:
        db.scalar(select(ExternalSubscription)).projection_valid_until = polling.now
        db.commit()
    assert not await polling.tick(45, WorkLane.URGENT)
    assert await polling.tick(45)
    assert len(polling.transport.requests) == 1 and polling.job().attempt_count == 1


async def test_any897_failed_read_waits_for_first_slot_at_least_40_seconds_later(
    activation_polling: ActivationPolling,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    polling = activation_polling
    get = polling.worker.client.get_subscription
    logical_reads: list[datetime] = []

    async def fail_once(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        logical_reads.append(polling.now)
        if len(logical_reads) == 1:
            raise LbxUnavailable()
        return await get(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(polling.worker.client, "get_subscription", fail_once)
    assert await polling.tick(27)
    assert polling.job().next_attempt_at == polling.window.prepared_at + timedelta(seconds=80)
    for time in (40, 60, 67, 79):
        assert not await polling.tick(time)
    assert await polling.tick(80)
    assert logical_reads == [polling.window.prepared_at + timedelta(seconds=seconds) for seconds in (27, 80)]
    assert polling.job().attempt_count == 2 and polling.job().last_error_classification is None


@pytest.mark.parametrize("picked_at,expected_reads", [(110, 1), (112, 1), (115, 0), (116, 0)])
async def test_any897_closing_read_is_once_and_never_outside_the_grace_period(
    activation_polling: ActivationPolling,
    monkeypatch: pytest.MonkeyPatch,
    picked_at: int,
    expected_reads: int,
) -> None:
    polling = activation_polling
    get = polling.worker.client.get_subscription
    budgets: list[float] = []

    async def record_budget(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        budgets.append(budget.deadline - monotonic())
        return await get(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(polling.worker.client, "get_subscription", record_budget)
    assert await polling.tick(picked_at)
    assert not await polling.tick(picked_at + 1)
    assert len(polling.transport.requests) == len(budgets) == expected_reads
    assert all(0 < seconds <= 115 - picked_at for seconds in budgets)
    job = polling.job()
    assert job.attempt_count == expected_reads and job.work_state == BillingWorkState.COMPLETED
    assert WidgetActivationWindow.from_work(job).completion == WidgetActivationCompletion(
        reason=WidgetActivationCompletionReason.WINDOW_EXPIRED,
        at=polling.window.prepared_at + timedelta(seconds=picked_at),
    )


@pytest.mark.parametrize("blocked_by", ["backoff", "lost_binding", "changed_before_lock"])
async def test_any897_closing_read_still_requires_backoff_and_eligibility(
    activation_polling: ActivationPolling,
    monkeypatch: pytest.MonkeyPatch,
    blocked_by: str,
) -> None:
    polling = activation_polling
    if blocked_by == "backoff":

        async def fail(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
            raise LbxUnavailable()

        with monkeypatch.context() as patch:
            patch.setattr(polling.worker.client, "get_subscription", fail)
            assert await polling.tick(73)
        assert polling.job().next_attempt_at == polling.window.deadline_at
    elif blocked_by == "lost_binding":
        with polling.factory() as db:
            db.scalar(select(ExternalSubscription)).purchase_intent_id = None
            db.commit()
    else:
        lock = widget_activation_poll.lock_user

        def change_then_lock(db: Session, user_id: UUID) -> User:
            with polling.factory() as concurrent:
                concurrent.scalar(
                    select(ExternalSubscription)
                ).commercial_access_status = ExternalSubscriptionCommercialAccessStatus.INELIGIBLE
                concurrent.commit()
            return lock(db, user_id)

        monkeypatch.setattr(widget_activation_poll, "lock_user", change_then_lock)
    assert await polling.tick(113)
    assert not polling.transport.requests
    assert polling.job().attempt_count == (1 if blocked_by == "backoff" else 0)
    assert WidgetActivationWindow.from_work(polling.job()).completion.reason == (
        WidgetActivationCompletionReason.WINDOW_EXPIRED
        if blocked_by == "backoff"
        else WidgetActivationCompletionReason.PURCHASE_INELIGIBLE
    )


async def test_any897_closing_timeout_retains_source_cleanup_ownership(
    activation_polling: ActivationPolling,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    polling = activation_polling
    cleaning = asyncio.Event()
    release = asyncio.Event()
    reads: list[int] = []

    async def slow(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        async def blocked() -> Subscription:
            reads.append(subscription_id)
            try:
                await asyncio.Future()
            finally:
                with budget.protect_source_cleanup():
                    cleaning.set()
                    await release.wait()
            raise AssertionError("the blocked read returned")

        return await budget.run(blocked)

    monkeypatch.setattr(polling.worker.client, "get_subscription", slow)
    try:
        assert await asyncio.wait_for(polling.tick(114.25), timeout=3)
        assert reads == [567] and cleaning.is_set()
        assert polling.worker.admissions[WorkLane.NORMAL].cleanup_pending_count == 1
        assert not await polling.tick(114.5)
        job = polling.job()
        assert job.last_error_classification == PreflightDeadlineExceeded().code
        assert (
            WidgetActivationWindow.from_work(job).completion.reason == WidgetActivationCompletionReason.WINDOW_EXPIRED
        )
    finally:
        release.set()


@pytest.mark.parametrize("starts_at, cutoff", [(109, 110), (112, 115)], ids=["ordinary", "closing"])
async def test_any897_late_positive_response_is_discarded(
    activation_polling: ActivationPolling,
    monkeypatch: pytest.MonkeyPatch,
    starts_at: int,
    cutoff: int,
) -> None:
    polling = activation_polling
    original = reconciliation_schedule(polling.factory)
    activate(polling.transport)
    get = polling.worker.client.get_subscription

    async def returned_after_cutoff(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        assert 0 < budget.deadline - monotonic() <= cutoff - starts_at
        point = await get(subscription_id=subscription_id, budget=budget)
        polling.now = polling.window.prepared_at + timedelta(seconds=cutoff, milliseconds=1)
        return point

    monkeypatch.setattr(polling.worker.client, "get_subscription", returned_after_cutoff)
    assert await polling.tick(starts_at)
    assert not await polling.tick(cutoff + 1)
    job = polling.job()
    assert len(polling.transport.requests) == job.attempt_count == 1
    assert job.last_error_classification == PreflightDeadlineExceeded().code
    assert WidgetActivationWindow.from_work(job).completion.reason == WidgetActivationCompletionReason.WINDOW_EXPIRED
    assert reconciliation_schedule(polling.factory) == original


@pytest.mark.parametrize("changed", ["binding", "primary", "lease", "generation"])
async def test_any897_activation_handoff_rechecks_binding_and_claim_after_point_read(
    activation_polling: ActivationPolling,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    polling = activation_polling
    factory = polling.factory
    original = reconciliation_schedule(factory)
    activate(polling.transport)
    get = polling.worker.client.get_subscription

    async def change_before_apply(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        point = await get(subscription_id=subscription_id, budget=budget)
        with factory() as db:
            if changed in {"binding", "primary"}:
                sub = db.scalar(select(ExternalSubscription))
                if changed == "binding":
                    sub.purchase_intent_id = None
                else:
                    db.scalar(select(BillingProductAccessScope)).primary_subscription_id = sub.subscription_id
            else:
                row = db.scalar(
                    select(BillingWorkItem).where(BillingWorkItem.work_kind == BillingWorkKind.WIDGET_ACTIVATION_CHECK)
                )
                if changed == "lease":
                    row.lease_owner = "replacement"
                else:
                    row.enqueue_generation += 1
            db.commit()
        return point

    monkeypatch.setattr(polling.worker.client, "get_subscription", change_before_apply)
    if changed in {"lease", "generation"}:
        with pytest.raises(BillingRefused, match="billing_work_stale"):
            await polling.tick(20)
        assert WidgetActivationWindow.from_work(polling.job()).completion is None
    else:
        assert await polling.tick(20)
        assert WidgetActivationWindow.from_work(polling.job()).completion.reason == (
            WidgetActivationCompletionReason.PURCHASE_INELIGIBLE
        )
    assert reconciliation_schedule(factory) == original


@pytest.mark.parametrize("state,blocking", [(2, 1), (2, 3), (3, 0)])
async def test_any897_blocked_or_ended_point_never_advances_reconciliation(
    activation_polling: ActivationPolling,
    state: int,
    blocking: int,
) -> None:
    polling = activation_polling
    original = reconciliation_schedule(polling.factory)
    polling.transport.subscriptions[0].update(state=state, current_blocking=blocking)
    assert await polling.tick(20)
    completed = WidgetActivationWindow.from_work(polling.job()).completion
    if state == 3:
        assert completed.reason == WidgetActivationCompletionReason.PURCHASE_INELIGIBLE
    else:
        assert completed is None
    assert reconciliation_schedule(polling.factory) == original


async def test_any897_handoff_past_cutoff_rolls_back_hint_and_expires_window(
    activation_polling: ActivationPolling,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    polling = activation_polling
    original = reconciliation_schedule(polling.factory)
    activate(polling.transport)
    enroll = work.enroll_subscription

    def advance_then_cross_cutoff(db: Session, subscription: ExternalSubscription, *, hint: bool = False) -> None:
        enroll(db, subscription, hint=hint)
        polling.now = polling.window.deadline_at + timedelta(seconds=5, milliseconds=1)

    monkeypatch.setattr(work, "enroll_subscription", advance_then_cross_cutoff)
    assert await polling.tick(112)
    assert polling.now > polling.window.deadline_at + timedelta(seconds=5)
    assert len(polling.transport.requests) == 1
    assert reconciliation_schedule(polling.factory) == original
    assert (
        WidgetActivationWindow.from_work(polling.job()).completion.reason
        == WidgetActivationCompletionReason.WINDOW_EXPIRED
    )


async def test_any897_handoff_hint_survives_running_reconciliation(
    activation_polling: ActivationPolling,
) -> None:
    polling = activation_polling
    factory = polling.factory
    identity, _, generation = reconciliation_schedule(factory)
    with factory() as db:
        db.get(BillingWorkItem, identity).next_attempt_at = polling.now
        db.commit()
    claim = work.claim_work(factory, polling.worker.configuration, WorkLane.URGENT)
    assert claim is not None and claim.id == identity
    activate(polling.transport)
    assert await polling.tick(20)
    with factory() as db:
        row = db.get(BillingWorkItem, identity)
        assert row.enqueue_generation == generation + 1
        assert row.work_state == BillingWorkState.RUNNING and row.lease_owner == claim.owner
        assert row.next_attempt_at <= polling.now
    polling.now += timedelta(seconds=1)
    await orchestration.reconcile_subscription(
        polling.worker.client,
        polling.worker.admissions[WorkLane.URGENT],
        polling.worker.configuration,
        factory=factory,
        subscription_id=UUID(claim.reference),
        work_claim=claim,
    )
    with factory() as db:
        row = db.get(BillingWorkItem, identity)
        assert row.work_state == BillingWorkState.PENDING and row.lease_owner is None
        assert row.enqueue_generation == generation + 1 and row.next_attempt_at <= polling.now
    assert await polling.tick(22, WorkLane.URGENT)


async def test_any897_parallel_widget_openings_save_one_window(
    scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    widget_app: FastAPI,
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    _, sources, purchase = scenario
    factory = postgres_session_factory
    first_opening = read_source_time(factory)
    opening_times = (first_opening, first_opening + timedelta(microseconds=1))
    database_now = widget_admission.database_now
    prepared = iter(opening_times)

    def preparation_clock(db: Session) -> datetime:
        return next(prepared, None) or database_now(db)

    monkeypatch.setattr(widget_admission, "database_now", preparation_clock)
    sent: asyncio.Queue[None] = asyncio.Queue()
    release = asyncio.Event()

    async def after_send() -> None:
        await sent.put(None)
        await release.wait()

    async with asyncio.TaskGroup() as group:
        first = group.create_task(payment_with_response_hook(widget_app, purchase.id, after_send))
        await asyncio.wait_for(sent.get(), timeout=10)
        second = group.create_task(payment_with_response_hook(widget_app, purchase.id, after_send))
        await asyncio.wait_for(sent.get(), timeout=10)
        with factory() as db:
            assert (
                db.scalar(
                    select(BillingWorkItem).where(BillingWorkItem.work_kind == BillingWorkKind.WIDGET_ACTIVATION_CHECK)
                )
                is None
            )
        release.set()
    assert first.result().status_code == second.result().status_code == 200
    assert not any(record.message == "widget_activation_enqueue_failed" for record in caplog.records)
    saved = activation_job(factory)
    window = WidgetActivationWindow.from_work(saved)
    assert window.purchase_id == purchase.id
    assert window.prepared_at in opening_times
    assert window.deadline_at == window.prepared_at + timedelta(minutes=5)
    assert saved.next_attempt_at == window.prepared_at + timedelta(seconds=20)
    assert window.completion is None and saved.enqueue_generation == 0
    assert saved.coalescing_key == f"{purchase.account_id}:{snapshot(factory)[0]}"

    configuration = step1_settings(billing_widget_activation_window_seconds=600)
    monkeypatch.setattr(billing_routes, "settings", configuration)
    assert (await payment(portal, purchase.id)).status_code == 200
    assert activation_schedule(activation_job(factory)) == activation_schedule(saved)

    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: first_opening + timedelta(seconds=1))
    polled = asyncio.Event()
    tick = BillingWorker.tick

    async def record_tick(worker: BillingWorker, lane: WorkLane | DeliveryLane) -> bool:
        result = await tick(worker, lane)
        if lane == WorkLane.NORMAL:
            polled.set()
        return result

    monkeypatch.setattr(BillingWorker, "tick", record_tick)
    for config in (step1_settings(), configuration):
        polled.clear()
        worker = BillingWorker(config, factory, sources.require_lbx())
        try:
            await worker.start()
            await asyncio.wait_for(polled.wait(), timeout=10)
        finally:
            await worker.aclose()
        assert activation_schedule(activation_job(factory)) == activation_schedule(saved)


@pytest.mark.parametrize(
    "completion_reason,completion_offset,reopen_offset",
    [
        (None, 0, 5),
        (WidgetActivationCompletionReason.ACTIVATION_DETECTED, -10, 50),
        (WidgetActivationCompletionReason.ACTIVATION_DETECTED, -120, 5),
        (WidgetActivationCompletionReason.WINDOW_EXPIRED, 5, 5),
        (WidgetActivationCompletionReason.PURCHASE_INELIGIBLE, -10, 5),
    ],
    ids=["lease", "handoff-grace", "closing-grace-after-handoff", "expired", "ineligible"],
)
async def test_any897_reopening_enforces_saved_window_and_lease_bounds(
    scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    completion_reason: WidgetActivationCompletionReason | None,
    completion_offset: int,
    reopen_offset: int,
) -> None:
    _, _, purchase = scenario
    factory = postgres_session_factory
    prepared_at = callback_at = read_source_time(factory)
    monkeypatch.setattr(widget_admission, "database_now", lambda db: prepared_at)
    monkeypatch.setattr(activation_windows, "database_now", lambda db: callback_at)
    assert (await payment(portal, purchase.id)).status_code == 200
    saved = activation_job(factory)
    original = WidgetActivationWindow.from_work(saved)
    monkeypatch.setattr(billing_routes, "settings", step1_settings(billing_widget_activation_window_seconds=420))
    completed_at = original.deadline_at + timedelta(seconds=completion_offset)
    earliest = original.deadline_at + timedelta(seconds=reopen_offset)

    with factory() as db:
        row = db.get(BillingWorkItem, saved.work_item_id)
        completion = None
        if completion_reason is None:
            row.work_state = BillingWorkState.RUNNING
            row.lease_owner = "test-worker"
            row.lease_expires_at = earliest + timedelta(seconds=1)
        else:
            completion = WidgetActivationCompletion(reason=completion_reason, at=completed_at)
            row.payload_document = original.model_copy(update={"completion": completion}).model_dump(mode="json")
            row.work_state = BillingWorkState.COMPLETED
        row.next_attempt_at = original.deadline_at
        row.last_attempt_started_at = original.deadline_at - timedelta(seconds=20)
        row.attempt_count = 3
        db.commit()
    prior_job = activation_job(factory)
    assert WidgetActivationWindow.from_work(prior_job).completion == completion

    # This callback runs past the threshold, but the Widget opened too early.
    prepared_at = earliest - timedelta(microseconds=1)
    callback_at = earliest + timedelta(seconds=1)
    assert (await payment(portal, purchase.id)).status_code == 200
    assert activation_schedule(activation_job(factory)) == activation_schedule(prior_job)

    prepared_at = earliest
    if prior_job.lease_expires_at is not None:
        callback_at = prior_job.lease_expires_at - timedelta(microseconds=1)
        assert (await payment(portal, purchase.id)).status_code == 200
        assert activation_schedule(activation_job(factory)) == activation_schedule(prior_job)
        callback_at = prior_job.lease_expires_at

    assert (await payment(portal, purchase.id)).status_code == 200
    reopened = activation_job(factory)
    assert WidgetActivationWindow.from_work(reopened) == WidgetActivationWindow(
        purchase_id=purchase.id, prepared_at=earliest, deadline_at=earliest + timedelta(minutes=7)
    )
    assert reopened.work_item_id == saved.work_item_id
    assert reopened.enqueue_generation == saved.enqueue_generation + 1
    assert reopened.next_attempt_at == earliest + timedelta(seconds=20)
    assert reopened.work_state == BillingWorkState.PENDING and reopened.attempt_count == 0
    assert reopened.last_attempt_started_at is reopened.lease_owner is reopened.lease_expires_at is None

    prepared_at = earliest - timedelta(microseconds=1)
    assert (await payment(portal, purchase.id)).status_code == 200
    assert activation_schedule(activation_job(factory)) == activation_schedule(reopened)


async def test_any897_expired_callbacks_and_purchases_that_no_longer_wait_cannot_save_windows(
    scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, _, purchase = scenario
    factory = postgres_session_factory
    prepared_at = read_source_time(factory)
    callback_at = prepared_at + timedelta(minutes=5)
    monkeypatch.setattr(widget_admission, "database_now", lambda db: prepared_at)
    monkeypatch.setattr(activation_windows, "database_now", lambda db: callback_at)
    assert (await payment(portal, purchase.id)).status_code == 200
    with factory() as db:
        assert (
            db.scalar(
                select(BillingWorkItem).where(BillingWorkItem.work_kind == BillingWorkKind.WIDGET_ACTIVATION_CHECK)
            )
            is None
        )

    prepared_at = callback_at
    assert (await payment(portal, purchase.id)).status_code == 200
    saved = activation_job(factory)
    prepared_at = WidgetActivationWindow.from_work(saved).deadline_at + timedelta(seconds=5)
    callback_at = prepared_at
    activate(transport)
    assert (await payment(portal, purchase.id)).status_code == 200
    assert activation_schedule(activation_job(factory)) == activation_schedule(saved)

    transport.subscriptions[0]["state"] = -2
    callback_at = prepared_at + timedelta(minutes=5)
    assert (await payment(portal, purchase.id)).status_code == 200
    assert activation_schedule(activation_job(factory)) == activation_schedule(saved)


async def test_any897_migrated_queue_enforces_one_key_even_after_completion(
    scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    database_test_url: URL,
) -> None:
    _, _, purchase = scenario
    factory = postgres_session_factory
    assert (await payment(portal, purchase.id)).status_code == 200
    saved = activation_job(factory)
    with factory() as db:
        row = db.get(BillingWorkItem, saved.work_item_id)
        row.work_state = BillingWorkState.COMPLETED
        window = WidgetActivationWindow.from_work(row)
        row.payload_document = window.model_copy(
            update={
                "completion": WidgetActivationCompletion(
                    reason=WidgetActivationCompletionReason.PURCHASE_INELIGIBLE,
                    at=window.prepared_at,
                )
            }
        ).model_dump(mode="json")
        db.commit()
    completed = activation_job(factory)
    with factory() as db:
        duplicate = BillingWorkItem(
            work_kind=saved.work_kind,
            scope_kind=saved.scope_kind,
            scope_reference=saved.scope_reference,
            coalescing_key=saved.coalescing_key,
            payload_schema_version=saved.payload_schema_version,
            payload_document=saved.payload_document,
            next_attempt_at=saved.next_attempt_at,
            work_state=BillingWorkState.PENDING,
        )
        with pytest.raises(IntegrityError, match="uq_billing_work_items_widget_activation"), db.begin_nested():
            db.add(duplicate)
            db.flush()

    with alembic_test_config(database_test_url) as migration:
        with pytest.raises(RuntimeError, match="Widget activation windows require the unique queue key"):
            command.downgrade(migration, "20261113_0013")
    assert activation_schedule(activation_job(factory)) == activation_schedule(completed)


@pytest.mark.parametrize("after_response", ["write_fails", "scope_released", "unlinked", "activated"])
async def test_any897_background_check_runs_after_widget_response_and_rechecks_purchase(
    scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    widget_app: FastAPI,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    after_response: str,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    subscription_id = snapshot(factory)[0]
    writes: list[WidgetActivationOpening] = []
    preparation_times: list[datetime] = []
    sent_at: datetime | None = None
    scheduled_work: tuple[UUID, int, datetime] | None = None
    database_now = widget_admission.database_now

    def record_preparation_time(db: Session) -> datetime:
        now = database_now(db)
        preparation_times.append(now)
        return now

    monkeypatch.setattr(widget_admission, "database_now", record_preparation_time)

    def writer(db: Session, opening: WidgetActivationOpening) -> None:
        assert sent_at is not None
        writes.append(opening)
        assert db.in_transaction()
        assert db.scalar(select(func.current_setting("lock_timeout"))) != "0"
        raise RuntimeError("private test canary")

    widget_app.dependency_overrides[billing_routes.get_widget_activation_writer] = lambda: writer

    async def on_sent() -> None:
        nonlocal sent_at, scheduled_work
        sent_at = read_source_time(factory)
        if after_response == "write_fails":
            with factory() as db:
                job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
                scheduled_work = (job.work_item_id, job.enqueue_generation, job.next_attempt_at)
        elif after_response == "activated":
            activate(transport)
            await run(sources, factory)
        else:
            with factory() as db:
                if after_response == "scope_released":
                    db.delete(
                        db.get(BillingPurchaseScopeHold, (purchase.user_id, purchase.accepted.selection.product_id))
                    )
                else:
                    db.get(ExternalSubscription, subscription_id).purchase_intent_id = None
                db.commit()

    started_at = read_source_time(factory)
    response = await payment_with_response_hook(widget_app, purchase.id, on_sent)
    assert response.status_code == 200 and response.json()["disablePayments"] is False
    failures = [record for record in caplog.records if record.message == "widget_activation_enqueue_failed"]
    if after_response != "write_fails":
        assert not writes and not failures
        return

    (opening,) = writes
    assert (opening.user_id, opening.purchase_id, opening.customer_id, opening.account_id, opening.subscription_id) == (
        purchase.user_id,
        purchase.id,
        purchase.customer_id,
        purchase.account_id,
        subscription_id,
    )
    assert sent_at is not None
    assert started_at <= opening.prepared_at <= sent_at
    assert preparation_times == [opening.prepared_at]
    (failure,) = failures
    assert failure.structured["error_type"] == "RuntimeError" and "private test canary" not in caplog.text

    # Activation is processed by the original scheduled job without another Widget open.
    activate(transport)
    with factory() as db:
        job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        assert job.work_state == "pending"
        assert (job.work_item_id, job.enqueue_generation, job.next_attempt_at) == scheduled_work
        job.next_attempt_at = database_now(db) - timedelta(seconds=1)
        job.priority = 1
        db.commit()
    worker = BillingWorker(step1_settings(paid_access_clock_skew_seconds=5), factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.URGENT)
        assert snapshot(factory)[1:3] == ("active", "allowed")
        assert await worker.tick(WorkLane.URGENT)
    finally:
        await worker.aclose()
    with factory() as db:
        state = db.scalar(select(PaidAccessState).where(PaidAccessState.user_id == purchase.user_id))
        assert state.access_revision == 1
        assert state.effective_state_document["grants"][0]["product_id"] == purchase.accepted.selection.product_id


@pytest.mark.parametrize(
    "mode", ["account", "inactive", "active", "current_primary", "previous_primary", "operator_primary"]
)
async def test_any897_only_waiting_first_activation_is_scheduled(
    scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    widget_app: FastAPI,
    portal: httpx.AsyncClient,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    if mode == "inactive":
        transport.subscriptions[0]["state"] = -1
    elif mode == "active":
        activate(transport)
    elif mode in {"current_primary", "previous_primary", "operator_primary"}:
        activate(transport)
        basis = await run(sources, factory)
        transport.subscriptions[0]["state"] = -2
        with factory() as db:
            scope = db.get(BillingProductAccessScope, basis.access_scope_id)
            if mode == "current_primary":
                scope.primary_subscription_id = basis.subscription_id
            else:
                operator = mode == "operator_primary"
                db.add(
                    BillingStateObservation(
                        observation_kind=BillingStateObservationKind.AUTHORITATIVE_SUBSCRIPTION_READ
                        if operator
                        else BillingStateObservationKind.PRIMARY_SELECTION,
                        external_billing_account_id=purchase.account_id,
                        user_id=purchase.user_id,
                        product_id=purchase.accepted.selection.product_id,
                        access_scope_id=scope.access_scope_id,
                        subscription_id=basis.subscription_id,
                        basis_observation_id=None if operator else basis.observation_id,
                        observed_at=basis.observed_at,
                        evidence_schema_version=basis.evidence_schema_version if operator else "primary-selection:v2",
                        evidence_document={
                            **basis.evidence_document,
                            "primary_selection": {"review_case_id": str(basis.observation_id), "principal": "test"},
                        }
                        if operator
                        else {"source_observation_id": str(basis.observation_id)},
                        completeness_classification=basis.completeness_classification,
                        result_classification=basis.result_classification if operator else "primary_selected",
                    )
                )
            db.commit()

    scheduled: list[Callable[..., object]] = []

    def add_task(tasks: BackgroundTasks, function: Callable[..., object], *args: object, **kwargs: object) -> None:
        scheduled.append(function)

    def writer(db: Session, opening: WidgetActivationOpening) -> None:
        pytest.fail("an ineligible Widget opening reached the activation writer")

    monkeypatch.setattr("starlette.background.BackgroundTasks.add_task", add_task)
    widget_app.dependency_overrides[billing_routes.get_widget_activation_writer] = lambda: writer
    response = (
        await portal.post("/api/billing/widget-bootstrap", json={})
        if mode == "account"
        else await payment(portal, purchase.id)
    )
    assert response.status_code == 200
    assert scheduled == []


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
        assert latest.evidence_schema_version == "subscription-reconciliation:v2"
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
            .where(BillingStateObservation.evidence_schema_version == "subscription-reconciliation:v2")
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
async def test_payment_with_incomplete_paid_calendar_refreshes_only_product_trust(
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
    current = snapshot(factory)
    assert current[0] == trusted[0]
    assert current[1:4] == ("active", "allowed", "eligible")
    assert current[4] > trusted[4] and current[5] - current[4] == timedelta(hours=6)
    assert current[6] != trusted[6]
    with factory() as db:
        attempt = db.scalar(
            select(BillingStateObservation)
            .where(BillingStateObservation.evidence_schema_version == "subscription-reconciliation:v2")
            .order_by(BillingStateObservation.observed_at.desc())
        )
        assert attempt.completeness_classification == "complete"
        assert attempt.evidence_document["calendar_complete"] is False
        assert "current_calendar_incomplete" in attempt.evidence_document["reasons"]
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0


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
    initial_count = observation_count(factory, "subscription-reconciliation:v2")
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
    assert observation_count(factory, "subscription-reconciliation:v2") == initial_count
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
