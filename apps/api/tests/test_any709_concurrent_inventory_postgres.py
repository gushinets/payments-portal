"""Own in-flight subscription preparation must not permanently block a sibling."""

from __future__ import annotations

from copy import deepcopy

import asyncio
import time
from datetime import UTC, datetime
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import purchases
from app.composition.sources import SourceResources, source_resources
from app.core.settings import Settings
from app.domains.billing.contracts import CustomerOpen
from app.domains.catalog.link_publication import publish_product_link
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.domains.purchases.contracts import (
    FinancialOperation,
    LegalSelection,
    Purchase,
    PurchaseMeaning,
    PurchaseRefused,
)
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.financial import NewSubscription
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from app.models import ExternalCreateOperation
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.test_any709_review_fixes_postgres import add_second_period
from apps.api.tests.test_any709_step3_postgres import TOKEN, accept, setup_purchase

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    ("checkpoint", "conflict"),
    [
        ("before_receipt", None),
        ("before_binding", None),
        ("unknown", None),
        ("before_binding", "seller"),
        ("before_binding", "terms"),
        ("before_binding", "receipt"),
    ],
)
async def test_sibling_inventory_waits_for_original_preparation_without_hiding_conflicts(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    checkpoint: str,
    conflict: str | None,
) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    factory, configuration = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    manifest = add_second_period(transport)
    publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(product_id="brief_decoder", period_id=9902)),
        expected_previous_revision=0,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=configuration.lbx_provider_origin,
    )
    if checkpoint == "unknown":
        transport.fail_create = "/subscriptions"
    async with source_resources(
        configuration,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest)),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        first = await accept(sources, factory, key="product-a")
        link, offer, documents = await purchases.review_purchase(
            sources, configuration, factory=factory, token=TOKEN, product_id="brief_decoder"
        )
        second = await purchases.confirm_purchase(
            sources,
            configuration,
            factory=factory,
            token=TOKEN,
            key="product-b",
            meaning=PurchaseMeaning(
                product_id="brief_decoder",
                revision_id=link.mapping_revision_id,
                expected_fingerprint=offer.fingerprint,
                documents=tuple(
                    LegalSelection(
                        document_version_id=doc.document_version_id, acceptance_text_hash=doc.acceptance_text_hash
                    )
                    for doc in documents
                ),
            ),
        )
        entered, release = asyncio.Event(), asyncio.Event()
        client = sources.require_lbx()
        create_subscription, recover_one = client.create_subscription, purchases._recover_one

        async def pause_before_receipt(command: NewSubscription, *, budget: PreflightBudget) -> int:
            provider_id = await create_subscription(command, budget=budget)
            entered.set()
            await release.wait()
            return provider_id

        async def pause_before_binding(
            resources: SourceResources,
            settings: Settings,
            purchase: Purchase,
            operation: FinancialOperation,
            customer: CustomerOpen,
            factory: SessionFactory,
            *,
            budget: PreflightBudget,
        ) -> bool:
            if purchase.id == first.id and operation.kind == Kind.SUBSCRIPTION:
                entered.set()
                await release.wait()
            return await recover_one(resources, settings, purchase, operation, customer, factory, budget=budget)

        if checkpoint == "before_receipt":
            monkeypatch.setattr(client, "create_subscription", pause_before_receipt)
        else:
            monkeypatch.setattr(purchases, "_recover_one", pause_before_binding)
        task = asyncio.create_task(
            purchases.advance_purchase(sources, configuration, factory=factory, token=TOKEN, purchase_id=first.id)
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            saved_agreement = deepcopy(transport.agreements[0])
            saved_subscription = deepcopy(transport.subscriptions[0])
            if conflict == "seller":
                transport.agreements[0]["organization_id"] = 999
            elif conflict == "terms":
                transport.subscriptions[0]["period_length"] = 99
            elif conflict == "receipt":
                transport.subscriptions[0]["subscription_id"] = 999
            with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
                await purchases.advance_purchase(
                    sources, configuration, factory=factory, token=TOKEN, purchase_id=second.id
                )
            pending = service.read_purchase(factory, second.user_id, second.id)
            assert pending.held and pending.accepted == second.accepted
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
            assert pending.state.value == "awaiting_external_result"
            assert all(operation.state == State.PENDING for operation in pending.operations)
            assert all(op.fence != prior.fence for op, prior in zip(pending.operations, second.operations))
            # Correct the original candidate; the sibling never acquired a
            # permanent financial review and can explicitly resume after binding.
            transport.agreements[0] = saved_agreement
            transport.subscriptions[0] = saved_subscription
            release.set()
            completed = await task
            assert completed.state.value == "linked"
            resumed = await purchases.advance_purchase(
                sources, configuration, factory=factory, token=TOKEN, purchase_id=second.id
            )
            assert resumed.id == second.id and resumed.accepted == second.accepted and resumed.held
            assert [operation.id for operation in resumed.operations] == [
                operation.id for operation in second.operations
            ]
            assert resumed.state.value == "linked"
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 2
        finally:
            release.set()
            if not task.done():
                task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_sibling_completion_between_inventory_reads_keeps_purchase_retryable(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    factory, configuration = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    manifest = add_second_period(transport)
    publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(product_id="brief_decoder", period_id=9902)),
        expected_previous_revision=0,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=configuration.lbx_provider_origin,
    )
    async with source_resources(
        configuration,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest)),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        first = await accept(sources, factory, key="product-a")
        link, offer, documents = await purchases.review_purchase(
            sources, configuration, factory=factory, token=TOKEN, product_id="brief_decoder"
        )
        second = await purchases.confirm_purchase(
            sources,
            configuration,
            factory=factory,
            token=TOKEN,
            key="product-b",
            meaning=PurchaseMeaning(
                product_id="brief_decoder",
                revision_id=link.mapping_revision_id,
                expected_fingerprint=offer.fingerprint,
                documents=tuple(
                    LegalSelection(
                        document_version_id=doc.document_version_id, acceptance_text_hash=doc.acceptance_text_hash
                    )
                    for doc in documents
                ),
            ),
        )
        first = await purchases.advance_purchase(
            sources, configuration, factory=factory, token=TOKEN, purchase_id=first.id
        )
        client = sources.require_lbx()
        discover = client.discover_subscriptions
        calls = 0

        async def changed_during_reads(*, user_id: int, budget: PreflightBudget, **kwargs: object) -> tuple:
            nonlocal calls
            rows = await discover(user_id=user_id, budget=budget, **kwargs)
            calls += 1
            if calls == 2:
                with factory() as db:
                    operation = next(op for op in first.operations if op.kind == Kind.SUBSCRIPTION)
                    db.get(ExternalCreateOperation, operation.id).send_fence = uuid4()
                    db.commit()
            return rows

        monkeypatch.setattr(client, "discover_subscriptions", changed_during_reads)
        with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
            await purchases.advance_purchase(
                sources, configuration, factory=factory, token=TOKEN, purchase_id=second.id
            )
        pending = service.read_purchase(factory, second.user_id, second.id)
        assert pending.state != "manual_review" and pending.held
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
        monkeypatch.setattr(client, "discover_subscriptions", discover)
        resumed = await purchases.advance_purchase(
            sources, configuration, factory=factory, token=TOKEN, purchase_id=second.id
        )
        assert resumed.state.value == "linked" and resumed.id == second.id
        assert resumed.accepted == second.accepted and resumed.held
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 2
