"""Own in-flight subscription preparation must not permanently block a sibling."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import purchases
from app.composition.sources import source_resources
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.link_publication import publish_product_link
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import (
    FinancialOperation,
    LegalSelection,
    Purchase,
    PurchaseMeaning,
    PurchaseRefused,
    PreparedSubscriptionObservation,
)
from app.infrastructure.queries import purchases as queries
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.financial import NewSubscription
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from app.models import PurchaseIntent
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
            client: LbxServerClient,
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
            return await recover_one(client, purchase, operation, customer, factory, budget=budget)

        if checkpoint == "before_receipt":
            monkeypatch.setattr(client, "create_subscription", pause_before_receipt)
        else:
            monkeypatch.setattr(purchases, "_recover_one", pause_before_binding)
        task = asyncio.create_task(
            purchases.advance_purchase(sources, configuration, factory=factory, token=TOKEN, purchase_id=first.id)
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            if conflict == "seller":
                transport.agreements[0]["organization_id"] = 999
            elif conflict == "terms":
                transport.subscriptions[0]["period_length"] = 99
            elif conflict == "receipt":
                transport.subscriptions[0]["subscription_id"] = 999
            expected = (
                "purchase_existing_subscription_review" if conflict == "receipt" else "purchase_inventory_incomplete"
            )
            if conflict in {"seller", "terms"}:
                await purchases.advance_purchase(
                    sources, configuration, factory=factory, token=TOKEN, purchase_id=second.id
                )
            else:
                with pytest.raises(PurchaseRefused, match=expected):
                    await purchases.advance_purchase(
                        sources, configuration, factory=factory, token=TOKEN, purchase_id=second.id
                    )
            pending = service.read_purchase(factory, second.user_id, second.id)
            assert pending.held and pending.accepted == second.accepted
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
            if conflict:
                assert pending.state.value == "manual_review"
                assert all(
                    operation.state == State.MANUAL_REVIEW or operation.state == State.PENDING
                    for operation in pending.operations
                )
            else:
                assert pending.state.value == "awaiting_external_result"
                assert all(operation.state == State.PENDING for operation in pending.operations)
            release.set()
            completed = await task
            if not conflict:
                assert completed.state.value == "linked"
            resumed = await purchases.advance_purchase(
                sources, configuration, factory=factory, token=TOKEN, purchase_id=second.id
            )
            assert resumed.id == second.id and resumed.accepted == second.accepted and resumed.held
            assert [operation.id for operation in resumed.operations] == [
                operation.id for operation in second.operations
            ]
            assert resumed.state.value == ("manual_review" if conflict else "linked")
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == (1 if conflict else 2)
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
        bind_ready, allow_bind = threading.Event(), threading.Event()
        lookup_ready, allow_snapshot = threading.Event(), threading.Event()
        writer_ready = threading.Event()
        writer_pid: list[int] = []
        original_bind, original_lookup, original_locked = (
            financial.bind_financial,
            queries.agreement_purchase,
            financial._locked,
        )

        def pause_bind(
            factory: SessionFactory,
            purchase: Purchase,
            operation: FinancialOperation,
            provider_id: int,
            *,
            observation: PreparedSubscriptionObservation | None = None,
            work_claim: WorkClaim | None = None,
        ) -> None:
            if purchase.id == first.id and operation.kind == Kind.SUBSCRIPTION:
                bind_ready.set()
                assert allow_bind.wait(10)
            original_bind(factory, purchase, operation, provider_id, observation=observation, work_claim=work_claim)

        def pause_lookup(
            db: Session, *, user_id: UUID, customer_id: UUID, account_id: str, agreement_id: str
        ) -> PurchaseIntent | None:
            row = original_lookup(
                db, user_id=user_id, customer_id=customer_id, account_id=account_id, agreement_id=agreement_id
            )
            if row is not None and row.purchase_intent_id == first.id:
                lookup_ready.set()
                assert allow_snapshot.wait(10)
            return row

        def observe_writer(db: Session, purchase: Purchase) -> PurchaseIntent:
            if purchase.id == first.id and lookup_ready.is_set():
                writer_pid.append(db.execute(text("SELECT pg_backend_pid()")).scalar_one())
                writer_ready.set()
            return original_locked(db, purchase)

        def writer_waiting() -> bool:
            with migrated_database.connect() as db:
                return bool(db.scalar(text("SELECT cardinality(pg_blocking_pids(:pid)) > 0"), {"pid": writer_pid[0]}))

        monkeypatch.setattr(financial, "bind_financial", pause_bind)
        monkeypatch.setattr(queries, "agreement_purchase", pause_lookup)
        monkeypatch.setattr(financial, "_locked", observe_writer)
        task_a = asyncio.create_task(
            purchases.advance_purchase(sources, configuration, factory=factory, token=TOKEN, purchase_id=first.id)
        )
        task_b: asyncio.Task[Purchase] | None = None
        try:
            assert await asyncio.to_thread(bind_ready.wait, 10)
            task_b = asyncio.create_task(
                purchases.advance_purchase(sources, configuration, factory=factory, token=TOKEN, purchase_id=second.id)
            )
            assert await asyncio.to_thread(lookup_ready.wait, 10)
            allow_bind.set()
            assert await asyncio.to_thread(writer_ready.wait, 10)
            # Let the real writer either finish (the old bug) or wait for the
            # reader. Observe PostgreSQL's wait condition, not a timing delay.
            async with asyncio.timeout(10):
                while not task_a.done() and not await asyncio.to_thread(writer_waiting):
                    await asyncio.sleep(0)
            allow_snapshot.set()
            with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
                await task_b
            assert (await task_a).state.value == "linked"
            pending = service.read_purchase(factory, second.user_id, second.id)
            assert pending.state.value == "awaiting_external_result" and pending.held
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
            resumed = await purchases.advance_purchase(
                sources, configuration, factory=factory, token=TOKEN, purchase_id=second.id
            )
            assert resumed.state.value == "linked" and resumed.id == second.id
            assert resumed.accepted == second.accepted and resumed.held
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 2
        finally:
            allow_bind.set()
            allow_snapshot.set()
            for task in (task_a, task_b):
                if task is not None and not task.done():
                    task.cancel()
            await asyncio.gather(*(task for task in (task_a, task_b) if task is not None), return_exceptions=True)
