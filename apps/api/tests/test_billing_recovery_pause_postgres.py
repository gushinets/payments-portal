"""Durable two-hour pause/notification and explicit recovery; SIMULATED LBX."""

import asyncio
from dataclasses import asdict
from datetime import UTC, datetime, timedelta, date
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import billing_background
from app.composition.billing import bootstrap_account
from app.composition.purchases import recover_financial, advance_purchase
from app.composition.sources import source_resources
from app.domains.billing import background_recovery as recovery, customers
from app.domains.billing.operator_diagnostics import inspect_operation
from app.core.errors import AppError
from app.domains.catalog.commercial_offer import canonical_document, commercial_digest
from app.domains.billing.work_contracts import WorkLane, RecoveryEscalation
from app.domains.purchases import financial, service
from app.integrations.lbx.financial import NewAgreement
from app.jobs.billing import BillingWorker
from app.infrastructure.queries import billing_reconciliation
from app.models import ExternalCreateOperation, ExternalCreateOperationKind as Kind, ManualReviewCase, BillingWorkItem
from apps.api.tests.factories.original_operation import financial_claim_clock
from apps.api.tests.factories.reconciliation import agreement_factory
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN, setup_purchase
from apps.api.tests.test_any709_step3_postgres import accept
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    synthetic_prepare,
    job,
    original,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("kind", [Kind.AGREEMENT, Kind.SUBSCRIPTION])
