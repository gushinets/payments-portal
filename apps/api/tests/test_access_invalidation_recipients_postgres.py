"""Recipient isolation on real PostgreSQL; backend HTTP responses are synthetic."""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from alembic import command
from sqlalchemy import delete, select, text
from sqlalchemy.engine import URL
from sqlalchemy.orm import Session, sessionmaker

from app.composition.backend_consumers import initialize_backend_consumers
from app.composition.billing_worker import billing_worker_resources
from app.core.settings import Settings
from app.domains.billing import access_invalidation as delivery, work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.work_contracts import (
    DeliveryLane,
    InvalidationDelivery,
    InvalidationFailureCode,
    WorkClaim,
    WorkLane,
)
from app.domains.catalog.contracts import SourceProvenance
from app.integrations.kernel.client import ManifestConnection, PlatformKernelClient
from app.jobs.billing import BillingWorker
from app.models import (
    AccessInvalidationOutbox,
    BillingWorkItem,
    PaidAccessState,
    PurchasedAllowance,
    ExternalSubscription,
)
from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer
from apps.api.tests.support.postgres import alembic_test_config
from apps.api.tests.test_access_invalidation_delivery_postgres import pending as pending
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario, paid_source as paid_source, reconcile

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
KERNEL = "platform-kernel"
SUMMARY = "synthetic-summary"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def recipients(pending: tuple) -> tuple[sessionmaker[Session], Settings, UUID]:
    factory, config, identity = pending
    config = config.model_copy(update={"backend_consumers": (backend_consumer(), second_consumer())})
    initialize_backend_consumers(config, factory)
    with factory.begin() as db:
        db.add(
            AccessInvalidationOutbox(
                recipient_id=SUMMARY,
                tenant_id="anytoolai",
                region="ru",
                user_id=identity,
                pending_revision=1,
                delivered_revision=0,
                next_attempt_at=datetime.now(UTC),
            )
        )
        delivery.schedule_delivery(db, identity, datetime.now(UTC), recipient_id=SUMMARY)
    return factory, config, identity


def status(factory: sessionmaker[Session], config: Settings, identity: UUID, recipient: str) -> dict:
    return delivery.inspect_delivery(factory, config, identity, recipient_id=recipient)


def clients(config: Settings, handler: httpx.AsyncBaseTransport) -> dict[str, PlatformKernelClient]:
    return {
        consumer.consumer_id: PlatformKernelClient(
            config,
            provenance=SourceProvenance.CONFIGURED_SOURCE,
            transport=handler,
            max_connections=config.billing_worker_delivery_concurrency,
            connection=ManifestConnection(consumer.backend_base_url, consumer.portal_to_backend_current_secret),
        )
        for consumer in config.backend_consumers
    }


@pytest.mark.parametrize("failure", [401, 503])
async def test_recipient_failure_ack_n_plus_one_and_cli_are_independent(recipients: tuple, failure: int) -> None:
    factory, config, identity = recipients
    requests: list[tuple[str, int]] = []
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        consumer = next(item for item in config.backend_consumers if request.url.host in item.backend_base_url)
        assert (
            request.headers["authorization"] == "Bearer " + consumer.portal_to_backend_current_secret.get_secret_value()
        )
        payload = json.loads(request.content)
        assert set(payload) == {"schema_version", "tenant_id", "region", "user_id", "access_revision"}
        assert payload["schema_version"] == 1
        requests.append((consumer.consumer_id, payload["access_revision"]))
        if consumer.consumer_id == SUMMARY:
            entered.set()
            await release.wait()
            return httpx.Response(failure, text="synthetic-private-backend-body")
        if payload["access_revision"] == 1:
            with factory.begin() as db:
                work.lock_user(db, identity)
                delivery.paid_access.outbox(db, identity, KERNEL).pending_revision = 2
                delivery.schedule_delivery(db, identity, datetime.now(UTC), recipient_id=KERNEL)
        return httpx.Response(204)

    connections = clients(config, httpx.MockTransport(respond))
    worker = BillingWorker(config, factory, None, delivery_clients=connections)
    blocked = asyncio.create_task(worker.tick(DeliveryLane(SUMMARY)))
    try:
        await asyncio.wait_for(entered.wait(), 3)
        # The only summary slot is blocked; Kernel has independent HTTP and DB capacity.
        assert not await worker.tick(DeliveryLane(SUMMARY))
        assert await asyncio.wait_for(worker.tick(DeliveryLane(KERNEL)), 3)
        kernel = status(factory, config, identity, KERNEL)
        summary = status(factory, config, identity, SUMMARY)
        assert (kernel["pending_revision"], kernel["delivered_revision"], kernel["work_state"]) == (2, 1, "pending")
        assert (summary["pending_revision"], summary["delivered_revision"], summary["work_state"]) == (1, 0, "running")
        assert await worker.tick(DeliveryLane(KERNEL))
        release.set()
        assert await blocked
        assert status(factory, config, identity, KERNEL)["delivered_revision"] == 2
        summary = status(factory, config, identity, SUMMARY)
        assert summary["work_state"] == ("invalid" if failure == 401 else "pending")
        assert summary["delivered_revision"] == 0 and summary["attempt_count"] == 1
        assert summary["next_attempt_at"] > datetime.now(UTC).isoformat()
        assert delivery.repair_delivery(factory, config) == 0
        if failure == 401:
            before = status(factory, config, identity, KERNEL)
            retried = delivery.inspect_delivery(factory, config, identity, recipient_id=SUMMARY, retry=True)
            assert retried["work_state"] == "pending"
            assert status(factory, config, identity, KERNEL) == before
        assert requests == [(SUMMARY, 1), (KERNEL, 1), (KERNEL, 2)]
    finally:
        release.set()
        await blocked
        await worker.aclose()
        for connection in connections.values():
            await connection.aclose()


