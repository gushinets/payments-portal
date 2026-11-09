"""SIMULATED late original proofs; real claims, locks, pause and notification work."""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import billing_background
from app.composition.billing import bootstrap_account
from app.composition.purchases import recover_financial
from app.composition.sources import SourceResources, source_resources
from app.domains.billing import background_recovery as recovery, customers
from app.domains.billing.work_contracts import RecoveryEscalation, WorkLane
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase
from app.infrastructure.queries import billing_reconciliation
from app.integrations.lbx.financial import NewAgreement
from app.jobs.billing import BillingWorker
from app.models import ExternalCreateOperation, ExternalCreateOperationKind as Kind
from apps.api.tests.factories.reconciliation import agreement_factory
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_step3_postgres import TOKEN, accept, setup_purchase
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    job,
    original,
    synthetic_prepare,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
async def uncertain_case(
    kind: Kind,
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[PurchaseTransport, SourceResources, UUID, Purchase | None]]:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    factory, configuration = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    async with source_resources(
        configuration,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = None if kind == Kind.CUSTOMER else await accept(sources, factory)
        customer = customers.reserve_customer(factory, configuration, TOKEN)
        customer = customers.claim_customer_send(factory, configuration, TOKEN, customer)
        transport.customer = {"user_id": 345, "outer_id": customer.outer_key}
        identity = customer.operation_id
        if purchase is not None:
            customers.apply_customer_read(factory, customer, provider_id="345", outer_key=customer.outer_key)
            if kind == Kind.SUBSCRIPTION:
                purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
            else:
                operation = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
                command = NewAgreement(
                    user_id=345, organization_id=21, agreement_number=operation.key, create_date=date(2026, 10, 27)
                )
                financial.claim_financial(
                    factory, purchase, operation, command.request_document(), configuration=configuration, token=TOKEN
                )
                transport.agreements.append({**agreement_factory().model_dump(), **command.request_document()})
                purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
            identity = next(op.id for op in purchase.operations if op.kind == kind)
        yield transport, sources, identity, purchase


@pytest.mark.parametrize("kind", [Kind.CUSTOMER, Kind.AGREEMENT, Kind.SUBSCRIPTION])
@pytest.mark.parametrize("timing", ["before_deadline", "deadline_pending", "deadline_applied"])
async def test_automatic_binding_checks_deadline_at_apply(
    uncertain_case: tuple[PurchaseTransport, SourceResources, UUID, Purchase | None],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    kind: Kind,
    timing: str,
) -> None:
    transport, sources, identity, purchase = uncertain_case
    factory, configuration = postgres_session_factory, step1_settings()
    immutable = original(factory, identity)
    window = job(factory, recovery.DEADLINE, identity).next_attempt_at
    now = window - timedelta(seconds=1)
    # All DB-clock aliases share one clock; advancing across the business
    # deadline must leave the queue lease valid and the proof otherwise current.
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: now)
    monkeypatch.setattr(financial, "database_now", lambda db: now)
    entered, release = asyncio.Event(), asyncio.Event()
    point_method = {Kind.CUSTOMER: "get_user", Kind.AGREEMENT: "get_agreement", Kind.SUBSCRIPTION: "get_subscription"}[
        kind
    ]
    point_get = getattr(sources.require_lbx(), point_method)

    async def held_point(**kwargs: Any) -> Any:
        value = await point_get(**kwargs)
        entered.set()
        await release.wait()
        return value

    monkeypatch.setattr(sources.require_lbx(), point_method, held_point)
    notices: list[RecoveryEscalation] = []

    def report(notice: RecoveryEscalation) -> bool:
        assert factory.kw["bind"].pool.checkedout() == 0
        notices.append(notice)
        return True

    monkeypatch.setattr(billing_background, "report_billing_recovery_exhausted", report)
    worker = BillingWorker(configuration, factory, sources.require_lbx())
    count = len(transport.requests)
    pending = asyncio.create_task(worker.tick(WorkLane.URGENT))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        claim = job(factory, recovery.RECOVERY, identity)
        if timing != "before_deadline":
            now = window + timedelta(seconds=1)
            assert claim.lease_expires_at > now
        if timing == "deadline_applied":
            for _ in range(5):
                if job(factory, recovery.RECOVERY, identity).work_state == "paused":
                    break
                assert await worker.tick(WorkLane.LOCAL)
        release.set()
        assert await pending
        with factory() as db:
            operation = db.get(ExternalCreateOperation, identity)
            if timing == "before_deadline":
                assert operation.operation_state == "bound"
            else:
                assert operation.operation_state in {"possible_send", "unknown", "manual_review"}
                assert operation.bound_external_object_id is None
                assert job(factory, recovery.RECOVERY, identity).work_state == "paused"
        # The independent deadline lane must notify an unresolved late proof,
        # and must not notify a binding completed within its fixed window.
        now = window + timedelta(seconds=1)
        for _ in range(5):
            if job(factory, recovery.DEADLINE, identity).work_state == "completed":
                break
            assert await worker.tick(WorkLane.LOCAL)
        assert job(factory, recovery.DEADLINE, identity).work_state == "completed"
        assert len(notices) == (0 if timing == "before_deadline" else 1)
        if timing != "before_deadline":
            assert notices[0].operation_id == identity
            # A pause only stops automatic recovery; the original can still be
            # proven explicitly without repeating the uncertain CREATE.
            if purchase is None:
                assert (await bootstrap_account(sources, configuration, factory=factory, token=TOKEN)).credential
            else:
                recovered = await recover_financial(
                    sources,
                    configuration,
                    factory=factory,
                    user_id=purchase.user_id,
                    purchase_id=purchase.id,
                    operation_id=identity,
                )
                assert recovered.held and recovered.accepted == purchase.accepted
        with factory() as db:
            assert db.get(ExternalCreateOperation, identity).operation_state == "bound"
        assert original(factory, identity) == immutable
        assert all(request.method == "GET" for request in transport.requests[count:])
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await worker.aclose()


