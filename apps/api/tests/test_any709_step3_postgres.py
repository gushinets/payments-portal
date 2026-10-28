"""Purchase transaction, fault and concurrency scenarios on disposable PostgreSQL.

Synthetic transports never reach live LBX.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command
from sqlalchemy import func, select, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.exc import DatabaseError, IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.purchases import advance_purchase, confirm_purchase, recover_financial, review_purchase
from app.composition.sources import SourceResources, source_resources
from app.core.time import utc_now
from app.domains.billing.contracts import BillingRefused
from app.domains.catalog.link_publication import publish_product_link
from app.domains.purchases.contracts import Purchase, PurchaseMeaning, LegalSelection, PurchaseRefused
from app.domains.purchases import financial, service
from app.models import (
    BillingPurchaseScopeHold,
    BillingProductAccessScope,
    BillingWorkItem,
    DocumentAcceptance,
    ExternalBillingCustomer,
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
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.postgres import alembic_test_config, reset_public_schema
from apps.api.tests.test_any709_step2_postgres import seed, TOKEN

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


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
    link, offer, documents = await review_purchase(
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
        assert not any("/tariffs" in req.url.path for req in transport.requests[before:])
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
        assert sub.financial_access_status.value == "unverified"
        assert sub.projection_valid_until == sub.last_authoritative_read_at
        for model in (PaidAccessState, PurchasedAllowance, BillingProductAccessScope):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 1
        assert db.scalar(select(func.count()).select_from(ExternalBillingCustomer)) == 1


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
            operation = next(
                op
                for op in retained.operations
                if op.kind == (Kind.AGREEMENT if path.startswith("/agreements/") else Kind.SUBSCRIPTION)
            )
            with factory() as db:
                work = db.scalar(select(BillingWorkItem).where(BillingWorkItem.coalescing_key == str(operation.id)))
                assert work.work_state == "pending" and work.payload_document["last_failure"]
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
        assert not any("/tariffs" in request.url.path for request in transport.requests[before:])
    assert [transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")] == [1, 1, 1]
    with factory() as db:
        for model in (PaidAccessState, PurchasedAllowance, BillingProductAccessScope, ManualReviewCase):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        sub = db.scalar(select(ExternalSubscription))
        assert sub.financial_access_status.value == "unverified"
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
            prepared = await client.post(f"/api/purchase-intents/{purchase_id}/advance")
            assert prepared.status_code == 200
            if lost_agreement_response:
                assert prepared.json()["state"] == "awaiting_external_result" and prepared.json()["scope_held"]
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
        for model in (PaidAccessState, PurchasedAllowance, BillingProductAccessScope):
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
        link, offer, docs = await review_purchase(
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
        assert result.state == IntentState.LINKED
        assert transport.creates(path) == 1
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert transport.creates(path) == 1


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
    assert financial.escalate_overdue_financial(factory, now=op.deadline + timedelta(seconds=1)) == 1
    assert financial.escalate_overdue_financial(factory, now=op.deadline + timedelta(hours=1)) == 0
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
        link, offer, docs = await review_purchase(
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
        link, offer, docs = await review_purchase(
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
        assert result.state == (IntentState.MANUAL_REVIEW if failure == "multiple" else IntentState.LINKED)
        assert result.held
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert transport.creates("/agreements") == 1
        if failure == "multiple":
            assert transport.creates("/subscriptions") == 0
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 1


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
            financial.bind_financial(factory, recovered, op, 999)
        with factory() as db:
            saved = db.get(ExternalCreateOperation, op.id)
            assert saved.unknown_recovery_deadline_at == op.deadline
            assert saved.operation_state == State.MANUAL_REVIEW and saved.bound_external_object_id is None
            work = db.scalar(select(BillingWorkItem).where(BillingWorkItem.coalescing_key == str(op.id)))
            assert work and work.next_attempt_at == op.deadline


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


async def test_any709_step3_logout_after_async_widget_checks_returns_no_credential(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    from app.models import AuthSession

    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    logout = []

    def respond(request: httpx.Request) -> httpx.Response:
        response = transport.respond(request)
        if request.url.path.endswith("/client/user") and not logout:
            with factory() as db:
                db.query(AuthSession).delete()
                db.commit()
            logout.append(True)
        return response

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        with pytest.raises(BillingRefused, match="billing_session_required"):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert logout and transport.creates("/agreements") == transport.creates("/subscriptions") == 1
    assert service.read_purchase(factory, purchase.user_id, purchase.id).held


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
