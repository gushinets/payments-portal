"""Purchase transaction, fault and concurrency scenarios on disposable PostgreSQL.

Synthetic transports never reach live LBX.
"""

from __future__ import annotations

import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Event, get_ident
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from alembic.util.exc import CommandError
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.purchases import advance_purchase, confirm_purchase, recover_financial, review_purchase
from app.composition.sources import SourceResources, source_resources
from app.core.time import utc_now
from app.domains.billing import background_recovery, terminal_resolution as terminal
from app.domains.billing import late_purchase_reviews as late
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.operator_review import case_digest
from app.domains.billing.work_contracts import WorkLane
from app.domains.catalog.link_publication import publish_product_link
from app.domains.purchases.contracts import Purchase, PurchaseMeaning, LegalSelection, PurchaseRefused
from app.domains.purchases import financial, service
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.financial import NewAgreement
from app.jobs.billing import BillingWorker
from app.models import (
    BillingPurchaseScopeHold,
    BillingProductAccessScope,
    BillingWorkItem,
    BillingWorkState,
    BillingStateObservation,
    DocumentAcceptance,
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    LegalAcceptanceEvent,
    ManualReviewCase,
    PaidAccessState,
    PurchaseIntent,
    PurchaseIntentState as IntentState,
    PurchasedAllowance,
)
from app.integrations.lbx.customer import LbxUser
from apps.api.tests.factories.billing_operator import terminal_request
from apps.api.tests.factories.original_operation import advance_deadlines, original_proof
from apps.api.tests.factories.reconciliation import agreement_factory
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema
from apps.api.tests.test_any709_step2_postgres import seed, TOKEN

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
PRINCIPAL = "os-euid:1000"


@pytest.fixture(autouse=True)
def fixed_billing_calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def setup_purchase(factory: sessionmaker[Session]) -> PurchaseTransport:
    seed(factory)
    config = step1_settings()
    publish_product_link(
        factory,
        evaluation=link_document(),
        expected_previous_revision=0,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    )
    transport = PurchaseTransport()
    transport.pool = factory.kw["bind"].pool
    return transport


async def accept(sources: SourceResources, factory: sessionmaker[Session], *, key: str = "one-request") -> Purchase:
    config = step1_settings()
    link, offer, documents, _terms = await review_purchase(
        sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
    )
    meaning = PurchaseMeaning(
        product_id="proposal_ai",
        revision_id=link.mapping_revision_id,
        expected_fingerprint=offer.fingerprint,
        documents=tuple(
            LegalSelection(document_version_id=doc.document_version_id, acceptance_text_hash=doc.acceptance_text_hash)
            for doc in documents
        ),
    )
    return await confirm_purchase(sources, config, factory=factory, token=TOKEN, key=key, meaning=meaning)


async def test_any709_step3_complete_preparation_and_historical_manage(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        assert not [req for req in transport.requests if req.method == "POST"]
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(LegalAcceptanceEvent)) == 1
            assert db.scalar(select(func.count()).select_from(DocumentAcceptance)) >= 3
        result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.state == IntentState.LINKED and result.held
        # Current prices and hints change. Original effective terms still authorize Manage.
        transport.change_price()
        transport.subscriptions[0]["outer_id"] = "mutable-hint-changed"
        publish_product_link(
            factory,
            evaluation=link_document(selection=link_selection(tariff_id=702)),
            expected_previous_revision=1,
            deadline=time.monotonic() + 5,
            lock_timeout_seconds=1,
            provider_origin=config.lbx_provider_origin,
        )
        with factory() as db:
            db.execute(text("UPDATE document_versions SET is_active = false WHERE doc_type = 'offer'"))
            db.commit()
        before = len(transport.requests)
        widget = await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert widget.purchase_id == purchase.id and widget.agreement_reference
        assert widget.seller_reference == "21"
        assert {req.url.path for req in transport.requests[before:] if "/tariffs" in req.url.path} == {
            "/api/rest/v1/tariffs/701"
        }
        # Account view shares the exact same customer and customer CREATE use case.
        account = await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        assert account.purchase_id is None
        assert [transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")] == [1, 1, 1]
        same = await confirm_purchase(
            sources, config, factory=factory, token=TOKEN, key="one-request", meaning=purchase.accepted.meaning
        )
        assert same.id == purchase.id and same.accepted == purchase.accepted
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        assert sub.financial_access_status.value == "blocked"
        assert sub.projection_valid_until == sub.last_authoritative_read_at
        assert db.scalar(select(BillingProductAccessScope)).primary_subscription_id is None
        for model in (PaidAccessState, PurchasedAllowance):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 1
        assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 1


async def test_customer_point_proof_is_stale_when_its_fence_changes_before_first_send(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()

    def change_customer_fence() -> None:
        with factory() as db:
            operation = db.scalar(
                select(ExternalCreateOperation).where(ExternalCreateOperation.operation_kind == Kind.CUSTOMER)
            )
            assert operation is not None
            operation.send_fence = uuid4()
            db.commit()

    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        transport.before_offer = change_customer_fence

        with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)

        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


async def test_customer_point_proof_detects_source_key_drift_before_first_send(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)

    def change_original_key_at_source() -> None:
        assert transport.customer is not None
        transport.customer["outer_id"] = "changed-original-key"

    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        transport.before_offer = change_original_key_at_source
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)

        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
        with factory() as db:
            assert db.get(ExternalBillingCustomer, purchase.customer_id).binding_state == Binding.IDENTITY_CONFLICT


