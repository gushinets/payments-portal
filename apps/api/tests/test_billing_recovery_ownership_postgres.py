"""Cancellation retains DB ownership across recovery -> reconciliation races."""

import asyncio
from datetime import UTC, datetime, timedelta
from threading import Event

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition import reconciliation as composition
from app.composition.purchase_observation import prepared_subscription_observation
from app.domains.billing import background_recovery, work
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import financial
from app.infrastructure.preflight import PreflightCleanupPending
from app.integrations.lbx.financial import Subscription
from app.jobs.billing import BillingWorker
from app.models import BillingStateObservation, BillingWorkItem, ExternalSubscription
from apps.api.tests.factories.original_operation import original_proof
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    synthetic_prepare,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("recovery_race", [False, True])
async def test_worker_drains_apply_after_concurrent_first_binding_and_waiter_cancellation(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    recovery_race: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=recovery_race)
    operation = next(op for op in purchase.operations if op.kind == "subscription")
    transport.subscriptions[0].update(
        state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31"
    )
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        kind = background_recovery.RECOVERY if recovery_race else work.RECONCILIATION
        reference = str(operation.id if recovery_race else sub.subscription_id)
        for row in db.scalars(select(BillingWorkItem)):
            target = row.work_kind == kind and row.scope_reference == reference
            row.next_attempt_at = datetime.now(UTC) if target else datetime.now(UTC) + timedelta(days=10)
            row.priority = int(target)
        db.commit()
    worker = BillingWorker(step1_settings(paid_access_clock_skew_seconds=10), factory, sources.require_lbx())
    loop = asyncio.get_running_loop()
    candidate_ready, continue_candidate = asyncio.Event(), asyncio.Event()
    apply_entered, apply_finished = asyncio.Event(), asyncio.Event()
    release_apply = Event()
    original_tariff = worker.client.get_tariff
    paused = False

    async def pause_candidate(**kwargs: object) -> object:
        nonlocal paused
        value = await original_tariff(**kwargs)
        if recovery_race and not paused:
            paused = True
            candidate_ready.set()
            await continue_candidate.wait()
        return value

    monkeypatch.setattr(worker.client, "get_tariff", pause_candidate)
    actual_apply = composition.apply_reconciliation

    def delayed_apply(*args: object, **kwargs: object) -> object:
        loop.call_soon_threadsafe(apply_entered.set)
        try:
            assert release_apply.wait(10)
            return actual_apply(*args, **kwargs)
        finally:
            loop.call_soon_threadsafe(apply_finished.set)

    monkeypatch.setattr(composition, "apply_reconciliation", delayed_apply)
    tick = asyncio.create_task(worker.tick(WorkLane.URGENT))
    try:
        if recovery_race:
            await asyncio.wait_for(candidate_ready.wait(), 5)
            # Foreground binds the same original while the worker's GET is paused.
            assert financial.bind_financial(
                factory,
                purchase,
                operation,
                567,
                proof=original_proof(factory, purchase, operation, transport),
                observation=prepared_subscription_observation(
                    Subscription.model_validate(transport.subscriptions[0]), purchase
                ),
            )
            continue_candidate.set()
        await asyncio.wait_for(apply_entered.wait(), 5)
        tick.cancel()
        with pytest.raises(asyncio.CancelledError):
            await tick
        with pytest.raises(PreflightCleanupPending):
            await worker.aclose()
        assert not apply_finished.is_set()
        release_apply.set()
        await asyncio.wait_for(apply_finished.wait(), 5)
        await worker.aclose()
        with factory() as db:
            sub = db.scalar(select(ExternalSubscription))
            observation = db.get(BillingStateObservation, sub.latest_observation_id)
            assert observation.evidence_schema_version == "subscription-reconciliation:v2"
        assert worker.cleanup_pending == 0
    finally:
        continue_candidate.set()
        release_apply.set()
        if not tick.done():
            tick.cancel()
        await asyncio.gather(tick, return_exceptions=True)
        if apply_entered.is_set():
            await asyncio.wait_for(apply_finished.wait(), 5)
        await worker.aclose()