@pytest.mark.parametrize("pause", [False, True])
async def test_deadline_pause_between_claim_and_subject_is_acknowledged(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    pause: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory, configuration = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    identity = next(op.id for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    window = job(factory, recovery.RECOVERY, identity).active_recovery_deadline_at
    now = window - timedelta(seconds=1)
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: now)
    monkeypatch.setattr(financial, "database_now", lambda db: now)
    monkeypatch.setattr(billing_background, "report_billing_recovery_exhausted", lambda notice: True)
    worker = BillingWorker(configuration, factory, sources.require_lbx())
    entered, release = asyncio.Event(), asyncio.Event()
    delegate = worker.db

    async def held_subject(lane: WorkLane, function: Any, *args: Any, **kwargs: Any) -> Any:
        if function is recovery.subject:
            entered.set()
            await release.wait()
        return await delegate(lane, function, *args, **kwargs)

    monkeypatch.setattr(worker, "db", held_subject)
    count = len(transport.requests)
    pending = asyncio.create_task(worker.tick(WorkLane.URGENT))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        claim = job(factory, recovery.RECOVERY, identity)
        if pause:
            now = window + timedelta(seconds=1)
            assert claim.lease_expires_at > now
            for _ in range(5):
                if job(factory, recovery.RECOVERY, identity).work_state == "paused":
                    break
                assert await worker.tick(WorkLane.LOCAL)
        release.set()
        assert await pending
        with factory() as db:
            assert db.get(ExternalCreateOperation, identity).operation_state == ("manual_review" if pause else "bound")
        if pause:
            assert job(factory, recovery.RECOVERY, identity).work_state == "paused"
            assert len(transport.requests) == count
        assert all(request.method == "GET" for request in transport.requests[count:])
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        await worker.aclose()
