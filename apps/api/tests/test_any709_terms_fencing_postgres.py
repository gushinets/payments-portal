"""Terms decisions must not demote concurrent financial progress."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import purchases
from app.composition.billing import bootstrap_account
from app.composition.sources import source_resources
from app.core.settings import Settings
from app.domains.catalog.product_link import CurrentOffer, ProductLinkRequest
from app.domains.purchases import financial, service
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.models import ExternalCreateOperation, ManualReviewCase
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from app.models import PurchaseIntentState as Intent
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN, accept, setup_purchase

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


@pytest.mark.parametrize("stage", [Kind.AGREEMENT, Kind.SUBSCRIPTION])
async def test_stale_price_read_preserves_concurrently_linked_purchase(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    stage: Kind,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    reject_subscription = stage == Kind.SUBSCRIPTION

    def respond(request: httpx.Request) -> httpx.Response:
        if reject_subscription and request.method == "POST" and request.url.path.endswith("/subscriptions"):
            raise httpx.ConnectError("synthetic no-send", request=request)
        return transport.respond(request)

    entered, release = asyncio.Event(), asyncio.Event()
    original_read = purchases.read_current_offer

    async def delayed_read(
        client: LbxServerClient, *, selection: ProductLinkRequest, configuration: Settings, budget: PreflightBudget
    ) -> CurrentOffer:
        if asyncio.current_task().get_name() == "stale-terms-read" and not entered.is_set():
            entered.set()
            await release.wait()
        return await original_read(client, selection=selection, configuration=configuration, budget=budget)

    monkeypatch.setattr(purchases, "read_current_offer", delayed_read)
    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        if reject_subscription:
            unsent = await purchases.advance_purchase(
                sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
            )
            assert next(op for op in unsent.operations if op.kind == stage).state == State.PROVEN_NOT_SENT
            reject_subscription = False
        stale = asyncio.create_task(
            purchases.advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id),
            name="stale-terms-read",
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            completed = await purchases.advance_purchase(
                sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
            )
            assert completed.state == Intent.LINKED
            transport.change_price()
            assert transport.subscriptions[0]["services"][0]["price"] == 100
            before = await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
            assert before.purchase_id == purchase.id
            proven = service.read_purchase(factory, purchase.user_id, purchase.id)
            release.set()
            result = await stale
            assert result == proven
            assert result.state == Intent.LINKED and result.held
            assert result.accepted == purchase.accepted
            after = await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
            assert after.purchase_id == purchase.id
            assert [transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")] == [1, 1, 1]
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
        finally:
            release.set()
            if not stale.done():
                stale.cancel()
                await asyncio.gather(stale, return_exceptions=True)


@pytest.mark.parametrize("stage", [Kind.AGREEMENT, Kind.SUBSCRIPTION])
async def test_current_unsent_terms_change_still_refuses_financial_send(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], stage: Kind
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/subscriptions"):
            raise httpx.ConnectError("synthetic no-send", request=request)
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        if stage == Kind.SUBSCRIPTION:
            unsent = await purchases.advance_purchase(
                sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
            )
            assert next(op for op in unsent.operations if op.kind == stage).state == State.PROVEN_NOT_SENT
        transport.change_price()
        result = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        assert result.state == (
            Intent.MANUAL_REVIEW if stage == Kind.SUBSCRIPTION else Intent.FAILED_BEFORE_EXTERNAL_EFFECT
        )
        assert result.held == (stage == Kind.SUBSCRIPTION)
        assert result.accepted == purchase.accepted
        assert transport.creates("/subscriptions") == 0
        assert transport.creates("/agreements") == (1 if stage == Kind.SUBSCRIPTION else 0)


async def test_terms_decision_checks_fence_even_when_operation_returns_to_same_state(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/subscriptions"):
            raise httpx.ConnectError("synthetic no-send", request=request)
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        stale = await purchases.advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    operation = next(op for op in stale.operations if op.kind == Kind.SUBSCRIPTION)
    assert operation.state == State.PROVEN_NOT_SENT
    with factory() as db:
        request = db.get(ExternalCreateOperation, operation.id).recovery_hint_document["request"]
    claimed = financial.claim_financial(factory, stale, operation, request, configuration=config, token=TOKEN)
    assert claimed.may_send
    financial.proven_not_sent(factory, stale, claimed)
    current = service.read_purchase(factory, purchase.user_id, purchase.id)
    new_operation = next(op for op in current.operations if op.kind == Kind.SUBSCRIPTION)
    assert current.state == stale.state
    assert new_operation.state == operation.state and new_operation.fence != operation.fence
    financial.changed_unsent_terms(factory, stale)
    assert service.read_purchase(factory, purchase.user_id, purchase.id) == current
    # A current decision still protects the accepted terms after agreement preparation.
    financial.changed_unsent_terms(factory, current)
    assert service.read_purchase(factory, purchase.user_id, purchase.id).state == Intent.MANUAL_REVIEW
