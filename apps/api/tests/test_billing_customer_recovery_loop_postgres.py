"""Bounded same-opening customer recovery; all provider traffic is synthetic."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.sources import source_resources
from app.domains.billing.customers import reserve_customer
from app.domains.billing.contracts import BillingRefused
from app.models import BillingWorkItem, ExternalBillingCustomer, ExternalCreateOperation, ExternalCreateOperationState
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed

pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def short_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.composition.billing.CUSTOMER_RETRY_BASE_SECONDS", 0.01)
    monkeypatch.setattr("app.composition.billing.CUSTOMER_RETRY_MAX_SECONDS", 0.02)


@pytest.mark.parametrize("failure", ["lost_reply", "lost_reply_after_effect", "unavailable", "not_sent", "email_taken"])
def test_customer_recovers_in_one_opening(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], failure: str
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings()
    initial = reserve_customer(factory, config, TOKEN)
    posts: list[dict[str, object]] = []
    recovery_reads = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal recovery_reads
        assert migrated_database.pool.checkedout() == 0
        if request.url.path.endswith("/auth"):
            data = {"token": "synthetic", "expires_in": 600}
        elif request.method == "POST":
            posts.append(json.loads(request.content))
            if len(posts) == 1:
                if failure in {"lost_reply", "lost_reply_after_effect"}:
                    raise httpx.ReadTimeout("synthetic lost reply", request=request)
                if failure == "not_sent":
                    raise httpx.ConnectError("synthetic unsent", request=request)
                return httpx.Response(
                    500,
                    json={
                        "code": 500,
                        "response": {"error": "Invalid email synthetic. Email must be unique"}
                        if failure == "email_taken"
                        else {"error": "synthetic temporary failure"},
                    },
                )
            if failure == "lost_reply_after_effect":
                # The first send created the customer, but discovery lagged.
                # The provider's selected email-uniqueness policy rejects the
                # second send; it must recover the original ID, not create again.
                return httpx.Response(
                    500, json={"code": 500, "response": {"error": "Invalid email synthetic. Email must be unique"}}
                )
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        elif request.url.path.endswith("/users"):
            if posts:
                recovery_reads += 1
            visible = (
                failure == "email_taken"
                and recovery_reads >= 4
                or failure == "lost_reply_after_effect"
                and len(posts) >= 2
            )
            data = [{"user_id": 345}] if visible else []
        else:
            data = {"user_id": 345, "outer_id": initial.outer_key}
        return httpx.Response(200, json={"code": 200, "response": data})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential

    asyncio.run(scenario())
    assert len(posts) == (1 if failure == "email_taken" else 2)
    assert all(row["outer_id"] == initial.outer_key and row["email"] == "synthetic@example.com" for row in posts)
    with factory() as db:
        customer = db.scalar(select(ExternalBillingCustomer))
        operation = db.scalar(select(ExternalCreateOperation))
        work = db.scalar(select(BillingWorkItem))
        assert customer.provider_customer_id == "345"
        assert operation.create_operation_id == initial.operation_id
        assert work.attempt_count == len(posts) and work.lease_owner is None and work.work_state == "done"


@pytest.mark.parametrize("mode", ["discovery_down", "permanent_create", "receipt_wait", "email_foreign"])
def test_customer_recovery_never_turns_failed_reads_or_terminal_evidence_into_create(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], mode: str
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings(
        preflight_total_timeout_seconds=0.6, preflight_cleanup_timeout_seconds=0.025, lbx_max_get_attempts=2
    )
    initial = reserve_customer(factory, config, TOKEN)
    posts = 0
    failed_reads = 0
    ready = False

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal posts, failed_reads
        if request.url.path.endswith("/auth"):
            data = {"token": "synthetic", "expires_in": 600}
        elif request.method == "POST":
            posts += 1
            if mode == "permanent_create":
                return httpx.Response(400, json={"code": 400, "response": {"error": "synthetic invalid input"}})
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        elif request.url.path.endswith("/users"):
            if mode == "discovery_down" or mode == "permanent_create" and posts and failed_reads < 2:
                failed_reads += 1
                return httpx.Response(503)
            data = [{"user_id": 345}] if mode == "email_foreign" else []
            if mode == "receipt_wait":
                assert posts == 0  # A durable receipt requires point reads, never more discovery.
        else:
            if mode == "receipt_wait" and not ready:
                return httpx.Response(503)
            data = {"user_id": 345, "outer_id": "foreign" if mode == "email_foreign" else initial.outer_key}
        return httpx.Response(200, json={"code": 200, "response": data})

    async def scenario() -> None:
        nonlocal ready
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            code = (
                "billing_source_rejected"
                if mode == "permanent_create"
                else "billing_identity_conflict"
                if mode == "email_foreign"
                else "billing_customer_pending"
            )
            with pytest.raises(BillingRefused, match=code):
                await bootstrap_account(sources, config, factory=factory, token=TOKEN)
            if mode == "receipt_wait":
                with factory() as db:
                    operation = db.scalar(select(ExternalCreateOperation))
                    assert operation.recovery_hint_document == {"provider_customer_candidate_id": "345"}
                    assert operation.operation_state == ExternalCreateOperationState.UNKNOWN
                ready = True
                assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential

    asyncio.run(scenario())
    assert posts == (1 if mode in {"permanent_create", "receipt_wait"} else 0)
    if mode == "discovery_down":
        with factory() as db:
            assert db.scalar(select(ExternalCreateOperation)).operation_state == ExternalCreateOperationState.PENDING
            assert db.scalar(select(BillingWorkItem)) is None


def test_customer_caller_cancellation_retains_the_send_lease(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings()
    started = asyncio.Event()
    finish = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            data = {"token": "synthetic", "expires_in": 600}
        elif request.method == "POST":
            started.set()
            await finish.wait()
            raise AssertionError("the cancelled caller must not reach a completed send")
        else:
            data = []
        return httpx.Response(200, json={"code": 200, "response": data})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            opening = asyncio.create_task(bootstrap_account(sources, config, factory=factory, token=TOKEN))
            await asyncio.wait_for(started.wait(), timeout=2)
            opening.cancel()
            with pytest.raises(asyncio.CancelledError):
                await opening

    asyncio.run(scenario())
    with factory() as db:
        assert db.scalar(select(ExternalCreateOperation)).operation_state == ExternalCreateOperationState.POSSIBLE_SEND
        work = db.scalar(select(BillingWorkItem))
        assert work.attempt_count == 1 and work.lease_owner is not None and work.lease_expires_at is not None