def test_claim_cannot_ack_other_recipient_and_restart_repairs_each_missing_work(recipients: tuple) -> None:
    factory, config, identity = recipients
    claim = work.claim_work(factory, config, WorkLane.DELIVERY, recipient_id=KERNEL)
    sent = delivery.capture_delivery(factory, config, claim)
    before = status(factory, config, identity, SUMMARY)
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        delivery.apply_delivery(factory, claim, replace(sent, recipient_id=SUMMARY))
    assert status(factory, config, identity, SUMMARY) == before
    with factory.begin() as db:
        db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == delivery.KIND))
    assert delivery.repair_delivery(factory, config) == 2
    assert delivery.repair_delivery(factory, config) == 0
    # A pre-repair row/claim cannot settle replacement work, even at the same R.
    with pytest.raises(BillingRefused, match="billing_work_stale"):
        delivery.apply_delivery(factory, claim, sent)
    for recipient in (KERNEL, SUMMARY):
        current = work.claim_work(factory, config, WorkLane.DELIVERY, recipient_id=recipient)
        assert current.recipient_id == recipient
        captured = delivery.capture_delivery(factory, config, current)
        delivery.apply_delivery(factory, current, captured)
        assert status(factory, config, identity, recipient)["delivered_revision"] == 1


@pytest.mark.parametrize("retirement", ["removed", "permission"])
@pytest.mark.parametrize("old_state", ["missing", "completed", "pending", "running", "invalid"])
async def test_writer_atomic_fanout_removal_noop_and_rollback(
    paid_source: Scenario, monkeypatch: pytest.MonkeyPatch, retirement: str, old_state: str
) -> None:
    scenario = paid_source
    config = scenario.config.model_copy(
        update={
            "backend_consumers": (
                backend_consumer(),
                second_consumer(),
                second_consumer(
                    consumer_id="identity-only",
                    technical_source_id="identity-only",
                    allowed_products=[],
                    permissions=["backend-session:introspect"],
                    backend_to_portal_current_secret="identity-service-" + "i" * 32,
                    backend_to_portal_previous_secret=None,
                    portal_to_backend_current_secret="portal-to-identity-" + "i" * 32,
                ),
            )
        }
    )
    initialize_backend_consumers(config, scenario.factory)
    await reconcile(scenario)
    with scenario.factory() as db:
        assert set(db.scalars(select(AccessInvalidationOutbox.recipient_id))) == {KERNEL, SUMMARY}
        identity = db.scalar(select(PaidAccessState.user_id))
        allowance_ids = list(db.scalars(select(PurchasedAllowance.allowance_id)))
    summary_claim = work.claim_work(scenario.factory, config, WorkLane.DELIVERY, recipient_id=SUMMARY)
    summary_sent = delivery.capture_delivery(scenario.factory, config, summary_claim)
    delivery.apply_delivery(scenario.factory, summary_claim, summary_sent, error=InvalidationFailureCode.UNAVAILABLE)
    unchanged = {key: status(scenario.factory, config, identity, key) for key in (KERNEL, SUMMARY)}
    await reconcile(scenario)
    assert {key: status(scenario.factory, config, identity, key) for key in (KERNEL, SUMMARY)} == unchanged
    scenario.transport.subscriptions[0]["current_blocking"] = 1
    original = delivery.schedule_delivery

    def fail_second(db: Session, user_id: UUID, now: datetime, *, recipient_id: str, hint: bool = True) -> None:
        original(db, user_id, now, recipient_id=recipient_id, hint=hint)
        if recipient_id == SUMMARY:
            raise RuntimeError("synthetic fanout rollback")

    with monkeypatch.context() as patch:
        patch.setattr(delivery, "schedule_delivery", fail_second)
        with pytest.raises(RuntimeError, match="fanout rollback"):
            await reconcile(scenario)
    assert {key: status(scenario.factory, config, identity, key) for key in (KERNEL, SUMMARY)} == unchanged
    with scenario.factory() as db:
        assert db.scalar(select(PaidAccessState.access_revision)) == 1
    # The source claim committed before the failed apply still owns its lease.
    # Model retry after expiry without weakening production claim ownership.
    with scenario.factory.begin() as db:
        db.get(ExternalSubscription, scenario.subscription_id).reconciliation_lease_expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    await reconcile(scenario)
    with scenario.factory() as db:
        state = db.scalar(select(PaidAccessState))
        assert state.access_revision == 2 and state.effective_state_document == {"grants": [], "allowances": []}
        assert list(db.scalars(select(PurchasedAllowance.allowance_id))) == allowance_ids
    assert all(status(scenario.factory, config, identity, key)["pending_revision"] == 2 for key in (KERNEL, SUMMARY))
    from app.infrastructure.queries import billing_work
    from app.models import BillingWorkState

    with scenario.factory.begin() as db:
        row = billing_work.by_key(db, delivery.KIND, delivery.delivery_key(SUMMARY, identity))
        if old_state == "missing":
            db.delete(row)
        else:
            row.work_state = BillingWorkState(old_state)
            if old_state == "running":
                row.lease_owner = "retained-writer-test"
                row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=2)
    # Both ways of disabling a recipient preserve every scheduling/history state.
    registry = (
        (backend_consumer(),)
        if retirement == "removed"
        else (
            backend_consumer(),
            second_consumer(consumer_policy_revision=2, permissions=["backend-session:introspect"]),
        )
    )
    initialize_backend_consumers(config.model_copy(update={"backend_consumers": registry}), scenario.factory)
    retired = status(scenario.factory, config, identity, SUMMARY)
    await reconcile(scenario)  # Semantic no-op must not re-enqueue retired work.
    assert status(scenario.factory, config, identity, SUMMARY) == retired
    scenario.transport.subscriptions[0]["current_blocking"] = 0
    await reconcile(scenario)
    assert status(scenario.factory, config, identity, SUMMARY) == retired
    assert status(scenario.factory, config, identity, KERNEL)["pending_revision"] == 3
    assert status(scenario.factory, config, identity, SUMMARY)["pending_revision"] == 2


