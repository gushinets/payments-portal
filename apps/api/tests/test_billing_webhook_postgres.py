"""Durable receipt/worker safety against disposable PostgreSQL and synthetic LBX."""

from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
import json
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.reconciliation import reconcile_subscription
from app.domains.billing import work, webhooks, reconciliation
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.work_contracts import WorkLane
from app.http import billing_webhook as entrypoint
from app.http.dependencies import get_session_factory
from app.integrations.lbx.webhook import decode_hint
from app.jobs.billing import BillingWorker
from app.main import create_app
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    BillingWorkItem,
    ExternalBillingWebhookDelivery as Delivery,
    ExternalSubscription,
    PaidAccessState,
    PurchasedAllowance,
    WebhookDeliveryState as State,
)
from apps.api.tests.factories.billing_webhook import AUTH_HEADER, AUTH_VALUE, PATH, hint_payload, webhook_settings
from apps.api.tests.test_billing_subscription_reconciliation_postgres import scenario as scenario, activate
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[httpx.AsyncClient]:
    monkeypatch.setattr(entrypoint, "settings", webhook_settings())
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: postgres_session_factory
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False), base_url="http://portal.test"
    ) as connection:
        yield connection


def receipts(factory: sessionmaker[Session]) -> list[Delivery]:
    with factory() as db:
        return list(db.scalars(select(Delivery).order_by(Delivery.received_at, Delivery.delivery_id)))


def subscription(factory: sessionmaker[Session]) -> ExternalSubscription:
    with factory() as db:
        return db.scalar(select(ExternalSubscription).where(ExternalSubscription.external_subscription_id == "567"))


def queue(factory: sessionmaker[Session], sub: ExternalSubscription) -> BillingWorkItem:
    with factory() as db:
        return db.scalar(
            select(BillingWorkItem).where(
                BillingWorkItem.work_kind == work.RECONCILIATION,
                BillingWorkItem.scope_reference == str(sub.subscription_id),
            )
        )


async def deliver(client: httpx.AsyncClient, **overrides: object) -> httpx.Response:
    return await client.post(PATH, json=hint_payload(**overrides), headers={AUTH_HEADER: AUTH_VALUE})