@pytest.mark.parametrize("path", ["/agreements/456", "/subscriptions/567"])
@pytest.mark.parametrize("failure", ["unavailable", "incomplete"])
async def test_any709_step3_linked_widget_retries_after_failed_point_proof(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    failure: str,
) -> None:
    from app.domains.billing import router as billing_routes
    from app.domains.purchases import router as purchase_routes
    from app.http.dependencies import get_session_factory
    from app.main import create_app

    factory = postgres_session_factory
    transport = setup_purchase(factory)
    configuration = step1_settings()
    monkeypatch.setattr(billing_routes, "settings", configuration)
    monkeypatch.setattr(purchase_routes, "settings", configuration)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: factory
    failing = False

    def respond(request: httpx.Request) -> httpx.Response:
        if failing and request.url.path == "/api/rest/v1" + path:
            if failure == "unavailable":
                transport.requests.append(request)
                return httpx.Response(503, json={"code": 503, "response": {"error": "Synthetic unavailable"}})
            body = transport.respond(request).json()
            body["response"].pop("organization_id" if path.startswith("/agreements/") else "services")
            return httpx.Response(200, json=body)
        return transport.respond(request)

    async with source_resources(
        configuration,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(respond),
    ) as sources:
        purchase = await accept(sources, factory)
        prepared = await advance_purchase(sources, configuration, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert prepared.state == IntentState.LINKED
        app.state.sources = sources
        body = {"purchase_intent_id": str(purchase.id)}
        before = len(transport.requests)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://portal.test",
            headers={"Authorization": "Bearer " + TOKEN},
        ) as client:
            original = await client.post("/api/billing/widget-bootstrap", json=body)
            assert original.status_code == 200
            target = original.json()["payment_target"]
            failing = True
            refused = await client.post("/api/billing/widget-bootstrap", json=body)
            assert refused.status_code == 409 and refused.json()["detail"]["code"] == "purchase_not_prepared"
            assert "credential" not in refused.json() and refused.headers["cache-control"] == "no-store"
            current = await client.get(f"/api/purchase-intents/{purchase.id}")
            assert current.status_code == 200 and current.json()["state"] == "linked"
            assert current.json()["scope_held"] is True and current.json()["paid_access_granted"] is False
            retained = service.read_purchase(factory, purchase.user_id, purchase.id)
            assert retained.accepted == purchase.accepted
            assert all(op.state == State.BOUND for op in retained.operations)
            assert [(op.id, op.bound_id) for op in retained.operations] == [
                (op.id, op.bound_id) for op in prepared.operations
            ]
            with factory() as db:
                observation = db.scalars(
                    select(BillingStateObservation)
                    .where(BillingStateObservation.evidence_schema_version == "subscription-reconciliation:v2")
                    .order_by(BillingStateObservation.observed_at.desc())
                ).first()
                assert observation.completeness_classification == "incomplete"
                work = db.scalar(
                    select(BillingWorkItem).where(BillingWorkItem.work_kind == "subscription_reconciliation")
                )
                assert work.work_state == "pending"
            failing = False
            retry_start = len(transport.requests)
            retried = await client.post("/api/billing/widget-bootstrap", json=body)
            assert retried.status_code == 200 and retried.headers["cache-control"] == "no-store"
            assert retried.json()["presentation"] == "payment" and retried.json()["disablePayments"] is False
            assert retried.json()["payment_target"] == target
            assert {"/api/rest/v1/agreements/456", "/api/rest/v1/subscriptions/567"}.issubset(
                {request.url.path for request in transport.requests[retry_start:]}
            )
        assert all(request.method == "GET" for request in transport.requests[before:])
        assert {request.url.path for request in transport.requests[before:] if "/tariffs" in request.url.path} == {
            "/api/rest/v1/tariffs/701"
        }
    assert [transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")] == [1, 1, 1]
    with factory() as db:
        assert db.scalar(select(BillingProductAccessScope)).primary_subscription_id is None
        for model in (PaidAccessState, PurchasedAllowance, ManualReviewCase):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        sub = db.scalar(select(ExternalSubscription))
        assert sub.financial_access_status.value == "blocked"
        assert sub.projection_valid_until == sub.last_authoritative_read_at


@pytest.mark.parametrize("lost_agreement_response", [False, True])
async def test_any709_step3_api_smoke_review_confirm_continue_payment(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    lost_agreement_response: bool,
) -> None:
    from app.domains.billing import router as billing_routes
    from app.domains.purchases import router as purchase_routes
    from app.http.dependencies import get_session_factory
    from app.main import create_app

    factory = postgres_session_factory
    transport = setup_purchase(factory)
    configuration = step1_settings()
    monkeypatch.setattr(billing_routes, "settings", configuration)
    monkeypatch.setattr(purchase_routes, "settings", configuration)
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: factory
    headers = {"Authorization": "Bearer " + TOKEN}
    async with source_resources(
        configuration,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        app.state.sources = sources
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://portal.test", headers=headers
        ) as client:
            account = await client.post("/api/billing/widget-bootstrap", json={})
            assert account.status_code == 200
            assert account.json()["presentation"] == "account" and account.json()["disablePayments"] is True
            assert account.json()["payment_target"] is None
            review = await client.post("/api/purchases/review", json={"product_id": "proposal_ai"})
            assert review.status_code == 200
            reviewed = review.json()
            assert reviewed["terms"]["recurring_amount"] == "100" and reviewed["legal_status"] == "draft"
            meaning = {
                "product_id": reviewed["product_id"],
                "revision_id": reviewed["revision_id"],
                "expected_fingerprint": reviewed["expected_fingerprint"],
                "documents": [
                    {
                        "document_version_id": doc["document_version_id"],
                        "acceptance_text_hash": doc["acceptance_text_hash"],
                    }
                    for doc in reviewed["documents"]
                ],
            }
            accepted_response = await client.post(
                "/api/purchase-intents", json=meaning, headers={"Idempotency-Key": "api-smoke"}
            )
            assert accepted_response.status_code == 200
            accepted = accepted_response.json()
            purchase_id = accepted["purchase_intent_id"]
            assert accepted["scope_held"] is True and accepted["paid_access_granted"] is False
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
            occupied = await client.post(
                "/api/purchase-intents", json=meaning, headers={"Idempotency-Key": "another-tab"}
            )
            assert occupied.status_code == 409 and occupied.json()["detail"]["code"] == "purchase_scope_occupied"
            premature_payment = await client.post(
                "/api/billing/widget-bootstrap", json={"purchase_intent_id": purchase_id}
            )
            assert premature_payment.status_code == 409 and "credential" not in premature_payment.json()
            if lost_agreement_response:
                transport.fail_create = "/agreements"
                transport.hide.add("/agreements")
            start = len(transport.requests)
            prepared = await client.post(f"/api/purchase-intents/{purchase_id}/advance")
            assert prepared.status_code == 200
            if lost_agreement_response:
                assert prepared.json()["state"] == "awaiting_external_result" and prepared.json()["scope_held"]
                assert (
                    sum(
                        req.method == "GET" and req.url.path.endswith("/agreements")
                        for req in transport.requests[start:]
                    )
                    == 1
                )
                repeated = await client.post(f"/api/purchase-intents/{purchase_id}/advance")
                assert repeated.status_code == 200 and repeated.json()["state"] == "awaiting_external_result"
                assert transport.creates("/agreements") == 1 and transport.creates("/subscriptions") == 0
                transport.fail_create = None
                transport.hide.clear()
                prepared = await client.post(f"/api/purchase-intents/{purchase_id}/advance")
            assert prepared.status_code == 200 and prepared.json()["state"] == "linked"
            assert prepared.json()["accepted"] == accepted["accepted"]
            continued = await client.post(f"/api/purchase-intents/{purchase_id}/advance")
            assert continued.status_code == 200 and continued.json()["purchase_intent_id"] == purchase_id
            payment = await client.post("/api/billing/widget-bootstrap", json={"purchase_intent_id": purchase_id})
            assert payment.status_code == 200 and payment.headers["cache-control"] == "no-store"
            presentation = payment.json()
            assert presentation["presentation"] == "payment" and presentation["disablePayments"] is False
            assert presentation["payment_target"] == {
                "purchase_intent_id": purchase_id,
                "agreement_reference": transport.agreements[0]["agreement_number"],
                "seller_reference": "21",
            }
            for flag in (
                "disableCreateSubscription",
                "disableEditSubscription",
                "disableStopSubscription",
                "disableAutopayments",
                "disableInvoiceGeneration",
            ):
                assert presentation[flag] is True
            app.state.sources = object()  # Local history/idempotency must survive a provider outage.
            current = await client.get("/api/purchase-intents/current?product_id=proposal_ai")
            status = await client.get(f"/api/purchase-intents/{purchase_id}")
            replay = await client.post("/api/purchase-intents", json=meaning, headers={"Idempotency-Key": "api-smoke"})
            assert current.status_code == status.status_code == replay.status_code == 200
            assert current.json()["purchase"] == status.json() == replay.json()
            assert status.json()["accepted"] == accepted["accepted"] and status.json()["paid_access_granted"] is False
    assert [transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")] == [1, 1, 1]
    with factory() as db:
        assert db.scalar(select(BillingProductAccessScope)).primary_subscription_id is None
        for model in (PaidAccessState, PurchasedAllowance):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 1


@pytest.mark.parametrize("same_key", [True, False])
async def test_any709_step3_twenty_confirmations_one_scope_and_consent(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], same_key: bool
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, docs, _terms = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
    meaning = PurchaseMeaning(
        product_id="proposal_ai",
        revision_id=link.mapping_revision_id,
        expected_fingerprint=offer.fingerprint,
        documents=tuple(
            LegalSelection(document_version_id=doc.document_version_id, acceptance_text_hash=doc.acceptance_text_hash)
            for doc in docs
        ),
    )

    def attempt(index: int) -> UUID | BillingRefused | None:
        try:
            return service.pin_purchase(
                factory, config, TOKEN, "same" if same_key else str(index), meaning, link, offer, docs
            ).id
        except BillingRefused as error:
            if error.code == "billing_busy":
                assert error.status == 503
                return error
            assert error.code == "purchase_scope_occupied"
            return None

    with ThreadPoolExecutor(max_workers=20) as executor:
        outcomes = list(executor.map(attempt, range(20)))
    accepted_ids = {value for value in outcomes if isinstance(value, UUID)}
    assert len(accepted_ids) == 1
    # Explicit requests after contention reuse the accepted intent or its scope conflict.
    for index in range(20):
        retried = attempt(index)
        assert not isinstance(retried, BillingRefused)
        if same_key:
            assert retried in accepted_ids
        else:
            assert retried is None or retried in accepted_ids
    with factory() as db:
        for model in (PurchaseIntent, BillingPurchaseScopeHold, LegalAcceptanceEvent):
            assert db.scalar(select(func.count()).select_from(model)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(ExternalCreateOperation)
                .where(ExternalCreateOperation.operation_kind != Kind.CUSTOMER)
            )
            == 2
        )


@pytest.mark.parametrize("after_acceptance", [False, True])
async def test_any709_step3_price_change_never_reprices_or_sends_financial_create(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], after_acceptance: bool
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        transport.change_price()
        if after_acceptance:
            result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
            assert result.state == IntentState.FAILED_BEFORE_EXTERNAL_EFFECT and not result.held
            assert result.accepted == purchase.accepted
        else:
            changed = purchase.accepted.meaning.model_copy(update={"expected_fingerprint": "sha256:" + "2" * 64})
            with pytest.raises(PurchaseRefused, match="purchase_idempotency_conflict"):
                await confirm_purchase(
                    sources, config, factory=factory, token=TOKEN, key="one-request", meaning=changed
                )
            with pytest.raises(PurchaseRefused, match="purchase_scope_occupied"):
                await confirm_purchase(sources, config, factory=factory, token=TOKEN, key="different", meaning=changed)
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("path", ["/agreements", "/subscriptions"])
async def test_any709_step3_500_after_create_recovers_without_another_post(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], path: str
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    transport.fail_create = path
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.state == IntentState.AWAITING_EXTERNAL_RESULT
        assert transport.creates(path) == 1
        before = len(transport.requests)
        worker = BillingWorker(config, factory, sources.require_lbx())
        try:
            assert await worker.tick(WorkLane.URGENT)
        finally:
            await worker.aclose()
        recovered = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert transport.requests[before:]
        assert all(req.method == "GET" for req in transport.requests[before:])
        if path == "/agreements":
            assert recovered.state == IntentState.PREPARING
            assert recovered.held and recovered.accepted == purchase.accepted
            assert next(op for op in recovered.operations if op.kind == Kind.AGREEMENT).state == State.BOUND
            assert next(op for op in recovered.operations if op.kind == Kind.SUBSCRIPTION).state == State.PENDING
            assert transport.creates("/subscriptions") == 0
            recovered = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert recovered.state == IntentState.LINKED
        assert recovered.accepted == purchase.accepted
        assert transport.creates(path) == 1


@pytest.mark.parametrize("receipt_matches", [True, False])
async def test_any709_step3_worker_binds_agreement_before_receipt(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    receipt_matches: bool,
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        client = sources.require_lbx()
        create_agreement = client.create_agreement

        async def deliver_after_worker(command: NewAgreement, *, budget: PreflightBudget) -> int:
            provider_id = await create_agreement(command, budget=budget)
            before = len(transport.requests)
            worker = BillingWorker(config, factory, client)
            try:
                assert await worker.tick(WorkLane.URGENT)
            finally:
                await worker.aclose()
            assert transport.requests[before:]
            assert all(req.method == "GET" for req in transport.requests[before:])
            saved = service.read_purchase(factory, purchase.user_id, purchase.id)
            agreement = next(op for op in saved.operations if op.kind == Kind.AGREEMENT)
            assert (agreement.state, agreement.bound_id) == (State.BOUND, str(provider_id))
            return provider_id if receipt_matches else provider_id + 1

        monkeypatch.setattr(client, "create_agreement", deliver_after_worker)
        result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)

    assert result.held and result.accepted == purchase.accepted
    assert [op.id for op in result.operations] == [op.id for op in purchase.operations]
    assert result.state == (IntentState.LINKED if receipt_matches else IntentState.PREPARING)
    assert transport.creates("/agreements") == 1
    assert transport.creates("/subscriptions") == int(receipt_matches)


async def test_any709_step3_restart_zero_discovery_deadline_and_get_only_operator_recovery(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    transport.fail_create = "/agreements"
    transport.hide.add("/agreements")
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        first = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        op = next(item for item in first.operations if item.kind == Kind.AGREEMENT)
        assert op.state == State.UNKNOWN and op.deadline is not None
    assert advance_deadlines(factory, now=op.deadline + timedelta(seconds=1)) == 1
    assert advance_deadlines(factory, now=op.deadline + timedelta(hours=1)) == 0
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        pending = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert pending.state == IntentState.MANUAL_REVIEW and pending.held
        transport.hide.clear()
        before = len(transport.requests)
        recovered = await recover_financial(
            sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
        assert all(req.method == "GET" for req in transport.requests[before:])
        agreement = next(item for item in recovered.operations if item.kind == Kind.AGREEMENT)
        assert agreement.state == State.BOUND and agreement.deadline == op.deadline
        assert transport.creates("/agreements") == 1 and recovered.held


@pytest.mark.parametrize("point_read", [1, 2], ids=["customer-setup", "inventory"])
async def test_late_customer_conflict_cannot_poison_replacement(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    point_read: int,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        customer = service.customer_for_purchase(factory, config, purchase)
        request = terminal_request(factory, config, purchase)
        client = sources.require_lbx()
        get_user = client.get_user
        entered, release = asyncio.Event(), asyncio.Event()
        reads = 0

        async def delayed_customer(*, user_id: int, budget: PreflightBudget) -> LbxUser:
            nonlocal reads
            point = await get_user(user_id=user_id, budget=budget)
            reads += 1
            if reads != point_read:
                return point
            entered.set()
            await release.wait()
            return point.model_copy(update={"outer_id": "stale-mismatch"})

        monkeypatch.setattr(client, "get_user", delayed_customer)
        late = asyncio.create_task(
            advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        )
        try:
            await asyncio.wait_for(entered.wait(), 5)
            result = terminal.resolve_purchase(factory, config, request, PRINCIPAL)
            assert result.state == IntentState.RESOLVED_NO_EXTERNAL_EFFECT and not result.already_resolved
            replacement = await accept(sources, factory, key="replacement-during-old-advance")
            release.set()
            with pytest.raises(PurchaseRefused, match="purchase_scope_released"):
                await late
        finally:
            release.set()
            await asyncio.gather(late, return_exceptions=True)
        with factory() as db:
            assert db.get(ExternalBillingCustomer, customer.customer_id).binding_state == Binding.BOUND
            [audit] = db.scalars(select(ManualReviewCase)).all()
            assert audit.review_case_id == result.review_case_id and audit.resolved_by_principal == PRINCIPAL
            assert terminal.TerminalAudit.model_validate(audit.resolution_document).request == request
        # Replay with a new engine and no source resources or in-process purchase state.
        restarted = create_engine(migrated_database.url)
        try:
            replay = terminal.resolve_purchase(sessionmaker(restarted, autoflush=False), config, request, PRINCIPAL)
        finally:
            restarted.dispose()
        assert replay == result.model_copy(update={"already_resolved": True})
        saved = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert not saved.held and saved.accepted == purchase.accepted
        assert [(op.id, op.key) for op in saved.operations] == [(op.id, op.key) for op in purchase.operations]
        assert service.read_purchase(factory, replacement.user_id, replacement.id).held
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("entrypoint", ["status", "current"])
async def test_purchase_status_and_hold_share_one_snapshot(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], entrypoint: str
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
    completion = terminal_request(factory, config, purchase)
    row_read, resume = Event(), Event()
    reader_thread: int | None = None

    def after_select(
        connection: object, cursor: object, statement: str, parameters: object, context: object, executemany: bool
    ) -> None:
        if (
            get_ident() == reader_thread
            and statement.startswith("SELECT")
            and any(f"FROM {table}" in statement for table in ("purchase_intents", "billing_purchase_scope_holds"))
        ):
            row_read.set()
            assert resume.wait(5)

    def read() -> Purchase | None:
        nonlocal reader_thread
        reader_thread = get_ident()
        if entrypoint == "current":
            return service.current_purchase(factory, config, TOKEN, purchase.accepted.selection.product_id)
        return service.read_purchase(factory, purchase.user_id, purchase.id)

    event.listen(migrated_database, "after_cursor_execute", after_select)
    reading = asyncio.create_task(asyncio.to_thread(read))
    try:
        assert await asyncio.to_thread(row_read.wait, 5)
        terminal.resolve_purchase(factory, config, completion, PRINCIPAL)
    finally:
        resume.set()
        try:
            before_release = await reading
        finally:
            event.remove(migrated_database, "after_cursor_execute", after_select)

    assert before_release is not None and before_release.state == IntentState.CREATED and before_release.held
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.state == IntentState.RESOLVED_NO_EXTERNAL_EFFECT and not saved.held
    assert service.current_purchase(factory, config, TOKEN, purchase.accepted.selection.product_id) is None
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


async def test_operator_releases_unknown_only_with_confirmed_no_effect(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)

    def respond(message: httpx.Request) -> httpx.Response:
        if message.method == "POST" and message.url.path.endswith("/agreements"):
            transport.requests.append(message)
            return httpx.Response(500, json={"code": 500, "response": {}})
        return transport.respond(message)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        pending = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        agreement, subscription = pending.operations
        assert agreement.state == State.UNKNOWN and agreement.deadline and not transport.agreements
        assert advance_deadlines(factory, now=agreement.deadline + timedelta(seconds=1)) == 1
        reviewed = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert reviewed.state == IntentState.MANUAL_REVIEW
        count = len(transport.requests)

        unsent = terminal_request(factory, config, reviewed)
        with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
            terminal.resolve_purchase(factory, config, unsent, PRINCIPAL)
        proof = terminal.OperationEvidence(
            operation_id=agreement.id, outcome=terminal.TerminalEvidenceKind.NO_EXTERNAL_EFFECT
        )
        unsent_subscription = terminal.OperationEvidence(
            operation_id=subscription.id, outcome=terminal.TerminalEvidenceKind.NOT_SENT
        )
        missing = terminal_request(factory, config, reviewed, proof, unsent_subscription)
        with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
            terminal.resolve_purchase(factory, config, missing, PRINCIPAL)
        confirmed = terminal_request(factory, config, reviewed, proof, unsent_subscription, confirmed=True)
        reversed_order = confirmed.evidence.model_copy(
            update={"confirmed_at": confirmed.evidence.senders_stopped_at - timedelta(seconds=1)}
        )
        with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
            terminal.resolve_purchase(
                factory, config, confirmed.model_copy(update={"evidence": reversed_order}), PRINCIPAL
            )

        def fail_after_audit(db: Session, user_id: UUID) -> int:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(ManualReviewCase)
                    .where(ManualReviewCase.reason_code == terminal.TERMINAL_REASON)
                )
                == 1
            )
            raise RuntimeError("synthetic reducer failure")

        with monkeypatch.context() as fault:
            fault.setattr(terminal, "reduce_paid_access", fail_after_audit)
            with pytest.raises(RuntimeError, match="synthetic reducer failure"):
                terminal.resolve_purchase(factory, config, confirmed, PRINCIPAL)
        saved = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert saved.held and saved.operations == reviewed.operations and saved.state == reviewed.state
        with factory() as db:
            assert (
                db.scalar(
                    select(func.count())
                    .select_from(ManualReviewCase)
                    .where(ManualReviewCase.reason_code == terminal.TERMINAL_REASON)
                )
                == 0
            )
            work = db.scalars(select(BillingWorkItem).where(BillingWorkItem.scope_reference == str(agreement.id))).all()
            assert work and all(item.work_state != BillingWorkState.INVALID for item in work)
            generations = {item.work_item_id: item.enqueue_generation for item in work}

        result = terminal.resolve_purchase(factory, config, confirmed, PRINCIPAL)
        assert result.state == IntentState.RESOLVED_NO_EXTERNAL_EFFECT
        assert not service.read_purchase(factory, purchase.user_id, purchase.id).held
        assert not background_recovery._repair_operation(factory, config, agreement.id)
        with factory() as db:
            for identity, generation in generations.items():
                item = db.get(BillingWorkItem, identity)
                assert item.work_state == BillingWorkState.INVALID and item.enqueue_generation == generation + 1
                assert item.lease_owner is None and item.lease_expires_at is None
        assert len(transport.requests) == count
        assert transport.creates("/agreements") == 1 and transport.creates("/subscriptions") == 0

        # A later exact agreement can produce a restriction even when the
        # terminal outcome uses a state the previous schema recognizes.
        original_post = next(
            item for item in transport.requests if item.method == "POST" and item.url.path.endswith("/agreements")
        )
        transport.agreements.append({**agreement_factory().model_dump(), **json.loads(original_post.content)})
        await recover_financial(
            sources,
            config,
            factory=factory,
            user_id=purchase.user_id,
            purchase_id=purchase.id,
            operation_id=agreement.id,
        )
        with alembic_test_config(migrated_database.url) as migration:
            with pytest.raises(CommandError, match="open late-object case"):
                command.downgrade(migration, "20261113_0013")
        with factory() as db:
            case = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).one()
            assert case.case_state == "open" and case.scope_reference == str(purchase.id)
            closure = late.ClosureRequest(
                user_id=purchase.user_id,
                purchase_id=purchase.id,
                case_id=case.review_case_id,
                expected_digest=case_digest(case),
                reason="Late agreement definitively closed",
                reference="Synthetic provider confirmation for ANY-821",
                evidence=late.ClosureEvidence(
                    outcome=late.ClosureKind.EXTERNAL_TERMINAL,
                    external_object_id=late.LateObjectEvidence.model_validate(
                        case.evidence_document
                    ).external_object_id,
                    confirmed_at=datetime.now(UTC),
                ),
            )

        transport.agreements[0]["close_date"] = "2026-10-27"
        assert late.close_case(factory, config, closure, PRINCIPAL).state == IntentState.RESOLVED_NO_EXTERNAL_EFFECT
        retained = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert not retained.held and all(op.bound_id is None for op in retained.operations)
        with alembic_test_config(migrated_database.url) as migration:
            with pytest.raises(CommandError, match="downgrade refused"):
                command.downgrade(migration, "20261113_0013")
        with factory() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261123_0821"
            case = db.get(ManualReviewCase, closure.case_id)
            assert case.case_state == "resolved"
            assert late.ClosureAudit.model_validate(case.resolution_document).request == closure
        assert service.read_purchase(factory, purchase.user_id, purchase.id) == retained
        assert transport.creates("/agreements") == 1 and transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("change", ["retarget", "legal"])
async def test_any709_step3_rechecks_local_changes_during_source_io(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], change: str
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, docs, _terms = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
        meaning = PurchaseMeaning(
            product_id="proposal_ai",
            revision_id=link.mapping_revision_id,
            expected_fingerprint=offer.fingerprint,
            documents=tuple(
                LegalSelection(
                    document_version_id=doc.document_version_id, acceptance_text_hash=doc.acceptance_text_hash
                )
                for doc in docs
            ),
        )

        def mutate_during_read() -> None:
            if change == "retarget":
                publish_product_link(
                    factory,
                    evaluation=link_document(selection=link_selection(tariff_id=702)),
                    expected_previous_revision=1,
                    deadline=time.monotonic() + 5,
                    lock_timeout_seconds=1,
                    provider_origin=config.lbx_provider_origin,
                )
            else:
                with factory() as db:
                    db.execute(text("UPDATE document_versions SET is_active = false WHERE doc_type = 'offer'"))
                    db.commit()

        transport.before_offer = mutate_during_read
        with pytest.raises(PurchaseRefused):
            await confirm_purchase(sources, config, factory=factory, token=TOKEN, key="racing", meaning=meaning)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 0
        assert db.scalar(select(func.count()).select_from(LegalAcceptanceEvent)) == 0


@pytest.mark.parametrize("mismatch", ["seller", "customer", "price"])
async def test_any709_step3_material_mismatch_blocks_payment_but_keeps_account_view(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], mismatch: str
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        if mismatch == "price":
            transport.subscriptions[0]["services"][0]["price"] = 101
        else:
            transport.agreements[0]["organization_id" if mismatch == "seller" else "user_id"] = 9
        with pytest.raises(BillingRefused):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential
        latest = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert latest.state == IntentState.MANUAL_REVIEW and latest.held
        assert latest.accepted == purchase.accepted
        # A known conflict cannot be cleared by merely restoring the next GET.
        if mismatch == "price":
            transport.subscriptions[0]["services"][0]["price"] = 100
        else:
            transport.agreements[0]["organization_id" if mismatch == "seller" else "user_id"] = (
                21 if mismatch == "seller" else 345
            )
        with pytest.raises(BillingRefused):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert service.read_purchase(factory, purchase.user_id, purchase.id).state == IntentState.MANUAL_REVIEW
    assert [transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")] == [1, 1, 1]


async def test_any709_step3_permanent_scope_binding_and_evidence_constraints(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    for statement in (
        "UPDATE purchase_intents SET accepted_snapshot = '{}'::jsonb",
        "DELETE FROM external_create_operations WHERE operation_kind = 'agreement'",
        "UPDATE external_create_operations SET unknown_since = unknown_since + interval '1 hour', unknown_recovery_deadline_at = unknown_recovery_deadline_at + interval '1 hour' WHERE operation_kind = 'agreement'",
        "UPDATE external_create_operations SET operation_state = 'pending' WHERE operation_kind = 'agreement'",
    ):
        with pytest.raises(DatabaseError), migrated_database.begin() as connection:
            connection.execute(text(statement))
    agreement = next(op for op in linked.operations if op.kind == Kind.AGREEMENT)
    with factory() as db:
        original = db.get(ExternalCreateOperation, agreement.id)
        duplicate = ExternalCreateOperation(
            create_operation_id=uuid4(),
            operation_kind=Kind.AGREEMENT,
            customer_id=original.customer_id,
            external_billing_account_id=original.external_billing_account_id,
            purchase_intent_id=purchase.id,
            request_correlation_key="other",
            operation_state=State.PENDING,
        )
        db.add(duplicate)
        with pytest.raises(IntegrityError):
            db.commit()


async def test_any709_step3_forward_upgrade_preserves_populated_history(
    postgres_engine: Engine, database_test_url: URL
) -> None:
    reset_public_schema(postgres_engine)
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "20261001_0002")
    factory = sessionmaker(bind=postgres_engine)
    configuration = step1_settings()
    user_id, customer_id, operation_id = uuid4(), uuid4(), uuid4()
    original_unknown_since = utc_now()
    original_deadline = original_unknown_since + timedelta(hours=2)
    outer_key = "retained-customer-key"
    # Seed the previous wire/schema shape, without running current application
    # code against a schema that predates its new mapped operation column.
    with factory() as db:
        db.execute(
            text(
                "INSERT INTO users (id, tenant_id, region, email, email_normalized, status, metadata) "
                "VALUES (:id, 'anytoolai', 'ru', 'retained@example.test', 'retained@example.test', 'active', '{}')"
            ),
            {"id": user_id},
        )
        db.execute(
            text(
                "INSERT INTO external_billing_customers "
                "(customer_id, external_billing_account_id, user_id, billing_customer_key) "
                "VALUES (:id, :account, :user, :key)"
            ),
            {
                "id": customer_id,
                "account": configuration.lbx_external_billing_account_id,
                "user": user_id,
                "key": outer_key,
            },
        )
        db.execute(
            text(
                "INSERT INTO external_create_operations "
                "(create_operation_id, operation_kind, customer_id, request_correlation_key, "
                "operation_state, unknown_since, unknown_recovery_deadline_at) "
                "VALUES (:id, 'customer', :customer, :key, 'possible_send', :since, :deadline)"
            ),
            {
                "id": operation_id,
                "customer": customer_id,
                "key": outer_key,
                "since": original_unknown_since,
                "deadline": original_deadline,
            },
        )
        db.commit()
    with alembic_test_config(database_test_url) as config:
        command.upgrade(config, "head")
    with factory() as db:
        customer = db.get(ExternalBillingCustomer, customer_id)
        assert customer.billing_customer_key == outer_key and customer.provider_origin is None
        operation = db.get(ExternalCreateOperation, operation_id)
        assert (
            operation.external_billing_account_id
            == db.get(ExternalBillingCustomer, customer_id).external_billing_account_id
        )
        assert operation.operation_state == State.POSSIBLE_SEND
        assert operation.request_correlation_key == outer_key and operation.send_fence is None
        assert operation.unknown_since == original_unknown_since
        assert operation.unknown_recovery_deadline_at == original_deadline
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 0


async def test_any709_step3_price_changed_between_review_and_confirmation_has_no_consent(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, docs, _terms = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
        meaning = PurchaseMeaning(
            product_id="proposal_ai",
            revision_id=link.mapping_revision_id,
            expected_fingerprint=offer.fingerprint,
            documents=tuple(
                LegalSelection(
                    document_version_id=doc.document_version_id, acceptance_text_hash=doc.acceptance_text_hash
                )
                for doc in docs
            ),
        )
        transport.change_price()
        with pytest.raises(PurchaseRefused, match="terms_changed"):
            await confirm_purchase(sources, config, factory=factory, token=TOKEN, key="new", meaning=meaning)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchaseIntent)) == 0
        assert db.scalar(select(func.count()).select_from(LegalAcceptanceEvent)) == 0
    assert not any(req.method == "POST" for req in transport.requests)


@pytest.mark.parametrize("failure", ["malformed", "timeout", "multiple"])
async def test_any709_step3_ambiguous_post_uses_only_get_recovery(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], failure: str
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()

    def respond(request: httpx.Request) -> httpx.Response:
        response = transport.respond(request)
        if request.method == "POST" and request.url.path.endswith("/agreements"):
            if failure == "multiple":
                transport.agreements.append({**transport.agreements[0], "agreement_id": 457})
            if failure == "timeout":
                raise httpx.ReadTimeout("PRIVATE timeout canary")
            return httpx.Response(200, json={"code": 200, "response": {}})
        return response

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.state == IntentState.AWAITING_EXTERNAL_RESULT and result.held
        before = len(transport.requests)
        recovered = await recover_financial(
            sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
        assert all(req.method == "GET" for req in transport.requests[before:])
        assert transport.creates("/agreements") == 1
        if failure == "multiple":
            assert recovered.state == IntentState.MANUAL_REVIEW
            assert transport.creates("/subscriptions") == 0
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 1
        else:
            assert transport.creates("/subscriptions") == 0
            continued = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
            assert continued.state == IntentState.LINKED
            assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


async def test_any709_step3_lost_claim_ack_and_late_apply_keep_original_fence_and_hold(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    lost: list[bool] = []

    class LostAcknowledgement(Session):
        def commit(self) -> None:
            claim = not lost and any(
                isinstance(row, ExternalCreateOperation)
                and row.operation_kind != Kind.CUSTOMER
                and row.operation_state == State.POSSIBLE_SEND
                # claim_financial deliberately flushes its durable evidence
                # before commit, so the operation is no longer in self.dirty.
                for row in self.identity_map.values()
            )
            super().commit()
            if claim:
                lost.append(True)
                raise RuntimeError("synthetic commit acknowledgement loss")

    factory = sessionmaker(bind=migrated_database, class_=LostAcknowledgement)
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        with pytest.raises(RuntimeError, match="acknowledgement"):
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert lost == [True]
        original = service.read_purchase(factory, purchase.user_id, purchase.id)
        op = next(item for item in original.operations if item.kind == Kind.AGREEMENT)
        assert op.state == State.POSSIBLE_SEND and op.deadline
        recovered = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert recovered.held and transport.creates("/agreements") == 0
        financial.financial_pending(factory, recovered, op, conflict=True)
        with pytest.raises(PurchaseRefused, match="purchase_pending"):
            financial.bind_financial(
                factory, recovered, op, 999, proof=original_proof(factory, recovered, op, transport)
            )
        with factory() as db:
            saved = db.get(ExternalCreateOperation, op.id)
            assert saved.unknown_recovery_deadline_at == op.deadline
            assert saved.operation_state == State.MANUAL_REVIEW and saved.bound_external_object_id is None
            work = db.scalar(select(BillingWorkItem).where(BillingWorkItem.coalescing_key == str(op.id)))
            assert work and work.next_attempt_at < op.deadline
            deadline = db.scalar(
                select(BillingWorkItem).where(
                    BillingWorkItem.work_kind == "external_create_deadline",
                    BillingWorkItem.scope_reference == str(op.id),
                )
            )
            assert deadline.next_attempt_at == op.deadline


async def test_any709_step3_api_ownership_local_status_and_same_key_survive_source_outage(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    from fastapi import FastAPI
    from app.domains.purchases import router as routes
    from app.http.dependencies import get_session_factory
    from app.models import User, AuthSession

    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
    with factory() as db:
        other = User(
            id=uuid4(),
            tenant_id="anytoolai",
            region="ru",
            email="other@example.test",
            email_normalized="other@example.test",
            email_verified_at=utc_now(),
        )
        db.add(other)
        db.flush()
        db.add(
            AuthSession(
                user_id=other.id,
                tenant_id="anytoolai",
                region="ru",
                token_hash=hashlib.sha256(b"other-token").hexdigest(),
                expires_at=utc_now() + timedelta(days=1),
            )
        )
        db.commit()
    monkeypatch.setattr(routes, "settings", config)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[get_session_factory] = lambda: factory
    app.state.sources = object()  # Any source access would fail this test.
    headers = {"Authorization": "Bearer " + TOKEN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client:
        status = await client.get(f"/api/purchase-intents/{purchase.id}", headers=headers)
        assert status.status_code == 200 and status.headers["cache-control"] == "no-store"
        current = await client.get("/api/purchase-intents/current?product_id=proposal_ai", headers=headers)
        assert current.json()["purchase"]["purchase_intent_id"] == str(purchase.id)
        repeated = await client.post(
            "/api/purchase-intents",
            json=purchase.accepted.meaning.model_dump(mode="json"),
            headers={**headers, "Idempotency-Key": "one-request"},
        )
        assert repeated.status_code == 200
        unauthorized = await client.get(f"/api/purchase-intents/{purchase.id}")
        assert unauthorized.status_code == 401
        foreign = await client.get(
            f"/api/purchase-intents/{purchase.id}", headers={"Authorization": "Bearer other-token"}
        )
        assert foreign.status_code == 404 and "accepted" not in foreign.json()
        unknown = await client.post(
            f"/api/purchase-intents/{purchase.id}/advance", headers={"Authorization": "Bearer other-token"}
        )
        assert unknown.status_code == 404


@pytest.mark.parametrize("interruption", ["logout", "release"])
async def test_any709_step3_widget_rechecks_after_client_io(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], interruption: str
) -> None:
    from app.models import AuthSession

    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    interrupted = False

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal interrupted
        response = transport.respond(request)
        if request.url.path.endswith("/client/user") and not interrupted:
            interrupted = True
            if interruption == "logout":
                with factory() as db:
                    db.query(AuthSession).delete()
                    db.commit()
            else:
                linked = service.read_purchase(factory, purchase.user_id, purchase.id)
                proofs = tuple(
                    terminal.OperationEvidence(
                        operation_id=op.id,
                        outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
                        external_object_id=op.bound_id,
                    )
                    for op in linked.operations
                )
                transport.agreements[0]["close_date"] = "2026-10-27"
                transport.subscriptions[0]["state"] = 3
                completion = terminal_request(factory, config, linked, *proofs, confirmed=True)
                terminal.resolve_purchase(factory, config, completion, PRINCIPAL)
                return transport.response({"user_id": 345, "outer_id": "stale-client-mismatch"})
        return response

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        refusal = "billing_session_required" if interruption == "logout" else "purchase_scope_released"
        with pytest.raises(BillingRefused, match=refusal):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert interrupted and transport.creates("/agreements") == transport.creates("/subscriptions") == 1
    assert service.read_purchase(factory, purchase.user_id, purchase.id).held == (interruption == "logout")
    with factory() as db:
        assert db.get(ExternalBillingCustomer, purchase.customer_id).binding_state == Binding.BOUND


async def test_any709_step3_changed_terms_after_possible_send_never_release_or_replace(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    transport.fail_create = "/agreements"
    transport.hide.add("/agreements")
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        uncertain = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        original = next(op for op in uncertain.operations if op.kind == Kind.AGREEMENT)
        subscription = next(op for op in uncertain.operations if op.kind == Kind.SUBSCRIPTION)
        agreement_id = str(transport.agreements[0]["agreement_id"])
        original_proof = terminal.OperationEvidence(
            operation_id=original.id,
            outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
            external_object_id=agreement_id,
        )
        no_subscription = terminal.OperationEvidence(
            operation_id=subscription.id,
            outcome=terminal.TerminalEvidenceKind.NOT_SENT,
        )
        early = terminal_request(factory, config, uncertain, original_proof, no_subscription, confirmed=True)
        transport.change_price()
        before = len(transport.requests)
        pending = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert pending.held and pending.accepted == purchase.accepted
        assert not any("/tariffs" in req.url.path for req in transport.requests[before:])
        transport.hide.clear()
        review = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert review.state == IntentState.MANUAL_REVIEW and review.held
        assert review.reason == "purchase_terms_changed_after_preparation"
        assert next(op for op in review.operations if op.kind == Kind.AGREEMENT).deadline == original.deadline
        assert review.operations[0].bound_id == agreement_id and review.operations[1].state == State.MANUAL_REVIEW
        refreshed = terminal_request(factory, config, review, original_proof, no_subscription, confirmed=True)
        with pytest.raises(PurchaseRefused, match="purchase_resolution_stale"):
            terminal.resolve_purchase(factory, config, early, PRINCIPAL)
        with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
            terminal.resolve_purchase(
                factory, config, refreshed.model_copy(update={"evidence": early.evidence}), PRINCIPAL
            )
        wrong_subscription = terminal.OperationEvidence(
            operation_id=subscription.id,
            outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
            external_object_id="99999",
        )
        wrong = terminal_request(factory, config, review, original_proof, wrong_subscription, confirmed=True)
        with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
            terminal.resolve_purchase(factory, config, wrong, PRINCIPAL)
        assert service.read_purchase(factory, purchase.user_id, purchase.id).held
        assert transport.creates("/agreements") == 1 and transport.creates("/subscriptions") == 0

        # A populated database remains readable through the upgrade and
        # downgrade until it actually contains the new outcome.
        previous_head = "20261113_0013"
        with alembic_test_config(migrated_database.url) as migration:
            command.downgrade(migration, previous_head)
            assert service.read_purchase(factory, purchase.user_id, purchase.id) == review
            command.upgrade(migration, "head")
        assert service.read_purchase(factory, purchase.user_id, purchase.id) == review

        transport.agreements[0]["close_date"] = "2026-10-27"
        confirmed = terminal_request(factory, config, review, original_proof, no_subscription, confirmed=True)
        done = terminal.resolve_purchase(factory, config, confirmed, PRINCIPAL)
        assert done.state == IntentState.RESOLVED_EXTERNAL_TERMINAL
        retained = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert not retained.held and retained.accepted == purchase.accepted
        assert all(old.fence != new.fence for old, new in zip(review.operations, retained.operations, strict=True))
        assert retained.operations == tuple(
            replace(op, fence=current.fence) for op, current in zip(review.operations, retained.operations, strict=True)
        )
        with alembic_test_config(migrated_database.url) as migration:
            with pytest.raises(CommandError, match="downgrade refused"):
                command.downgrade(migration, previous_head)
        assert service.read_purchase(factory, purchase.user_id, purchase.id) == retained
        with factory() as db:
            assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261123_0821"
            assert db.get(ManualReviewCase, done.review_case_id).case_state == "resolved"
        assert transport.creates("/agreements") == 1 and transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("duplicate", ["subscription", "agreement"])
async def test_any709_step3_subscription_and_agreement_bindings_are_unique_for_history(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], duplicate: str
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        db.add(
            ExternalSubscription(
                subscription_id=uuid4(),
                external_billing_account_id=sub.external_billing_account_id,
                customer_id=sub.customer_id,
                user_id=sub.user_id,
                product_id="other-product",
                external_subscription_id=sub.external_subscription_id if duplicate == "subscription" else "999",
                external_agreement_id=sub.external_agreement_id if duplicate == "agreement" else "999",
                lifecycle_status=sub.lifecycle_status,
                financial_access_status=sub.financial_access_status,
                commercial_access_status=sub.commercial_access_status,
                last_authoritative_read_at=sub.last_authoritative_read_at,
                projection_valid_until=sub.projection_valid_until,
            )
        )
        with pytest.raises(IntegrityError) as caught:
            db.commit()
        assert caught.value.orig.diag.constraint_name == (
            "uq_subscription_provider" if duplicate == "subscription" else "uq_subscription_agreement"
        )


async def test_any709_step3_missing_original_consent_never_prepares_financial_objects(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.infrastructure.queries import purchases as queries

    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        monkeypatch.setattr(queries, "original_consent", lambda db, row, **kwargs: [])
        with pytest.raises(PurchaseRefused, match="purchase_consent_unproven"):
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert not any(req.method == "POST" for req in transport.requests)