@pytest.mark.parametrize("old_state", ["pending", "running", "invalid", "completed", "missing"])
def test_forward_migration_preserves_history_and_retires_old_claims(
    pending: tuple,
    database_test_url: URL,
    old_state: str,
) -> None:
    factory, config, identity = pending
    now = datetime.now(UTC)
    with alembic_test_config(database_test_url) as migrations:
        command.downgrade(migrations, "20261111_0009")
        with factory.begin() as db:
            db.execute(
                text(
                    "UPDATE access_invalidation_outbox SET pending_revision=6, delivered_revision=2, "
                    "attempt_count=7, last_error_classification='kernel_invalidation_unavailable'"
                )
            )
            if old_state == "missing":
                db.execute(text("DELETE FROM billing_work_items WHERE work_kind='access_invalidation'"))
                before_work = None
            else:
                db.execute(
                    text(
                        "UPDATE billing_work_items SET work_state=:state, enqueue_generation=9, "
                        "attempt_count=7, lease_owner=:owner, lease_expires_at=:expiry "
                        "WHERE work_kind='access_invalidation'"
                    ),
                    {
                        "state": old_state,
                        "owner": "pre-cutover-owner" if old_state == "running" else None,
                        "expiry": now + timedelta(minutes=2) if old_state == "running" else None,
                    },
                )
                before_work = db.execute(text("SELECT * FROM billing_work_items")).mappings().one()
            before_outbox = db.execute(text("SELECT * FROM access_invalidation_outbox")).mappings().one()
        command.upgrade(migrations, "head")
    initialize_backend_consumers(config, factory)
    with factory() as db:
        after_outbox = db.execute(text("SELECT * FROM access_invalidation_outbox")).mappings().one()
        assert dict(after_outbox) == dict(before_outbox) | {"recipient_id": KERNEL}
        if before_work:
            after_work = db.execute(text("SELECT * FROM billing_work_items")).mappings().one()
            assert dict(after_work) == dict(before_work) | {
                "recipient_id": KERNEL,
                "coalescing_key": delivery.delivery_key(KERNEL, identity),
                "work_state": "pending" if old_state == "running" else old_state,
                "enqueue_generation": 10 if old_state == "running" else 9,
                "lease_owner": None,
                "lease_expires_at": None,
            }
    if old_state == "running":
        old_claim = WorkClaim(
            before_work["work_item_id"],
            delivery.KIND,
            str(identity),
            "pre-cutover-owner",
            9,
            now,
            now + timedelta(minutes=2),
        )
        old_sent = InvalidationDelivery(KERNEL, "anytoolai", "ru", identity, 5)
        with pytest.raises(BillingRefused, match="billing_work_stale"):
            delivery.apply_delivery(factory, old_claim, old_sent)
    assert delivery.repair_delivery(factory, config) == int(old_state in {"missing", "completed"})
    assert delivery.repair_delivery(factory, config) == 0
    if old_state != "invalid":
        claim = work.claim_work(factory, config, WorkLane.DELIVERY, recipient_id=KERNEL)
        sent = delivery.capture_delivery(factory, config, claim)
        assert sent.revision == 6
        delivery.apply_delivery(factory, claim, sent)
        assert status(factory, config, identity, KERNEL)["delivered_revision"] == 6
    else:
        assert work.claim_work(factory, config, WorkLane.DELIVERY, recipient_id=KERNEL) is None
        assert status(factory, config, identity, KERNEL)["work_state"] == "invalid"


