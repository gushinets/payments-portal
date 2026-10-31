"""Owner-approved bounded find/create/recover customer flow."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.sources import source_resources
from app.core.time import utc_now
from app.domains.billing.contracts import BillingAccountFailure
from app.domains.billing.customers import claim_customer_send, reserve_customer
from app.models import (
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationState as State,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "mode",
    [
        "new",
        "existing",
        "duplicate",
        "unknown_error_after_effect",
        "old_review",
        "expired_claim",
        "email_unproven",
        "ambiguous",
        "duplicate_invisible",
    ],
)
def test_customer_ensure_find_create_recover(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    mode: str,
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings(preflight_total_timeout_seconds=0.6, preflight_cleanup_timeout_seconds=0.025)
    slot = reserve_customer(factory, config, TOKEN)
    if mode in {"old_review", "expired_claim"}:
        claim_customer_send(factory, config, TOKEN, slot)
        with factory() as db:
            operation = db.scalar(select(ExternalCreateOperation))
            work = db.scalar(select(BillingWorkItem))
            operation.operation_state = State.MANUAL_REVIEW if mode == "old_review" else State.POSSIBLE_SEND
            work.lease_expires_at = utc_now() - timedelta(seconds=1)
            db.commit()
    calls = []
    posts = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert migrated_database.pool.checkedout() == 0
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/auth"):
            data = {"token": "PRIVATE", "expires_in": 600}
        elif request.method == "POST":
            body = json.loads(request.content)
            assert body["outer_id"] == slot.outer_key
            posts.append(body)
            if mode in {"duplicate", "duplicate_invisible"}:
                return httpx.Response(
                    500, json={"code": 500, "response": {"error": "Invalid email PRIVATE. Email must be unique"}}
                )
            if mode == "unknown_error_after_effect":
                return httpx.Response(500, json={"code": 500, "response": {"error": "PRIVATE-unknown-rejection"}})
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        elif request.url.path.endswith("/users"):
            body = json.loads(request.content)
            assert body["show_passwords"] is False
            ids = []
            if mode == "existing" or mode in {"duplicate", "unknown_error_after_effect"} and posts:
                ids = [345]
            if mode == "ambiguous":
                ids = [345, 346]
            if mode == "email_unproven" and "email" in body:
                ids = [345]
            data = [{"user_id": value} for value in ids]
        else:
            data = {
                "user_id": 345,
                "outer_id": "different" if mode == "email_unproven" else slot.outer_key,
                "password": "DISCARD",
            }
        return httpx.Response(200, json={"code": 200, "response": data})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            if mode in {"email_unproven", "ambiguous", "duplicate_invisible"}:
                with pytest.raises(BillingAccountFailure):
                    await bootstrap_account(sources, config, factory=factory, token=TOKEN)
            else:
                for _ in range(2):
                    assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential

    asyncio.run(scenario())
    assert len(posts) == (0 if mode in {"existing", "ambiguous", "email_unproven"} else 1)
    if posts:
        assert calls.index(("GET", "/api/rest/v1/users")) < calls.index(("POST", "/api/rest/v1/users"))
    with factory() as db:
        customer = db.scalar(select(ExternalBillingCustomer))
        operation = db.scalar(select(ExternalCreateOperation))
        assert customer.billing_customer_key == slot.outer_key
        assert operation.create_operation_id == slot.operation_id
        if mode not in {"email_unproven", "ambiguous", "duplicate_invisible"}:
            assert customer.provider_customer_id == "345" and operation.operation_state == State.BOUND
            work = db.scalar(select(BillingWorkItem))
            if work:
                assert work.lease_owner is None and work.work_state == "done"
        else:
            assert customer.provider_customer_id is None


def test_customer_ensure_corrected_email_retries_on_next_open_without_reset(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings(preflight_total_timeout_seconds=0.6, preflight_cleanup_timeout_seconds=0.025)
    slot = reserve_customer(factory, config, TOKEN)
    posts = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            data = {"token": "PRIVATE", "expires_in": 600}
        elif request.method == "POST":
            posts.append(json.loads(request.content))
            if len(posts) == 1:
                return httpx.Response(
                    500, json={"code": 500, "response": {"error": "Invalid email PRIVATE. Email must be unique"}}
                )
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        elif request.url.path.endswith("/users"):
            data = []
        else:
            data = {"user_id": 345, "outer_id": slot.outer_key}
        return httpx.Response(200, json={"code": 200, "response": data})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            with pytest.raises(BillingAccountFailure):
                await bootstrap_account(sources, config, factory=factory, token=TOKEN)
            with factory() as db:
                assert db.scalar(select(BillingWorkItem)).lease_owner is None
            assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential

    asyncio.run(scenario())
    assert len(posts) == 2 and all(body["outer_id"] == slot.outer_key for body in posts)
    with factory() as db:
        assert db.scalar(select(ExternalCreateOperation)).create_operation_id == slot.operation_id
        assert db.scalar(select(BillingWorkItem)).attempt_count == 2


def test_customer_failed_attempt_invalidates_concurrent_presearch_snapshot(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.domains.billing.customers import finish_customer_attempt, record_customer_receipt
    from app.domains.billing.contracts import BillingRefused

    factory = postgres_session_factory
    config = step1_settings()
    seed(factory)
    first = claim_customer_send(factory, config, TOKEN, reserve_customer(factory, config, TOKEN))
    concurrent = reserve_customer(factory, config, TOKEN)
    finish_customer_attempt(factory, first)
    stale = claim_customer_send(factory, config, TOKEN, concurrent)
    assert not stale.may_create and stale.fence != first.fence
    fresh = claim_customer_send(factory, config, TOKEN, reserve_customer(factory, config, TOKEN))
    assert fresh.may_create and fresh.operation_id == first.operation_id
    assert fresh.fence != stale.fence
    with pytest.raises(BillingRefused):
        record_customer_receipt(factory, first, 345)
    finish_customer_attempt(factory, first)
    with factory() as db:
        assert db.scalar(select(BillingWorkItem)).lease_owner == f"customer-send:{fresh.fence}"
