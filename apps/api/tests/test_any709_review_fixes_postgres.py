"""Review regressions: synthetic LBX only, disposable PostgreSQL, no real payments."""

from __future__ import annotations

import asyncio
import copy
import json
import time
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import advance_purchase, confirm_purchase, recover_financial, review_purchase
from app.composition.sources import source_resources
from app.domains.catalog.link_publication import publish_product_link
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import LegalSelection, PurchaseMeaning, PurchaseRefused
from app.models import BillingWorkItem, ExternalCreateOperation, ExternalCreateOperationKind as Kind
from app.models import ExternalCreateOperationState as State, PurchaseIntentState as IntentState
from apps.api.tests.support.any709_step1 import step1_settings, link_document, link_selection
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.kernel import manifest_fixture, resign
from apps.api.tests.test_any709_step3_postgres import setup_purchase, accept, TOKEN

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


@pytest.mark.parametrize("path,kind", [("/agreements", Kind.AGREEMENT), ("/subscriptions", Kind.SUBSCRIPTION)])
async def test_proven_not_sent_resumes_original_operation_only_on_explicit_advance(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    kind: Kind,
) -> None:
    from app.composition import purchases as purchase_composition

    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    failures: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith(path) and not failures:
            failures.append(request)
            raise httpx.ConnectError("synthetic pre-send failure", request=request)
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        first = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        original = next(op for op in first.operations if op.kind == kind)
        assert original.state == State.PROVEN_NOT_SENT and first.held
        assert original.last_failure_code == "lbx_create_not_sent"
        assert len(failures) == 1 and transport.creates(path) == 0
        with factory() as db:
            op = db.get(ExternalCreateOperation, original.id)
            evidence = copy.deepcopy(op.recovery_hint_document)
            since = op.unknown_since
            work = db.scalar(select(BillingWorkItem).where(BillingWorkItem.coalescing_key == str(original.id)))
            work_id = work.work_item_id
            assert work.work_state == "done" and work.attempt_count == 1
        recovered = await recover_financial(
            sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
        assert next(op for op in recovered.operations if op.kind == kind).state == State.PROVEN_NOT_SENT
        assert transport.creates(path) == 0
        # A GET failure or the original deadline cannot erase positive no-send evidence.
        financial.financial_pending(factory, first, original)
        monkeypatch.setattr(financial, "utc_now", lambda: datetime.now(UTC) + timedelta(days=1))
        monkeypatch.setattr(purchase_composition, "current_billing_date", lambda: datetime(2026, 10, 28).date())
        # The next request must preserve the original immutable request across midnight.
        second = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert second.state == IntentState.LINKED and second.held
        later = next(op for op in second.operations if op.kind == kind)
        assert later.id == original.id and later.key == original.key and later.deadline == original.deadline
        assert transport.creates(path) == 1
        financial.proven_not_sent(factory, first, replace(original, may_send=True))
        assert (
            next(
                op for op in service.read_purchase(factory, purchase.user_id, purchase.id).operations if op.kind == kind
            ).state
            == State.BOUND
        )
        with factory() as db:
            op = db.get(ExternalCreateOperation, original.id)
            assert op.recovery_hint_document == evidence and op.unknown_since == since
            work = db.scalar(select(BillingWorkItem).where(BillingWorkItem.coalescing_key == str(original.id)))
            assert work.work_item_id == work_id and work.attempt_count == 2


async def test_concurrent_resume_claims_one_post_and_preserves_database_guards(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    failures: list[bool] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/agreements") and not failures:
            failures.append(True)
            raise httpx.ConnectError("synthetic no-send", request=request)
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        first = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        original = next(op for op in first.operations if op.kind == Kind.AGREEMENT)
        assert original.state == State.PROVEN_NOT_SENT
        for mutation in (
            "operation_state = 'pending'",
            "unknown_since = NULL",
            "recovery_hint_document = '{}'::jsonb",
            "unknown_recovery_deadline_at = unknown_recovery_deadline_at + interval '1 hour'",
        ):
            with factory() as db:
                with pytest.raises(DatabaseError):
                    db.execute(
                        text("UPDATE external_create_operations SET " + mutation + " WHERE create_operation_id = :id"),
                        {"id": original.id},
                    )
                    db.commit()
        # A global pool count includes the other request's short transaction;
        # sequential scenarios above retain the no-DB-resource-during-HTTP guard.
        transport.pool = None
        results = await asyncio.gather(
            *(
                advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
                for _ in range(2)
            ),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                assert isinstance(result, PurchaseRefused) and result.code == "purchase_pending"
        result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.state == IntentState.LINKED
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


async def test_changed_terms_after_no_send_can_release_without_external_effect(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/agreements"):
            raise httpx.ConnectError("synthetic no-send", request=request)
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        transport.change_price()
        result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.state == IntentState.FAILED_BEFORE_EXTERNAL_EFFECT and not result.held
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


def add_second_period(transport: PurchaseTransport) -> dict:
    transport.period_lengths[9902] = 12
    periods = json.loads(transport.offer.bodies["periods"])
    second = {**periods["response"][0], "period_id": 9902, "tariff_period_id": 9903, "period_length": 12}
    periods["response"].append(second)
    transport.offer.bodies["periods"] = json.dumps(periods).encode()
    prices = json.loads(transport.offer.bodies["prices"])
    prices["response"].extend(
        [
            {**row, "period_id": 9902, "price_id": row["price_id"] + 10000, "period_length": 12}
            for row in prices["response"]
            if row["period_id"] == 901
        ]
    )
    transport.offer.bodies["prices"] = json.dumps(prices).encode()
    services = json.loads(transport.offer.bodies["services"])
    for service_row in services["response"]:
        service_row["discounts"].append({"period_id": 9902, "discounts": []})
        service_row["prices"].extend(
            [{**row, "period_id": 9902} for row in service_row.get("prices", []) if row["period_id"] == 901]
        )
    transport.offer.bodies["services"] = json.dumps(services).encode()
    manifest = manifest_fixture()
    for product in manifest["products"]:
        if product["product_id"] == "brief_decoder":
            product["enabled"] = True
    resign(manifest)
    return manifest


@pytest.mark.parametrize("already_linked", [False, True])
@pytest.mark.parametrize("inventory", ["proven", "unknown", "wrong_seller", "changed_terms"])
async def test_same_tariff_products_use_product_scope_and_point_proven_history(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    already_linked: bool,
    inventory: str,
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    manifest = add_second_period(transport)
    publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(product_id="brief_decoder", period_id=9902)),
        expected_previous_revision=0,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    )
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(lambda request: httpx.Response(200, json=manifest)),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        first = await accept(sources, factory, key="product-a")
        if already_linked:
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=first.id)
        link, offer, docs = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="brief_decoder"
        )
        meaning = PurchaseMeaning(
            product_id="brief_decoder",
            revision_id=link.mapping_revision_id,
            expected_fingerprint=offer.fingerprint,
            documents=tuple(
                LegalSelection(
                    document_version_id=doc.document_version_id, acceptance_text_hash=doc.acceptance_text_hash
                )
                for doc in docs
            ),
        )
        second = await confirm_purchase(sources, config, factory=factory, token=TOKEN, key="product-b", meaning=meaning)
        if not already_linked:
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=first.id)
        if inventory == "unknown":
            transport.subscriptions.append({**transport.subscriptions[0], "subscription_id": 999})
        elif inventory == "wrong_seller":
            transport.agreements[0]["organization_id"] = 999
        elif inventory == "changed_terms":
            transport.subscriptions[0]["period_length"] = 99
        try:
            result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=second.id)
        except PurchaseRefused as error:
            assert inventory == "unknown" and error.code == "purchase_existing_subscription_review"
            result = service.read_purchase(factory, second.user_id, second.id)
        if inventory == "proven":
            assert result.state == IntentState.LINKED and result.held
            assert transport.creates("/users") == 1
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 2
            assert {row["period_id"] for row in transport.subscriptions} == {901, 9902}
            assert len({row["agreement_id"] for row in transport.subscriptions}) == 2
        else:
            assert result.state == IntentState.MANUAL_REVIEW and result.held
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