async def test_registry_composition_uses_independent_credentials_without_legacy_kernel_connection(
    recipients: tuple,
) -> None:
    factory, config, identity = recipients
    config = config.model_copy(update={"billing_worker_enabled": True, "kernel_base_url": ""})
    requests: set[str] = set()

    def respond(request: httpx.Request) -> httpx.Response:
        consumer = next(item for item in config.backend_consumers if request.url.host in item.backend_base_url)
        assert (
            request.headers["authorization"] == "Bearer " + consumer.portal_to_backend_current_secret.get_secret_value()
        )
        requests.add(consumer.consumer_id)
        return httpx.Response(204)

    async with billing_worker_resources(
        config, factory=factory, invalidation_transport=httpx.MockTransport(respond)
    ) as worker:
        assert len(worker.delivery_clients) == 2
        async with asyncio.timeout(5):
            while any(status(factory, config, identity, key)["delivered_revision"] != 1 for key in (KERNEL, SUMMARY)):
                await asyncio.sleep(0.01)
    assert requests == {KERNEL, SUMMARY}
    assert worker.cleanup_pending == 0 and all(task.done() for task in worker.tasks)


def test_recipient_storage_identity_is_immutable_and_unsafe_downgrade_refused(
    recipients: tuple,
    database_test_url: URL,
) -> None:
    from sqlalchemy.exc import DatabaseError

    factory, config, identity = recipients
    before = status(factory, config, identity, KERNEL)
    with pytest.raises(DatabaseError), factory.begin() as db:
        db.execute(
            text("UPDATE access_invalidation_outbox SET recipient_id='other' WHERE recipient_id=:recipient"),
            {"recipient": KERNEL},
        )
    assert status(factory, config, identity, KERNEL) == before
    with alembic_test_config(database_test_url) as migrations:
        with pytest.raises(RuntimeError, match="downgrade is unsafe"):
            command.downgrade(migrations, "20261111_0009")
    assert status(factory, config, identity, KERNEL) == before
    assert status(factory, config, identity, SUMMARY)["pending_revision"] == 1


