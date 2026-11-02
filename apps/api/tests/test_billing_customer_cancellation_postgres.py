"""Caller cancellation and owned deadlines with actual HTTP cleanup and PostgreSQL."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.purchases import advance_purchase
from app.composition.sources import source_resources
from app.domains.billing.contracts import BillingAccountFailure
from app.infrastructure.preflight import PreflightDeadlineExceeded
from app.models import BillingWorkItem, ExternalCreateOperation
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State, PurchaseIntentState
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import setup_purchase, accept, TOKEN

pytestmark = pytest.mark.postgres


@pytest.mark.parametrize("entrypoint", ["widget", "advance"])
@pytest.mark.parametrize("stage", ["GET", "POST"])
@pytest.mark.parametrize("caller_cancel", [True, False])
def test_customer_cleanup_preserves_caller_cancellation_and_normalizes_owned_deadline(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    caplog: pytest.LogCaptureFixture,
    entrypoint: str,
    stage: str,
    caller_cancel: bool,
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    short = step1_settings(preflight_total_timeout_seconds=1.5, preflight_cleanup_timeout_seconds=0.4)

    async def scenario() -> None:
        closing = asyncio.Event()
        finish = asyncio.Event()
        closed = asyncio.Event()
        stall = True

        class SlowClose(httpx.AsyncByteStream):
            async def __aiter__(self) -> AsyncIterator[bytes]:
                yield b'{"code":200,"response":[]}' if stage == "GET" else b'{"code":201,"response":{"user_id":345}}'

            async def aclose(self) -> None:
                closing.set()
                await finish.wait()
                closed.set()

        async def respond(request: httpx.Request) -> httpx.Response:
            nonlocal stall
            response = transport.respond(request)
            if stall and request.method == stage and request.url.path.endswith("/users"):
                stall = False
                return httpx.Response(
                    response.status_code, stream=SlowClose(), headers={"Content-Type": "application/json"}
                )
            return response

        async with source_resources(
            short, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
        ) as sources:
            purchase = await accept(sources, factory) if entrypoint == "advance" else None
            opening = asyncio.create_task(
                advance_purchase(sources, short, factory=factory, token=TOKEN, purchase_id=purchase.id)
                if purchase
                else bootstrap_account(sources, short, factory=factory, token=TOKEN)
            )
            try:
                await asyncio.wait_for(closing.wait(), timeout=3)
                if caller_cancel:
                    budget = next(iter(sources.billing._active))
                    await asyncio.sleep(max(0, budget.work_deadline - time.monotonic() - 0.2))
                    assert time.monotonic() < budget.work_deadline
                    opening.cancel("synthetic caller disconnect before deadline")
                    with pytest.raises(asyncio.CancelledError):
                        await opening
                    assert time.monotonic() >= budget.work_deadline
                    assert opening.cancelled()
                    assert not any(record.getMessage() == "billing_account_failed" for record in caplog.records)
                else:
                    with pytest.raises(BillingAccountFailure, match="billing_customer_pending") as caught:
                        await opening
                    assert caught.value.status == 409
                    assert not opening.cancelled()
                assert sources.billing.active_count == 1  # Protected close still owns its slot.
                assert transport.creates("/users") == (0 if stage == "GET" else 1)
                assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
                with factory() as db:
                    operation = db.scalar(
                        select(ExternalCreateOperation).where(ExternalCreateOperation.operation_kind == Kind.CUSTOMER)
                    )
                    assert operation.operation_state == (State.PENDING if stage == "GET" else State.POSSIBLE_SEND)
                    work = db.scalar(
                        select(BillingWorkItem).where(
                            BillingWorkItem.coalescing_key == str(operation.create_operation_id)
                        )
                    )
                    if stage == "POST":
                        assert work.lease_owner is not None and work.lease_expires_at is not None
                        assert operation.unknown_since is not None and operation.bound_external_object_id is None
                    else:
                        assert work is None
            finally:
                finish.set()
                await asyncio.wait_for(closed.wait(), timeout=2)
        assert sources.billing.active_count == 0
        # Another explicit opening uses the same operation; a completed synthetic
        # POST is recovered by point proof instead of dispatching a second CREATE.
        normal = step1_settings()
        async with source_resources(
            normal, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
        ) as sources:
            if purchase:
                resumed = await advance_purchase(sources, normal, factory=factory, token=TOKEN, purchase_id=purchase.id)
                assert resumed.state == PurchaseIntentState.LINKED and resumed.id == purchase.id
            else:
                assert (await bootstrap_account(sources, normal, factory=factory, token=TOKEN)).credential
        assert transport.creates("/users") == 1

    asyncio.run(scenario())


@pytest.mark.parametrize("entrypoint", ["widget", "advance"])
def test_deadline_after_customer_proof_keeps_its_original_classification(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
) -> None:
    from app.composition import purchases

    factory = postgres_session_factory
    transport = setup_purchase(factory)
    short = step1_settings(preflight_total_timeout_seconds=0.5, preflight_cleanup_timeout_seconds=0.1)

    async def wait_after_customer(*args: object, **kwargs: object) -> None:
        await asyncio.Event().wait()

    async def scenario() -> None:
        normal = step1_settings()
        async with source_resources(
            normal,
            kernel_transport=httpx.MockTransport(transport.kernel),
            lbx_transport=httpx.MockTransport(transport.respond),
        ) as sources:
            purchase = await accept(sources, factory)
            assert (await bootstrap_account(sources, normal, factory=factory, token=TOKEN)).credential
        if entrypoint == "advance":
            monkeypatch.setattr(purchases, "_prepare", wait_after_customer)
        async with source_resources(
            short,
            kernel_transport=httpx.MockTransport(transport.kernel),
            lbx_transport=httpx.MockTransport(transport.respond),
        ) as sources:
            if entrypoint == "widget":
                monkeypatch.setattr(sources.lbx, "client_user", wait_after_customer)
            with pytest.raises(PreflightDeadlineExceeded):
                if entrypoint == "advance":
                    await advance_purchase(sources, short, factory=factory, token=TOKEN, purchase_id=purchase.id)
                else:
                    await bootstrap_account(sources, short, factory=factory, token=TOKEN)
        assert transport.creates("/users") == 1
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0

    asyncio.run(scenario())
