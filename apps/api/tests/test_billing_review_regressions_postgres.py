"""ANY-715 review regressions: real PostgreSQL writers, SIMULATED LBX only."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import httpx
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import billing
from app.composition.purchase_observation import prepared_subscription_observation
from app.composition.reconciliation import reconcile_subscription
from app.composition.sources import source_resources
from app.core.errors import AppError
from app.domains.billing import background_recovery as recovery, customers, work
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import financial, service
from app.integrations.lbx.financial import Subscription
from app.jobs.billing import BillingWorker
from app.models import (
    ExternalCreateOperationState as State,
    ExternalCreateOperationKind as Kind,
    ExternalSubscription,
    ManualReviewCase,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN, setup_purchase
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    original,
    synthetic_prepare,
    job,
)
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("completed", [False, True])
async def test_overdue_customer_deadline_records_one_review_without_source_io(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    completed: bool,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    instant = datetime.now(UTC) - timedelta(hours=3)
    monkeypatch.setattr(customers, "utc_now", lambda: instant)
    customer = customers.reserve_customer(factory, config, TOKEN)
    customer = customers.claim_customer_send(factory, config, TOKEN, customer)
    if completed:
        customers.apply_customer_read(factory, customer, provider_id="345", outer_key=customer.outer_key)
    async with source_resources(config, lbx_transport=httpx.MockTransport(transport.respond)) as sources:
        worker = BillingWorker(config, factory, sources.require_lbx())
        try:
            assert await worker.tick(WorkLane.LOCAL)
            assert not await worker.tick(WorkLane.LOCAL)
        finally:
            await worker.aclose()
    current = customers.reserve_customer(factory, config, TOKEN)
    assert current.provider_id == ("345" if completed else None)
    with factory() as db:
        reviews = list(db.scalars(select(ManualReviewCase)))
        assert len(reviews) == (0 if completed else 1)
        if not completed:
            assert reviews[0].reason_code == "external_create_outcome_unknown:customer"
            assert reviews[0].case_state == "open"
    assert not transport.requests


@pytest.mark.parametrize("completion", ["bound", "proven_not_sent"])
@pytest.mark.parametrize("timing", ["before_lookup", "after_lookup"])
async def test_deadline_preserves_completion_committed_before_business_locks(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    completion: str,
    timing: str,
) -> None:
    transport, _, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    monkeypatch.setattr(financial, "utc_now", lambda: datetime.now(UTC) - timedelta(hours=3))
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    immutable = original(factory, operation.id)
    claim = work.claim_work(factory, config, WorkLane.LOCAL)
    if claim.reference != str(operation.id):
        recovery.apply_deadline(factory, claim)
        claim = work.claim_work(factory, config, WorkLane.LOCAL)
    assert claim.reference == str(operation.id)

    def finish() -> None:
        if completion == "bound":
            financial.bind_financial(
                factory,
                purchase,
                operation,
                567,
                observation=prepared_subscription_observation(
                    Subscription.model_validate(transport.subscriptions[0]), purchase
                ),
            )
        else:
            financial.proven_not_sent(factory, purchase, replace(operation, may_send=True))

    lookup = recovery.queries.operation_subject

    def concurrent_lookup(db: Session, identity: UUID) -> Any:
        found = lookup(db, identity)
        finish()  # A separate real transaction commits after this Session cached the row.
        return found

    if timing == "before_lookup":
        finish()
    else:
        monkeypatch.setattr(recovery.queries, "operation_subject", concurrent_lookup)
    recovery.apply_deadline(factory, claim)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    expected = State.BOUND if completion == "bound" else State.PROVEN_NOT_SENT
    assert next(op for op in saved.operations if op.id == operation.id).state == expected
    assert saved.state != "manual_review" and saved.held
    assert original(factory, operation.id) == immutable
    with factory() as db:
        assert not list(db.scalars(select(ManualReviewCase)))


@pytest.mark.parametrize("incomplete", [False, True])
async def test_inventory_preserves_proven_conflict_when_next_product_is_incomplete(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    incomplete: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    historical_link(factory, first, transport, "brief_decoder", 1)
    _, purchases = recovery.customer_snapshot(factory, config, first.customer_id)
    for purchase in purchases:
        with factory() as db:
            identity = db.scalar(
                select(ExternalSubscription.subscription_id).where(
                    ExternalSubscription.purchase_intent_id == purchase.id
                )
            )
        await reconcile_subscription(
            sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=identity
        )
    first_op = next(op for op in purchases[0].operations if op.kind == Kind.SUBSCRIPTION)
    point = next(row for row in transport.subscriptions if str(row["subscription_id"]) == first_op.bound_id)
    competitor = deepcopy(point)
    competitor["subscription_id"] = 999
    transport.subscriptions.append(competitor)
    if incomplete:
        point["total_price"] = None
    recovery.repair_batch(factory, config)
    worker = BillingWorker(config, factory, sources.require_lbx())
    before = len(transport.requests)
    try:
        assert await worker.tick(WorkLane.NORMAL)
    finally:
        await worker.aclose()
    assert job(factory, recovery.INVENTORY, first.customer_id).last_error_classification == "inventory_conflict"
    for index, purchase in enumerate(purchases):
        current = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert current.state == ("linked" if incomplete and index == 1 else "manual_review")
        assert current.held
        assert tuple((op.id, op.key, op.bound_id) for op in current.operations) == tuple(
            (op.id, op.key, op.bound_id) for op in purchase.operations
        )
    with factory() as db:
        first_sub = db.scalar(
            select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchases[0].id)
        )
        assert first_sub.commercial_access_status == "ineligible"
    assert all(request.method == "GET" for request in transport.requests[before:])


@pytest.mark.parametrize("change", ["healthy_read", "customer_conflict", "commercial_conflict", "diagnostic_only"])
async def test_payment_widget_last_admission_checks_customer_and_purchase_together(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    with factory() as db:
        identity = db.scalar(select(ExternalSubscription.subscription_id))
    delegate = billing.run_in_threadpool
    injected = False

    async def interleaved(function: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal injected
        if function.__name__ == "recheck_payment_purchase":
            injected = True
            if change == "customer_conflict":
                transport.customer["outer_id"] = "another-original-customer-key"
            elif change == "commercial_conflict":
                transport.subscriptions[0]["services"][0]["price"] = 15
            if change == "diagnostic_only":
                financial.financial_pending(
                    factory,
                    purchase,
                    next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION),
                    failure_facts={"code": "lbx_unavailable", "reason": "transport"},
                )
            else:
                await reconcile_subscription(
                    sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=identity
                )
        return await delegate(function, *args, **kwargs)

    monkeypatch.setattr(billing, "run_in_threadpool", interleaved)
    if change in {"customer_conflict", "commercial_conflict"}:
        with pytest.raises(AppError):
            await billing.bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    else:
        result = await billing.bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.purchase_id == purchase.id
    assert injected
