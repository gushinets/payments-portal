"""Inventory refusal fences pre-claim source proof; real writers, simulated LBX."""

import asyncio
from dataclasses import replace
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import advance_purchase
from app.composition.sources import source_resources
from app.domains.billing import background_recovery as recovery
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseRefused
from app.infrastructure.preflight import PreflightBudget
from app.jobs.billing import BillingWorker
from app.models import (
    BillingStateObservation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ManualReviewCase,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN, accept, setup_purchase
from apps.api.tests.test_any709_subscription_inventory_postgres import add_external_subscription
from apps.api.tests.test_billing_background_recovery_postgres import anyio_backend as anyio_backend, original

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("stage", [Kind.AGREEMENT, Kind.SUBSCRIPTION])
@pytest.mark.parametrize("resume", [False, True], ids=["pending", "proven-not-sent"])
@pytest.mark.parametrize("competition", [False, True], ids=["clean-control", "known-competition"])
async def test_inventory_refusal_fences_inflight_admission_and_allows_fresh_continuation(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    stage: Kind,
    resume: bool,
    competition: bool,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    transport = setup_purchase(factory)
    endpoint = f"/{stage.value}s"
    reject_create = resume

    def respond(request: httpx.Request) -> httpx.Response:
        if reject_create and request.method == "POST" and request.url.path.endswith(endpoint):
            raise httpx.ConnectError("synthetic no-send", request=request)
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        if resume:
            paused = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
            assert next(op for op in paused.operations if op.kind == stage).state == State.PROVEN_NOT_SENT
            reject_create = False
        entered, release = asyncio.Event(), asyncio.Event()
        prepare = sources.require_lbx().prepare_customer_create

        async def pause_before_claim(*, budget: PreflightBudget) -> None:
            await prepare(budget=budget)
            current = service.read_purchase(factory, purchase.user_id, purchase.id)
            agreement = next(op for op in current.operations if op.kind == Kind.AGREEMENT)
            if (
                transport.customer is not None
                and not entered.is_set()
                and (stage == Kind.AGREEMENT or agreement.state == State.BOUND)
            ):
                entered.set()
                await release.wait()

        monkeypatch.setattr(sources.require_lbx(), "prepare_customer_create", pause_before_claim)
        task = asyncio.create_task(
            advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        )
        worker = BillingWorker(config, factory, sources.require_lbx())
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            before = service.read_purchase(factory, purchase.user_id, purchase.id)
            history = {op.id: original(factory, op.id) for op in before.operations}
            counts = transport.creates("/agreements"), transport.creates("/subscriptions")
            assert transport.creates(endpoint) == 0
            if competition:
                add_external_subscription(transport, -2)
            recovery.repair_batch(factory, config)
            assert await worker.tick(WorkLane.NORMAL)
            fenced = service.read_purchase(factory, purchase.user_id, purchase.id)
            assert fenced.state == before.state and fenced.held and fenced.accepted == before.accepted
            assert tuple(replace(op, fence=old.fence) for old, op in zip(before.operations, fenced.operations)) == (
                before.operations
            )
            assert {op.id: original(factory, op.id) for op in fenced.operations} == history
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
                if competition:
                    observation = db.scalars(
                        select(BillingStateObservation).where(
                            BillingStateObservation.evidence_schema_version == "customer-inventory:v1"
                        )
                    ).one()
                    assert observation.result_classification == "admission_blocked"
            release.set()
            current = await task
            if competition:
                assert current == fenced
                assert (transport.creates("/agreements"), transport.creates("/subscriptions")) == counts
                # The stale request stays refused even though its original source reads passed.
                with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
                    await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
                assert service.read_purchase(factory, purchase.user_id, purchase.id) == fenced
                next(row for row in transport.subscriptions if row["subscription_id"] == 9999)["state"] = 3
                current = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
            else:
                assert fenced == before
            assert current.state == "linked" and current.held and current.accepted == purchase.accepted
            assert [(op.id, op.key) for op in current.operations] == [(op.id, op.key) for op in purchase.operations]
            # Completed no-send keeps its original command/date/deadline across fencing and resume.
            for operation_id, saved in history.items():
                if saved[2] is not None:
                    assert original(factory, operation_id) == saved
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await worker.aclose()