async def test_billing_webhook_commits_redacted_receipt_and_work_before_ack_and_only_worker_updates_facts(
    client: httpx.AsyncClient,
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    original = subscription(factory)
    with factory() as db:
        row = db.get(BillingWorkItem, queue(factory, original).work_item_id)
        row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=10)
        db.commit()
    before = len(transport.requests)
    response = await deliver(
        client,
        event="block_subscription",
        state=3,
        email="pii-canary@test.invalid",
        token=AUTH_VALUE,
        card="card-canary",
    )
    assert response.status_code == 200 and response.json()["outcome"] == "queued"
    saved = receipts(factory)
    assert len(saved) == 1 and saved[0].delivery_id == UUID(response.json()["delivery_id"])
    assert saved[0].processing_state == State.PENDING and saved[0].provider_event_id is None
    assert saved[0].evidence_document == {"event": "block_subscription"}
    assert saved[0].correlation_document["enqueue_generation"] == queue(factory, original).enqueue_generation == 1
    assert saved[0].correlation_document["subscription_id"] == str(original.subscription_id)
    assert queue(factory, original).next_attempt_at <= datetime.now(UTC)
    assert len(transport.requests) == before
    unchanged = subscription(factory)
    assert (unchanged.latest_observation_id, unchanged.projection_valid_until, unchanged.lifecycle_status) == (
        original.latest_observation_id,
        original.projection_valid_until,
        original.lifecycle_status,
    )
    output = json.dumps([saved[0].correlation_document, saved[0].evidence_document]) + caplog.text
    for canary in (AUTH_VALUE, "pii-canary", "card-canary"):
        assert canary not in output
    activate(transport)
    worker = BillingWorker(webhook_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    assert receipts(factory)[0].processing_state == State.PROCESSED
    assert receipts(factory)[0].processing_started_at is not None and receipts(factory)[0].processed_at is not None
    assert subscription(factory).financial_access_status.value == "allowed"
    assert [request.method for request in transport.requests[before:]] == ["GET"] * 4
    with factory() as db:
        assert db.scalar(select(BillingProductAccessScope)).primary_subscription_id is None
        assert all(row.resulting_access_revision is None for row in db.scalars(select(BillingStateObservation)))
        for model in (PaidAccessState, PurchasedAllowance, AccessInvalidationOutbox):
            assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("failure", ["enqueue", "commit"])
async def test_billing_webhook_failure_before_commit_acknowledges_nothing_and_rolls_back_both(
    client: httpx.AsyncClient,
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    transport, _, _ = scenario
    factory = postgres_session_factory
    original = queue(factory, subscription(factory))
    before = len(transport.requests)

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic failure")

    if failure == "enqueue":
        original_enqueue = work.enroll_subscription

        def fail_after_enqueue(*args: object, **kwargs: object) -> None:
            original_enqueue(*args, **kwargs)
            fail()

        monkeypatch.setattr(work, "enroll_subscription", fail_after_enqueue)
    else:
        original_commit = Session.commit

        def fail_before_commit(db: Session) -> None:
            db.flush()  # Both writes reached PostgreSQL but neither may escape rollback.
            fail()

        monkeypatch.setattr(Session, "commit", fail_before_commit)
    response = await deliver(client)
    assert response.status_code == 500
    assert receipts(factory) == []
    saved = queue(factory, subscription(factory))
    assert (saved.enqueue_generation, saved.next_attempt_at) == (original.enqueue_generation, original.next_attempt_at)
    assert len(transport.requests) == before
    if failure == "commit":
        monkeypatch.setattr(Session, "commit", original_commit)


async def test_billing_webhook_response_loss_duplicates_reordering_and_later_generation_survive_claim(
    client: httpx.AsyncClient,
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    original_receive = entrypoint.receive_hint

    def lose_after_commit(*args: object, **kwargs: object) -> None:
        original_receive(*args, **kwargs)
        raise RuntimeError("synthetic response loss after commit")

    monkeypatch.setattr(entrypoint, "receive_hint", lose_after_commit)
    assert (await deliver(client)).status_code == 500
    first = receipts(factory)[0]
    monkeypatch.setattr(entrypoint, "receive_hint", original_receive)
    config = webhook_settings()
    claim = work.claim_work(factory, config, WorkLane.URGENT)
    assert claim is not None
    response = await deliver(client)
    assert response.status_code == 200
    await deliver(client, event="close_subscription", state=3)  # Stale body does not override current REST.
    activate(transport)
    await reconcile_subscription(
        sources.require_lbx(),
        sources.billing,
        config,
        factory=factory,
        subscription_id=UUID(claim.reference),
        work_claim=claim,
    )
    saved = receipts(factory)
    assert [row.processing_state for row in saved] == [State.PROCESSED, State.PENDING, State.PENDING]
    assert saved[0].payload_hash == saved[1].payload_hash and saved[0].delivery_id != saved[1].delivery_id
    assert queue(factory, subscription(factory)).next_attempt_at <= datetime.now(UTC)
    assert subscription(factory).lifecycle_status.value == "active"
    assert await BillingWorker(config, factory, sources.require_lbx()).tick(WorkLane.URGENT)
    assert all(row.processing_state == State.PROCESSED for row in receipts(factory))
    # An identical future event is never permanently suppressed by payload hash.
    await deliver(client)
    assert receipts(factory)[-1].payload_hash == first.payload_hash
    assert receipts(factory)[-1].processing_state == State.PENDING


async def test_billing_webhook_crash_reclaim_rejects_stale_owner_and_processes_covered_receipts(
    client: httpx.AsyncClient, scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    _, sources, _ = scenario
    factory = postgres_session_factory
    config = webhook_settings()
    await deliver(client)
    abandoned = work.claim_work(factory, config, WorkLane.URGENT)
    assert abandoned is not None
    with factory() as db:
        db.get(BillingWorkItem, abandoned.id).lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    successor = work.claim_work(factory, config, WorkLane.URGENT)
    assert successor is not None and successor.owner != abandoned.owner
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        await reconcile_subscription(
            sources.require_lbx(),
            sources.billing,
            config,
            factory=factory,
            subscription_id=UUID(abandoned.reference),
            work_claim=abandoned,
        )
    assert receipts(factory)[0].processing_state == State.PENDING
    # The rejected stale attempt still owns its finite subscription read lease;
    # simulate its expiry before a new handler can safely claim that subject.
    with factory() as db:
        db.get(ExternalSubscription, UUID(successor.reference)).reconciliation_lease_expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
        db.commit()
    await reconcile_subscription(
        sources.require_lbx(),
        sources.billing,
        config,
        factory=factory,
        subscription_id=UUID(successor.reference),
        work_claim=successor,
    )
    assert receipts(factory)[0].processing_state == State.PROCESSED


async def test_billing_webhook_delayed_rest_incomplete_read_keeps_receipt_pending_and_polling_converges(
    client: httpx.AsyncClient,
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.lbx.errors import LbxUnavailable

    transport, sources, _ = scenario
    factory = postgres_session_factory
    original = subscription(factory)
    get_subscription = sources.require_lbx().get_subscription

    async def unavailable(**kwargs: object) -> None:
        raise LbxUnavailable()

    await deliver(client)
    monkeypatch.setattr(sources.require_lbx(), "get_subscription", unavailable)
    worker = BillingWorker(webhook_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    assert receipts(factory)[0].processing_state == State.PENDING
    assert subscription(factory).projection_valid_until == original.projection_valid_until
    assert queue(factory, original).last_error_classification == "source_incomplete"
    # No second notification. Existing retry alone observes delayed REST visibility.
    monkeypatch.setattr(sources.require_lbx(), "get_subscription", get_subscription)
    activate(transport)
    with factory() as db:
        db.get(BillingWorkItem, queue(factory, original).work_item_id).next_attempt_at = datetime.now(UTC)
        db.commit()
    assert await BillingWorker(webhook_settings(lbx_webhook_enabled=False), factory, sources.require_lbx()).tick(
        WorkLane.URGENT
    )
    assert subscription(factory).financial_access_status.value == "allowed"
    assert receipts(factory)[0].processing_state == State.PROCESSED


async def test_billing_webhook_unknown_conflicting_and_cross_product_hints_are_isolated(
    client: httpx.AsyncClient, scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, _, purchase = scenario
    factory = postgres_session_factory
    historical_link(factory, purchase, transport, "brief_decoder", 1)
    original = queue(factory, subscription(factory))
    for overrides in (
        {"subscription_id": 999999},
        {"agreement_id": 457},
        {"user_id": 999999},
        {"subscription_id": 568, "agreement_id": 456},
    ):
        response = await deliver(client, **overrides)
        assert response.status_code == 200 and response.json()["outcome"] == "ignored"
    assert all(row.processing_state == State.IGNORED for row in receipts(factory))
    assert all(set(row.correlation_document) == {"subject_hash"} for row in receipts(factory))
    assert queue(factory, subscription(factory)).enqueue_generation == original.enqueue_generation
    # Deployment account/scope cannot be selected by caller fields.
    webhooks.receive_hint(
        factory,
        webhook_settings(lbx_base_url="https://other-lbx.test"),
        decode_hint(json.dumps(hint_payload()).encode()),
    )
    assert receipts(factory)[-1].processing_state == State.IGNORED
    response = await deliver(
        client, subscription_id=568, agreement_id=457, product_id="proposal_ai", tenant_id="foreign"
    )
    assert response.json()["outcome"] == "queued"
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.external_subscription_id == "568"))
    assert receipts(factory)[-1].correlation_document["subscription_id"] == str(sub.subscription_id)
    assert queue(factory, subscription(factory)).enqueue_generation == original.enqueue_generation


async def test_billing_webhook_concurrent_receipts_coalesce_one_job_and_keep_each_generation(
    scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    hint = decode_hint(json.dumps(hint_payload()).encode())
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: webhooks.receive_hint(factory, webhook_settings(), hint), range(2)))
    saved = receipts(factory)
    assert len(saved) == 2 and {row.correlation_document["enqueue_generation"] for row in saved} == {1, 2}
    assert len({row.correlation_document["work_item_id"] for row in saved}) == 1
    assert queue(factory, subscription(factory)).enqueue_generation == 2


async def test_billing_webhook_apply_failure_rolls_back_receipts_facts_and_queue_together(
    client: httpx.AsyncClient,
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    await deliver(client)
    before = subscription(factory)
    activate(transport)
    original_mark = reconciliation.mark_processed

    def fail_after_mark(*args: object, **kwargs: object) -> None:
        original_mark(*args, **kwargs)
        raise RuntimeError("synthetic apply crash")

    monkeypatch.setattr(reconciliation, "mark_processed", fail_after_mark)
    with pytest.raises(RuntimeError, match="synthetic apply crash"):
        await BillingWorker(webhook_settings(), factory, sources.require_lbx()).tick(WorkLane.URGENT)
    assert receipts(factory)[0].processing_state == State.PENDING
    assert subscription(factory).latest_observation_id == before.latest_observation_id
    assert subscription(factory).projection_valid_until == before.projection_valid_until
    assert queue(factory, before).work_state == "running"


async def test_billing_webhook_completely_lost_notification_converges_in_disabled_polling_mode(
    client: httpx.AsyncClient,
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    config = webhook_settings(lbx_webhook_enabled=False)
    monkeypatch.setattr(entrypoint, "settings", config)
    assert (await deliver(client)).status_code == 404
    activate(transport)
    assert await BillingWorker(config, factory, sources.require_lbx()).tick(WorkLane.URGENT)
    assert receipts(factory) == []
    assert subscription(factory).financial_access_status.value == "allowed"
