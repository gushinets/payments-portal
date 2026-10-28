"""Durable receipt recovery and phase-specific transport failures, isolated PostgreSQL."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.sources import source_resources
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import (
    apply_customer_read,
    claim_customer_send,
    record_customer_receipt,
    reserve_customer,
)
from app.models import ExternalBillingCustomer, ExternalCreateOperation, ExternalCreateOperationState as State
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize(
    "failure",
    [
        httpx.PoolTimeout,
        httpx.ConnectTimeout,
        httpx.ConnectError,
        httpx.WriteTimeout,
        httpx.ReadTimeout,
        httpx.WriteError,
        httpx.ReadError,
        httpx.RemoteProtocolError,
    ],
)
def test_any709_qa_transport_failure_recovers_in_the_same_discover_first_open(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], failure: type[httpx.TransportError]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings(lbx_max_get_attempts=2)
    attempts = 0
    outer = ""
    first = reserve_customer(factory, config, TOKEN)

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempts, outer
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "private", "expires_in": 600}})
        if request.method == "POST":
            attempts += 1
            outer = json.loads(request.content)["outer_id"]
            if attempts == 1:
                raise failure("private network diagnostics", request=request)
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        return httpx.Response(
            200,
            json={
                "code": 200,
                "response": [] if request.url.path.endswith("/users") else {"user_id": 345, "outer_id": outer},
            },
        )

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            await bootstrap_account(sources, config, factory=factory, token=TOKEN)
            await bootstrap_account(sources, config, factory=factory, token=TOKEN)
            assert reserve_customer(factory, config, TOKEN).operation_id == first.operation_id

    asyncio.run(scenario())
    assert attempts == 2


def test_any709_qa_receipt_survives_point_failure_without_more_discovery_or_create(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings(lbx_max_get_attempts=2)
    posts = 0
    points = 0
    outer = ""

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal posts, points, outer
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "private", "expires_in": 600}})
        if request.method == "POST":
            posts += 1
            outer = json.loads(request.content)["outer_id"]
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        if request.url.path.endswith("/users"):
            assert posts == 0  # Discovery precedes CREATE; saved receipt then skips lists.
            return httpx.Response(200, json={"code": 200, "response": []})
        if request.url.path.endswith("/users/345"):
            points += 1
            with factory() as db:
                operation = db.scalar(select(ExternalCreateOperation))
                customer = db.scalar(select(ExternalBillingCustomer))
                assert operation.recovery_hint_document == {"provider_customer_candidate_id": "345"}
                if points <= 2:
                    assert customer.provider_customer_id is None
                    return httpx.Response(503, json={"code": 503, "response": {"error": "private provider text"}})
        return httpx.Response(200, json={"code": 200, "response": {"user_id": 345, "outer_id": outer}})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            for _ in range(2):
                await bootstrap_account(sources, config, factory=factory, token=TOKEN)

    asyncio.run(scenario())
    assert posts == 1 and points == 4
    with factory() as db:
        assert db.scalar(select(ExternalCreateOperation)).operation_state == State.BOUND
        assert db.scalar(select(ExternalBillingCustomer)).provider_customer_id == "345"


def test_any709_qa_receipt_rejects_stale_fences_and_conflicting_candidates(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings()
    owner = claim_customer_send(factory, config, TOKEN, reserve_customer(factory, config, TOKEN))
    record_customer_receipt(factory, owner, 345)
    record_customer_receipt(factory, owner, 345)
    for expected, candidate in [
        (replace(owner, may_create=False), 345),
        (replace(owner, outer_key="different"), 345),
        (replace(owner, fence=None), 345),
        (owner, 346),
    ]:
        with pytest.raises(BillingRefused):
            record_customer_receipt(factory, expected, candidate)
    apply_customer_read(factory, owner, provider_id="345", outer_key=owner.outer_key)
    with pytest.raises(BillingRefused):
        record_customer_receipt(factory, owner, 345)


@pytest.mark.parametrize("names", [(None, None, None), ("Synthetic", None, None), ("Synthetic", "QA", "Test")])
def test_any709_qa_fresh_create_names_point_proof_and_reopen(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], names: tuple[str | None, ...]
) -> None:
    from app.models import User

    factory = postgres_session_factory
    seed(factory)
    config = step1_settings()
    posts = []
    outer = ""
    with factory() as db:
        user = db.scalar(select(User))
        user.first_name, user.surname, user.patronymic = names
        db.commit()

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal outer
        if request.url.path.endswith("/auth"):
            return httpx.Response(200, json={"code": 200, "response": {"token": "private", "expires_in": 600}})
        if request.method == "POST":
            body = json.loads(request.content)
            posts.append(body)
            outer = body["outer_id"]
            for key, value in zip(("user_name", "user_surname", "user_patronymic"), names, strict=True):
                assert body.get(key) == value and (value is not None or key not in body)
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        if request.url.path.endswith("/users"):
            assert posts == []
            return httpx.Response(200, json={"code": 200, "response": []})
        assert request.url.path.endswith(("/users/345", "/client/user"))
        return httpx.Response(
            200,
            json={"code": 200, "response": {"user_id": 345, "outer_id": outer, "password": "discard-provider-secret"}},
        )

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            for _ in range(2):
                assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential

    asyncio.run(scenario())
    assert len(posts) == 1
    with factory() as db:
        assert db.scalar(select(ExternalCreateOperation)).operation_state == State.BOUND
        assert db.scalar(select(ExternalBillingCustomer)).provider_customer_id == "345"


def test_any709_qa_short_list_recovery_uses_detailed_original_outer_identity(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings()
    current = claim_customer_send(factory, config, TOKEN, reserve_customer(factory, config, TOKEN))
    calls = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert request.method == "GET"
        if request.url.path.endswith("/auth"):
            data = {"token": "private", "expires_in": 600}
        elif request.url.path.endswith("/users"):
            data = [{"user_id": 345}]
        else:
            data = {"user_id": 345, "outer_id": current.outer_key, "password": "discard-provider-secret"}
        return httpx.Response(200, json={"code": 200, "response": data})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential

    asyncio.run(scenario())
    assert "/api/rest/v1/users/345" in calls
    with factory() as db:
        assert db.scalar(select(ExternalCreateOperation)).operation_state == State.BOUND


@pytest.mark.parametrize("commit_phase", ["claim", "receipt"])
def test_any709_qa_uncertain_commit_preserves_active_claim_or_saved_receipt(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    commit_phase: str,
) -> None:
    from app.composition import billing

    factory = postgres_session_factory
    seed(factory)
    config = step1_settings(preflight_total_timeout_seconds=0.6, preflight_cleanup_timeout_seconds=0.025)
    posts = []
    target = "claim_customer_send" if commit_phase == "claim" else "record_customer_receipt"
    original = getattr(billing, target)

    def uncertain(*args: object, **kwargs: object) -> object:
        original(*args, **kwargs)
        raise RuntimeError("simulated lost commit acknowledgement")

    monkeypatch.setattr(billing, target, uncertain)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth"):
            data = {"token": "private", "expires_in": 600}
        elif request.method == "POST":
            posts.append(json.loads(request.content))
            return httpx.Response(201, json={"code": 201, "response": {"user_id": 345}})
        elif request.url.path.endswith("/users"):
            data = []
        else:
            data = {"user_id": 345, "outer_id": posts[0]["outer_id"]}
        return httpx.Response(200, json={"code": 200, "response": data})

    async def scenario() -> None:
        async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
            with pytest.raises(RuntimeError, match="simulated lost commit acknowledgement"):
                await bootstrap_account(sources, config, factory=factory, token=TOKEN)
            monkeypatch.setattr(billing, target, original)
            if commit_phase == "claim":
                with pytest.raises(BillingRefused):
                    await bootstrap_account(sources, config, factory=factory, token=TOKEN)
            else:
                assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential

    asyncio.run(scenario())
    assert len(posts) == (0 if commit_phase == "claim" else 1)