@pytest.mark.parametrize("recovery_first", [False, True])
async def test_overdue_financial_pauses_across_restart_but_explicit_get_recovers(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    kind: Kind,
    recovery_first: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    financial_claim_clock(monkeypatch, lambda: financial.utc_now())
    monkeypatch.setattr(financial, "utc_now", lambda: datetime.now(UTC) - timedelta(hours=3))
    if kind == Kind.SUBSCRIPTION:
        purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    else:
        operation = next(op for op in purchase.operations if op.kind == kind)
        command = NewAgreement(
            user_id=345, organization_id=21, agreement_number=operation.key, create_date=date(2026, 10, 27)
        )
        financial.claim_financial(
            factory, purchase, operation, command.request_document(), configuration=config, token=TOKEN
        )
        transport.agreements.append({**agreement_factory().model_dump(), **command.request_document()})
        purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    operation = next(op for op in purchase.operations if op.kind == kind)
    immutable = original(factory, operation.id)
    notices: list[RecoveryEscalation] = []

    def report(notice: RecoveryEscalation) -> bool:
        assert factory.kw["bind"].pool.checkedout() == 0
        notices.append(notice)
        return True

    monkeypatch.setattr(billing_background, "report_billing_recovery_exhausted", report)
    count = len(transport.requests)
    worker = BillingWorker(config, factory, sources.require_lbx())
    try:
        if recovery_first:
            assert await worker.tick(WorkLane.URGENT)
            assert len(transport.requests) == count
        for _ in range(3):
            if job(factory, recovery.DEADLINE, operation.id).work_state == "completed":
                break
            assert await worker.tick(WorkLane.LOCAL)
        assert job(factory, recovery.RECOVERY, operation.id).work_state == "paused"
        assert job(factory, recovery.DEADLINE, operation.id).work_state == "completed"
        assert len(notices) == 1 and notices[0].operation_id == operation.id
        lookup = inspect_operation(factory, config, notices[0].operation_id)
        assert lookup["user_id"] == str(purchase.user_id)
        assert lookup["purchase_intent_id"] == str(purchase.id)
        assert " recover " in lookup["recover_command"]
        assert len(transport.requests) == count
        recovery.repair_batch(factory, config)
        assert job(factory, recovery.RECOVERY, operation.id).work_state == "paused"
        assert not await worker.tick(WorkLane.URGENT)
    finally:
        await worker.aclose()
    restarted = BillingWorker(config, factory, sources.require_lbx())
    try:
        assert not await restarted.tick(WorkLane.URGENT)
        assert len(transport.requests) == count
    finally:
        await restarted.aclose()
    recovered = await recover_financial(
        sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id, operation_id=operation.id
    )
    assert next(op for op in recovered.operations if op.id == operation.id).state == "bound"
    assert recovered.held and original(factory, operation.id) == immutable
    assert all(request.method == "GET" for request in transport.requests[count:])


async def test_deadline_notification_retries_without_restarting_discovery(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    financial_claim_clock(monkeypatch, lambda: financial.utc_now())
    monkeypatch.setattr(financial, "utc_now", lambda: datetime.now(UTC) - timedelta(hours=3))
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    notices: list[RecoveryEscalation] = []

    def report(notice: RecoveryEscalation) -> bool:
        notices.append(notice)
        return len(notices) > 1

    monkeypatch.setattr(billing_background, "report_billing_recovery_exhausted", report)
    worker = BillingWorker(config, factory, sources.require_lbx())
    before = len(transport.requests)
    try:
        while not notices:
            assert await worker.tick(WorkLane.LOCAL)
        deadline = job(factory, recovery.DEADLINE, operation.id)
        assert (
            deadline.work_state == "pending" and deadline.last_error_classification == "recovery_notification_pending"
        )
        assert job(factory, recovery.RECOVERY, operation.id).work_state == "paused"
        with factory() as db:
            db.get(BillingWorkItem, deadline.work_item_id).next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        assert await worker.tick(WorkLane.LOCAL)
        assert notices[0] == notices[1]
        assert job(factory, recovery.DEADLINE, operation.id).work_state == "completed"
        assert not await worker.tick(WorkLane.URGENT)
        assert len(transport.requests) == before
    finally:
        await worker.aclose()


@pytest.mark.parametrize("visible", [False, True])
async def test_overdue_customer_pauses_and_explicit_account_open_recovers(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    visible: bool,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    with factory() as db:
        past = billing_reconciliation.database_now(db) - timedelta(hours=4)
    customer = customers.reserve_customer(factory, config, TOKEN)
    with monkeypatch.context() as clock:
        clock.setattr(billing_reconciliation, "database_now", lambda db: past)
        customer = customers.claim_customer_send(factory, config, TOKEN, customer)
    transport.customer = {"user_id": 345, "outer_id": customer.outer_key} if visible else None
    monkeypatch.setattr(billing_background, "report_billing_recovery_exhausted", lambda notice: True)
    async with source_resources(config, lbx_transport=httpx.MockTransport(transport.respond)) as sources:
        worker = BillingWorker(config, factory, sources.require_lbx())
        try:
            assert await worker.tick(WorkLane.LOCAL)
            assert job(factory, recovery.RECOVERY, customer.operation_id).work_state == "paused"
            lookup = inspect_operation(factory, config, customer.operation_id)
            assert lookup["create_operation_id"] == str(customer.operation_id)
            assert lookup["kind"] == "customer" and lookup["purchase_intent_id"] is None
            assert "billing-customer diagnose" in lookup["inspect_command"]
            recovery.repair_batch(factory, config)
            assert not await worker.tick(WorkLane.URGENT)
            assert not transport.requests
        finally:
            await worker.aclose()
        if visible:
            result = await bootstrap_account(sources, config, factory=factory, token=TOKEN)
            assert result.credential
        else:
            with pytest.raises(AppError, match="billing_customer_review"):
                await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        assert all(request.method == "GET" for request in transport.requests)
    with factory() as db:
        assert db.get(ExternalCreateOperation, customer.operation_id).operation_state == (
            "bound" if visible else "manual_review"
        )
        assert db.scalar(select(ManualReviewCase)).case_state == ("resolved" if visible else "open")


@pytest.mark.parametrize("days", [20, None])
async def test_accepted_purchase_continues_after_only_block_to_close_changes(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    days: int | None,
) -> None:
    from app.integrations.lbx import current_offer
    from app.domains.catalog.product_link import CurrentOffer, ProductLinkRequest

    config = step1_settings()
    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    transport = setup_purchase(postgres_session_factory)

    def legacy_v2(account: str, selection: ProductLinkRequest, offer: CurrentOffer) -> str:
        period = asdict(offer.period)
        del period["price_effective_until"]
        return commercial_digest(
            canonical_document(
                {
                    "schema": "current-terms:v2",
                    "scope": account,
                    "selection": selection.model_dump(),
                    "money": asdict(offer.money),
                    "period": period,
                    "quantity": asdict(offer.quantity),
                    "price_id": offer.price_id,
                    "period_membership_id": offer.period_membership_id,
                    "defaults": [offer.tariff_service_id],
                    "prepaid": offer.prepaid,
                    "full_funding_required": offer.full_funding_required,
                    "block_to_close_days": offer.block_to_close_days,
                }
            )
        )

    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        with monkeypatch.context() as historical:
            historical.setattr(current_offer, "current_offer_fingerprint", legacy_v2)
            purchase = await accept(sources, postgres_session_factory)
        await _continue_historical_purchase(transport, sources, purchase, postgres_session_factory, days)


async def _continue_historical_purchase(
    transport: Any,
    sources: Any,
    purchase: Any,
    postgres_session_factory: sessionmaker[Session],
    days: int | None,
) -> None:
    before = purchase.accepted
    old_snapshot: dict[str, Any]
    from app.models import PurchaseIntent

    with postgres_session_factory() as db:
        old_snapshot = db.get(PurchaseIntent, purchase.id).accepted_snapshot
    if days is None:
        transport.offer.replace("tariff", '"block_to_close_days":30,', "")
    else:
        transport.offer.replace("tariff", '"block_to_close_days":30', f'"block_to_close_days":{days}')
    result = await advance_purchase(
        sources, step1_settings(), factory=postgres_session_factory, token=TOKEN, purchase_id=purchase.id
    )
    assert result.state == "linked" and result.accepted == before
    with postgres_session_factory() as db:
        assert db.get(PurchaseIntent, purchase.id).accepted_snapshot == old_snapshot


async def test_deadline_revokes_inflight_automatic_binding(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    deadline = job(factory, recovery.RECOVERY, operation.id).active_recovery_deadline_at
    entered, release = asyncio.Event(), asyncio.Event()
    get_subscription = sources.require_lbx().get_subscription

    async def held(**kwargs: Any) -> Any:
        point = await get_subscription(**kwargs)
        entered.set()
        await release.wait()
        return point

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", held)
    monkeypatch.setattr(billing_background, "report_billing_recovery_exhausted", lambda notice: True)
    worker = BillingWorker(config, factory, sources.require_lbx())
    pending = asyncio.create_task(worker.tick(WorkLane.URGENT))
    try:
        await asyncio.wait_for(entered.wait(), timeout=5)
        monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: deadline + timedelta(seconds=1))
        for _ in range(3):
            if job(factory, recovery.RECOVERY, operation.id).work_state == "paused":
                break
            assert await worker.tick(WorkLane.LOCAL)
        release.set()
        assert await pending  # Intentional pause is acknowledged without an extra worker error.
        current = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert next(op for op in current.operations if op.id == operation.id).state == "manual_review"
        assert job(factory, recovery.RECOVERY, operation.id).work_state == "paused"
    finally:
        release.set()
        if not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        await worker.aclose()
