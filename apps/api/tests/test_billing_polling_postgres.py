"""Polling converges without ingress; retained inbox history never becomes work."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import reconcile_purchase
from app.composition.purchases import advance_purchase
from app.composition.reconciliation import reconcile_subscription
from app.domains.billing import reconciliation, work
from app.domains.billing.work_contracts import WorkLane
from app.http.dependencies import get_session_factory
from app.jobs.billing import BillingWorker
from app.main import create_app
from app.models import (
    BillingWorkItem,
    ExternalBillingWebhookDelivery,
    ExternalSubscription,
    WebhookDeliveryState,
    BillingStateObservation,
    BillingPurchaseScopeHold,
    ExternalCreateOperation,
    PurchaseIntent,
    BillingProductAccessScope,
    ManualReviewCase,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
)
from apps.api.tests.test_billing_qa_isolation_postgres import product_snapshot, assert_no_access_writes
from apps.api.tests.test_billing_subscription_reconciliation_postgres import (
    scenario as scenario,
    activate,
)
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


def subscription(factory: sessionmaker[Session]) -> ExternalSubscription:
    with factory() as db:
        return db.scalar(select(ExternalSubscription).where(ExternalSubscription.product_id == "proposal_ai"))


def queue(factory: sessionmaker[Session], identity: UUID) -> BillingWorkItem:
    with factory() as db:
        return db.scalar(
            select(BillingWorkItem).where(
                BillingWorkItem.work_kind == work.RECONCILIATION,
                BillingWorkItem.scope_reference == str(identity),
            )
        )


async def test_ordinary_purchase_and_worker_need_no_callback_and_404_changes_nothing(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert purchase.state == "linked" and purchase.held
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
    # Preserve a receipt from an older build without treating it as an active inbox.
    with factory() as db:
        history = ExternalBillingWebhookDelivery(
            external_billing_account_id=purchase.account_id,
            payload_hash="retained-diagnostic-hash",
            correlation_schema_version="billing-webhook-work:v1",
            correlation_document={"retained": True},
            evidence_schema_version="billing-webhook-receipt:v1",
            evidence_document={"event": "change_subscription"},
            processing_state=WebhookDeliveryState.PENDING,
            received_at=datetime.now(UTC),
        )
        db.add(history)
        db.commit()
        history_id = history.delivery_id

    def billing_snapshot() -> dict:
        with factory() as db:
            return {
                model.__tablename__: list(
                    db.execute(select(model.__table__).order_by(*model.__table__.primary_key.columns)).mappings()
                )
                for model in (
                    ExternalSubscription,
                    ExternalCreateOperation,
                    PurchaseIntent,
                    BillingPurchaseScopeHold,
                    BillingStateObservation,
                    BillingProductAccessScope,
                    BillingWorkItem,
                    ExternalBillingWebhookDelivery,
                    ManualReviewCase,
                )
            }

    before = billing_snapshot()
    count = len(transport.requests)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: factory
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client:
        for payload in (
            {"event": "block_subscription", "parameters": {"subscription_id": 567, "agreement_id": 456}},
            {},
        ):
            assert (await client.post("/api/billing/lbx/webhook", json=payload)).status_code == 404
    assert len(transport.requests) == count
    assert billing_snapshot() == before
    activate(transport)
    worker = BillingWorker(config, factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.URGENT)
        assert subscription(factory).financial_access_status == "allowed"
        assert all(request.method == "GET" for request in transport.requests[count:])
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
        with factory() as db:
            retained = db.get(ExternalBillingWebhookDelivery, history_id)
            assert retained.processing_state == WebhookDeliveryState.PENDING
            assert retained.processed_at is None and retained.processing_started_at is None
            assert retained.evidence_document == {"event": "change_subscription"}
            assert retained.correlation_document == {"retained": True}
        assert_no_access_writes(factory)
    finally:
        await worker.aclose()


async def test_nonclaim_read_hints_coalesce_survive_old_generation_and_stay_product_scoped(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory, config = postgres_session_factory, step1_settings()
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    await reconcile_purchase(sources, config, factory=factory, user_id=sibling.user_id, purchase_id=sibling.id)
    untouched = product_snapshot(factory, "brief_decoder")
    claim = work.claim_work(factory, config, WorkLane.URGENT)
    assert claim and claim.reference == str(subscription(factory).subscription_id)
    transport.subscriptions[0]["total_price"] = None
    for _ in range(2):
        # Actual operator/nonclaim observation path: incomplete proof requests
        # follow-up without taking another worker's queue ownership.
        await reconcile_purchase(sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id)
    row = queue(factory, UUID(claim.reference))
    assert row.enqueue_generation == claim.generation + 2
    assert row.work_state == "running" and row.lease_owner == claim.owner
    activate(transport)
    transport.subscriptions[0]["total_price"] = 100
    await reconcile_subscription(
        sources.require_lbx(),
        sources.billing,
        config,
        factory=factory,
        subscription_id=UUID(claim.reference),
        work_claim=claim,
    )
    row = queue(factory, UUID(claim.reference))
    assert row.work_state == "pending" and row.priority == 1 and row.lease_owner is None
    assert row.next_attempt_at <= datetime.now(UTC)
    assert product_snapshot(factory, "brief_decoder") == untouched
    worker = BillingWorker(config, factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.URGENT)
        assert queue(factory, UUID(claim.reference)).priority == 0
        assert product_snapshot(factory, "brief_decoder") == untouched
    finally:
        await worker.aclose()


async def test_polling_apply_failure_rolls_back_facts_and_queue_without_receipt_hook(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    original = subscription(factory)
    activate(transport)
    schedule = reconciliation.schedule_reconciliation

    def fail_after_schedule(*args: Any, **kwargs: Any) -> None:
        schedule(*args, **kwargs)
        raise RuntimeError("synthetic apply rollback")

    monkeypatch.setattr(reconciliation, "schedule_reconciliation", fail_after_schedule)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    try:
        with pytest.raises(RuntimeError, match="synthetic apply rollback"):
            await worker.tick(WorkLane.URGENT)
        assert subscription(factory).latest_observation_id == original.latest_observation_id
        assert subscription(factory).projection_valid_until == original.projection_valid_until
        assert queue(factory, original.subscription_id).work_state == "running"
    finally:
        await worker.aclose()


async def test_concurrent_real_sweep_enqueues_keep_one_job_and_one_owner(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: work.ensure_sweep(factory, config), range(2)))
        claims = list(pool.map(lambda _: work.claim_work(factory, config, WorkLane.LOCAL), range(2)))
    assert sum(claim is not None for claim in claims) == 1
    with factory() as db:
        rows = list(db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.SWEEP)))
        assert len(rows) == 1 and rows[0].enqueue_generation == 1