async def test_cleanup_held_by_one_recipient_does_not_block_another(recipients: tuple) -> None:
    factory, config, identity = recipients
    config = config.model_copy(
        update={"billing_worker_io_timeout_seconds": 0.2, "preflight_cleanup_timeout_seconds": 0.02}
    )
    entered, release = asyncio.Event(), asyncio.Event()

    class SlowClose(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            yield b""

        async def aclose(self) -> None:
            entered.set()
            await release.wait()

    def respond(request: httpx.Request) -> httpx.Response:
        return (
            httpx.Response(204, stream=SlowClose())
            if request.url.host == "summary.example.test"
            else httpx.Response(204)
        )

    connections = clients(config, httpx.MockTransport(respond))
    worker = BillingWorker(config, factory, None, delivery_clients=connections)
    attempt = asyncio.create_task(worker.tick(DeliveryLane(SUMMARY)))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert await attempt
        assert worker.admissions[DeliveryLane(SUMMARY)].active_count == 1
        assert not await worker.tick(DeliveryLane(SUMMARY))
        assert await worker.tick(DeliveryLane(KERNEL))
        assert status(factory, config, identity, KERNEL)["delivered_revision"] == 1
        assert status(factory, config, identity, SUMMARY)["delivered_revision"] == 0
    finally:
        release.set()
        await attempt
        await worker.aclose()
        for connection in connections.values():
            await connection.aclose()


@pytest.mark.parametrize("retirement", ["removed", "permission"])
@pytest.mark.parametrize("old_state", ["missing", "completed", "pending", "running", "invalid"])
def test_inactive_recipient_is_not_repaired_or_retried(recipients: tuple, retirement: str, old_state: str) -> None:
    factory, config, identity = recipients
    from app.core.backend_consumers import BackendPermission
    from app.infrastructure.queries import billing_work
    from app.models import BillingWorkState

    with factory.begin() as db:
        row = billing_work.by_key(db, delivery.KIND, delivery.delivery_key(SUMMARY, identity))
        if old_state == "missing":
            db.delete(row)
        else:
            row.work_state = BillingWorkState(old_state)
            if old_state == "running":
                row.lease_owner = "retained-owner"
                row.lease_expires_at = datetime.now(UTC) + timedelta(minutes=2)
    retired = config.model_copy(
        update={
            "backend_consumers": (backend_consumer(),)
            if retirement == "removed"
            else (
                backend_consumer(),
                second_consumer(consumer_policy_revision=2, permissions=[BackendPermission.INTROSPECT]),
            )
        }
    )
    initialize_backend_consumers(retired, factory)
    before = status(factory, retired, identity, SUMMARY)
    assert delivery.repair_delivery(factory, retired) == 0
    assert status(factory, retired, identity, SUMMARY) == before
    pending_count, _, parked_count = work.inspect_backlog(factory, retired)
    assert (pending_count, parked_count) == (1, 0)
    with pytest.raises(BillingRefused, match="invalidation_recipient_inactive"):
        delivery.inspect_delivery(factory, retired, identity, recipient_id=SUMMARY, retry=True)
    restored = config.model_copy(
        update={
            "backend_consumers": (
                backend_consumer(),
                second_consumer(consumer_policy_revision=3),
            )
        }
    )
    initialize_backend_consumers(restored, factory)
    assert delivery.repair_delivery(factory, restored) == int(old_state in {"missing", "completed"})
    if old_state == "invalid":
        assert (
            delivery.inspect_delivery(factory, restored, identity, recipient_id=SUMMARY, retry=True)["work_state"]
            == "pending"
        )
    assert status(factory, restored, identity, SUMMARY)["pending_revision"] == before["pending_revision"]
    assert status(factory, restored, identity, SUMMARY)["delivered_revision"] == before["delivered_revision"]


@pytest.mark.parametrize("retire_during_scan", [False, True])
def test_repair_filters_before_limit_and_rechecks_scoped_membership(
    recipients: tuple,
    monkeypatch: pytest.MonkeyPatch,
    retire_during_scan: bool,
) -> None:
    from app.infrastructure.queries import billing_work

    factory, config, identity = recipients
    config = config.model_copy(update={"backend_consumers": (second_consumer(),), "billing_worker_scan_batch_size": 1})
    initialize_backend_consumers(config, factory)
    with factory.begin() as db:
        db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == delivery.KIND))
    original = billing_work.missing_invalidations

    def candidates(db: Session, tenant: str, region: str, limit: int) -> list[tuple[str, UUID]]:
        result = original(db, tenant, region, limit)
        assert result == [(SUMMARY, identity)]  # Retired Kernel sorts first, but cannot consume LIMIT.
        if retire_during_scan:
            initialize_backend_consumers(config.model_copy(update={"backend_consumers": ()}), factory)
        return result

    monkeypatch.setattr(billing_work, "missing_invalidations", candidates)
    assert delivery.repair_delivery(factory, config) == int(not retire_during_scan)
    assert status(factory, config, identity, KERNEL)["work_state"] == "unscheduled"
