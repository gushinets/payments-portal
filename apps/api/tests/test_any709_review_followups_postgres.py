"""Review regressions using disposable PostgreSQL and synthetic source HTTP."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import purchases
from app.composition.billing import bootstrap_account
from app.composition.sources import source_resources
from app.core.errors import AppError
from app.domains.billing import customers
from app.domains.billing.contracts import BillingRefused
from app.domains.catalog.commercial_offer import SelectedOfferRefused
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase, PurchaseRefused
from app.integrations.lbx.errors import LbxCreateNotSent
from app.models import (
    ExternalBillingCustomer,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.kernel import manifest_fixture, resign
from apps.api.tests.test_any709_step3_postgres import TOKEN, accept, setup_purchase

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def billing_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


@pytest.mark.parametrize("change", ["archive", "disabled", "unsupported"])
@pytest.mark.parametrize("agreement_bound", [False, True])
async def test_unsellable_offer_releases_only_financially_unsent_purchase(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
    agreement_bound: bool,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    disabled = False

    def kernel(request: httpx.Request) -> httpx.Response:
        payload = manifest_fixture()
        if disabled:
            for product in payload["products"]:
                product["enabled"] = False
            resign(payload)
        return httpx.Response(200, json=payload)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(kernel), lbx_transport=httpx.MockTransport(transport.respond)
    ) as sources:
        purchase = await accept(sources, factory)
        if agreement_bound:

            async def not_sent(*args: object, **kwargs: object) -> int:
                raise LbxCreateNotSent()

            monkeypatch.setattr(sources.require_lbx(), "create_subscription", not_sent)
            await purchases.advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        if change == "archive":
            transport.offer.replace("tariff", '"archive":0', '"archive":1')
        elif change == "disabled":
            disabled = True
        else:
            transport.offer.replace("services", '"periodic_service":1', '"periodic_service":0')
        result = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        assert result.accepted == purchase.accepted
        assert result.held is agreement_bound
        assert transport.creates("/agreements") == int(agreement_bound)
        assert transport.creates("/subscriptions") == 0
        if agreement_bound:
            assert result.state.value == "manual_review"
            with pytest.raises(PurchaseRefused, match="purchase_scope_occupied"):
                await purchases.confirm_purchase(
                    sources,
                    config,
                    factory=factory,
                    token=TOKEN,
                    key="another-purchase",
                    meaning=purchase.accepted.meaning,
                )
        else:
            assert result.state.value == "failed_before_external_effect" and result.reason == "terms_changed"
            disabled = False
            if change == "archive":
                transport.offer.replace("tariff", '"archive":1', '"archive":0')
            elif change == "unsupported":
                transport.offer.replace("services", '"periodic_service":0', '"periodic_service":1')
            replacement = await accept(sources, factory, key="another-purchase")
            assert replacement.id != purchase.id and replacement.held


@pytest.mark.parametrize("failure", ["incomplete", "unavailable"])
async def test_temporary_offer_failure_retains_same_unsent_purchase(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], failure: str
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    unavailable = False

    def respond(request: httpx.Request) -> httpx.Response:
        if unavailable and "/tariffs/" in request.url.path:
            return httpx.Response(503, json={"code": 503, "response": {"error": "Unavailable"}})
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        if failure == "incomplete":
            transport.offer.replace("tariff", '"archive":0', '"archive":null')
        else:
            unavailable = True
        with pytest.raises(SelectedOfferRefused):
            await purchases.advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        retained = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert retained.held and all(op.state == State.PENDING for op in retained.operations)
        assert not transport.creates("/agreements") and not transport.creates("/subscriptions")
        unavailable = False
        if failure == "incomplete":
            transport.offer.replace("tariff", '"archive":null', '"archive":0')
        resumed = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        assert resumed.id == purchase.id and resumed.state.value == "linked"


@pytest.mark.parametrize("other_open", ["healthy", "transient", "conflict"])
async def test_concurrent_widget_opens_ignore_diagnostics_but_reject_real_conflict(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    other_open: str,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    transient = False

    def respond(request: httpx.Request) -> httpx.Response:
        if transient and request.method == "GET" and request.url.path.endswith("/agreements/456"):
            transport.requests.append(request)
            raise httpx.ReadTimeout("Synthetic temporary read timeout", request=request)
        return transport.respond(request)

    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(respond),
    ) as sources:
        purchase = await accept(sources, factory)
        prepared = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        entered, release = asyncio.Event(), asyncio.Event()
        original = purchases.verify_payment_purchase

        async def paused(*args: object, **kwargs: object) -> Purchase:
            result = await original(*args, **kwargs)
            if asyncio.current_task().get_name() == "opening-a":
                entered.set()
                await release.wait()
            return result

        monkeypatch.setattr(purchases, "verify_payment_purchase", paused)
        first = asyncio.create_task(
            bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id), name="opening-a"
        )
        try:
            await asyncio.wait_for(entered.wait(), 10)
            if other_open == "conflict":
                transport.agreements[0]["organization_id"] = 99
                with pytest.raises(AppError):
                    await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
                release.set()
                with pytest.raises(AppError):
                    await first
            else:
                if other_open == "transient":
                    transient = True
                    with pytest.raises(AppError, match="purchase_not_prepared"):
                        await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
                    failed = service.read_purchase(factory, purchase.user_id, purchase.id)
                    assert (
                        next(op for op in failed.operations if op.kind == Kind.SUBSCRIPTION).last_failure_code
                        is not None
                    )
                    assert [(op.state, op.bound_id, op.fence) for op in failed.operations] == [
                        (op.state, op.bound_id, op.fence) for op in prepared.operations
                    ]
                else:
                    second = await bootstrap_account(
                        sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
                    )
                    assert second.purchase_id == purchase.id
                release.set()
                assert (await first).purchase_id == purchase.id
                retained = service.read_purchase(factory, purchase.user_id, purchase.id)
                if other_open == "healthy":
                    assert retained.operations == prepared.operations
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
        finally:
            release.set()
            if not first.done():
                first.cancel()
            await asyncio.gather(first, return_exceptions=True)


@pytest.mark.parametrize("receipt", [False, True])
async def test_customer_row_contention_is_a_bounded_busy_refusal(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], receipt: bool
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    setup_purchase(factory)
    current = customers.reserve_customer(factory, config, TOKEN)
    with factory() as blocker, ThreadPoolExecutor(max_workers=1) as workers:
        blocker.execute(
            select(ExternalBillingCustomer)
            .where(ExternalBillingCustomer.customer_id == current.customer_id)
            .with_for_update()
        ).scalar_one()
        future = (
            workers.submit(customers.record_customer_receipt, factory, current, 345)
            if receipt
            else workers.submit(customers.finish_customer_attempt, factory, current)
        )
        with pytest.raises(BillingRefused) as caught:
            future.result(timeout=5)
        assert caught.value.code == "billing_busy" and caught.value.status == 503
        blocker.rollback()
    customers.finish_customer_attempt(factory, current)
