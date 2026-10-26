"""Durable review regressions: unsent release versus uncertain-send recovery."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Coroutine
from dataclasses import replace
from typing import Any, TypeVar
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import billing
from app.composition.sources import source_resources
from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.customers import claim_customer_send, release_unsent_claim, reserve_customer
from app.domains.catalog.publication import SessionFactory
from app.core.settings import Settings
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.models import (
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalCreateOperationState as State,
    PurchaseIntent,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed

pytestmark = pytest.mark.postgres
T = TypeVar("T")


@pytest.mark.parametrize("refusal", ["after_claim", "before_task", "after_schedule"])
def test_any709_step2_proven_unsent_bootstrap_releases_only_its_claim_and_reuses_identity(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    refusal: str,
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings()
    claims: list[CustomerOpen] = []
    posts: list[dict[str, Any]] = []
    rejected = False
    reject_check = False
    real_check, real_run = PreflightBudget.check, PreflightBudget.run

    def claim(factory: SessionFactory, config: Settings, token: str, current: CustomerOpen) -> CustomerOpen:
        result = claim_customer_send(factory, config, token, current)
        # The worker has returned from commit, unlike an uncertain commit/crash.
        claims.append(result)
        return result

    def check(budget: PreflightBudget) -> None:
        nonlocal rejected
        if not rejected and claims and (refusal == "after_claim" or reject_check):
            rejected = True
            raise PreflightDeadlineExceeded()
        real_check(budget)

    async def run(
        budget: PreflightBudget,
        source: Callable[[], Coroutine[Any, Any, T]],
        *,
        on_schedule: Callable[[asyncio.Task[T]], None] | None = None,
    ) -> T:
        nonlocal reject_check
        if refusal == "before_task" and on_schedule is not None and not rejected:
            reject_check = True

        def scheduled(task: asyncio.Task[T]) -> None:
            nonlocal reject_check
            on_schedule(task)
            if refusal == "after_schedule" and not rejected:
                reject_check = True

        return await real_run(budget, source, on_schedule=scheduled if on_schedule is not None else None)

    monkeypatch.setattr(billing, "claim_customer_send", claim)
    monkeypatch.setattr(PreflightBudget, "check", check)
    monkeypatch.setattr(PreflightBudget, "run", run)

    def transport(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "private-server", "expires_in": 600}})
        if request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        assert posts  # No discovery is needed for an operation proven unsent.
        return httpx.Response(200, json={"code": 200, "response": {"user_id": 345, "outer_id": posts[0]["outer_id"]}})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            with pytest.raises(BillingRefused, match="billing_source_unavailable"):
                await billing.bootstrap_account(sources, config, factory=factory, token=TOKEN)
            assert posts == [] and rejected
            with factory() as db:
                operation = db.scalar(select(ExternalCreateOperation))
                assert operation.operation_state == State.PENDING
                assert operation.unknown_since is None and operation.unknown_recovery_deadline_at is None
                assert db.scalar(select(BillingWorkItem)).work_state == "done"
            for _ in range(2):  # Both opens are explicit; the second reuses the binding.
                assert (await billing.bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential

    asyncio.run(scenario())
    assert len(posts) == 1 and len(claims) == 2
    assert claims[0].operation_id == claims[1].operation_id
    assert claims[0].outer_key == claims[1].outer_key == posts[0]["outer_id"]
    assert claims[0].fence != claims[1].fence
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 1
        assert db.scalar(select(func.count()).select_from(ExternalCreateOperation)) == 1
        assert db.scalar(select(func.count()).select_from(BillingWorkItem)) == 1
        assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 0
        assert db.scalar(select(ExternalCreateOperation)).operation_state == State.BOUND


@pytest.mark.parametrize(
    "failure,expected",
    [
        (503, "billing_source_unavailable"),
        (429, "billing_source_unavailable"),
        ("timeout", "billing_source_unavailable"),
        (401, "billing_server_auth_failed"),
        ("credentials_500", "billing_server_auth_failed"),
        ("invalid", "billing_source_invalid_response"),
    ],
)
def test_any709_step2_preauth_outage_leaves_the_same_operation_pending_without_a_send(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], failure: int | str, expected: str
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings(lbx_max_get_attempts=2)
    calls: list[tuple[str, str]] = []

    def transport(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if failure == "timeout":
            raise httpx.ReadTimeout("private timeout", request=request)
        if failure == "invalid":
            return httpx.Response(200, json={"code": 200, "response": {}})
        if failure == "credentials_500":
            return httpx.Response(
                500, json={"code": 500, "response": "Invalid login/pass. Client login: private-login"}
            )
        return httpx.Response(failure, json={"code": failure})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            first = None
            for _ in range(2):
                with pytest.raises(BillingRefused, match=expected):
                    await billing.bootstrap_account(sources, config, factory=factory, token=TOKEN)
                current = reserve_customer(factory, config, TOKEN)
                if first is None:
                    first = current
                assert (current.operation_id, current.outer_key) == (first.operation_id, first.outer_key)
                with factory() as db:
                    operation = db.scalar(select(ExternalCreateOperation))
                    assert operation.operation_state == State.PENDING and operation.send_fence is None
                    assert operation.unknown_since is None and operation.unknown_recovery_deadline_at is None
                    assert db.scalar(select(func.count()).select_from(BillingWorkItem)) == 0

    asyncio.run(scenario())
    assert calls == [("GET", "/api/rest/v1/auth")] * (2 if failure in {401, "invalid", "credentials_500"} else 4)


def test_any709_step2_lost_create_response_and_empty_discovery_never_release_or_replay(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings()
    posts = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "private-server", "expires_in": 600}})
        if request.method == "POST":
            posts += 1
            raise httpx.ReadTimeout("lost reply", request=request)
        assert request.url.path.endswith("/users")
        return httpx.Response(200, json={"code": 200, "response": []})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            identity = None
            for _ in range(3):
                with pytest.raises(BillingRefused, match="billing_customer_pending"):
                    await billing.bootstrap_account(sources, config, factory=factory, token=TOKEN)
                with factory() as db:
                    operation = db.scalar(select(ExternalCreateOperation))
                    assert operation.operation_state == State.UNKNOWN
                    current = (
                        operation.create_operation_id,
                        operation.send_fence,
                        operation.unknown_since,
                        operation.unknown_recovery_deadline_at,
                    )
                    if identity is None:
                        identity = current
                    assert current == identity
                    assert db.scalar(select(BillingWorkItem)).work_state == "pending"

    asyncio.run(scenario())
    assert posts == 1


def test_any709_step2_unsent_release_rejects_nonowner_and_changed_claims(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings()
    slot = reserve_customer(factory, config, TOKEN)
    owner = claim_customer_send(factory, config, TOKEN, slot)
    loser = claim_customer_send(factory, config, TOKEN, slot)
    for invalid in (
        loser,
        replace(owner, operation_id=uuid4()),
        replace(owner, fence=uuid4()),
        replace(owner, outer_key="changed"),
    ):
        with pytest.raises(BillingRefused, match="billing_customer_pending"):
            release_unsent_claim(factory, invalid)
    release_unsent_claim(factory, owner)
    newer = claim_customer_send(factory, config, TOKEN, reserve_customer(factory, config, TOKEN))
    with pytest.raises(BillingRefused, match="billing_customer_pending"):
        release_unsent_claim(factory, owner)
    with factory() as db:
        operation = db.scalar(select(ExternalCreateOperation))
        assert operation.operation_state == State.POSSIBLE_SEND and operation.send_fence == newer.fence


def test_any709_step2_client_credentials_denial_preserves_bound_customer_without_another_post(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings()
    outer = ""
    posts = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal outer, posts
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "server", "expires_in": 600}})
        if request.method == "POST":
            posts += 1
            outer = json.loads(request.content)["outer_id"]
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        if request.url.path.endswith("/client/user"):
            return httpx.Response(
                500, json={"code": 500, "response": "Invalid login/pass. Client login: private-login"}
            )
        return httpx.Response(200, json={"code": 200, "response": {"user_id": 345, "outer_id": outer}})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(transport)) as sources:
            for _ in range(2):
                with pytest.raises(BillingRefused, match="billing_client_not_ready"):
                    await billing.bootstrap_account(sources, config, factory=factory, token=TOKEN)
                with factory() as db:
                    assert db.scalar(select(ExternalCreateOperation)).operation_state == State.BOUND
                    assert db.scalar(select(ExternalBillingCustomer)).provider_customer_id == "345"

    asyncio.run(scenario())
    assert posts == 1
