"""Origin-proven historical scopes through real Application/DB and synthetic LBX."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import reconcile_purchase, resolve_review
from app.composition.purchases import advance_purchase
from app.composition.sources import SourceResources, source_resources
from app.core.settings import Settings
from app.domains.billing import background_recovery as recovery, customers, work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase
from app.http import billing_webhook as entrypoint
from app.http.dependencies import get_session_factory
from app.jobs.billing import BillingWorker
from app.main import create_app
from app.models import (
    AccessInvalidationOutbox,
    BillingStateObservation,
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalBillingWebhookDelivery,
    ExternalSubscription,
    PaidAccessState,
    PurchasedAllowance,
    PurchaseIntentState,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
)
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.factories.billing_webhook import AUTH_HEADER, AUTH_VALUE, PATH, hint_payload, webhook_settings
from apps.api.tests.factories.billing_worker import work_factory
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_connection_scope_postgres import head
from apps.api.tests.test_any709_step2_postgres import seed, TOKEN
from apps.api.tests.test_any709_step3_postgres import accept
from apps.api.tests.test_billing_background_recovery_postgres import original, synthetic_prepare
from apps.api.tests.test_billing_subscription_reconciliation_postgres import activate

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
Scenario = tuple[Settings, PurchaseTransport, SourceResources, Purchase]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(params=[False, True], ids=["fresh", "retained"])
async def retained_scenario(
    request: pytest.FixtureRequest,
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Scenario]:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    factory = postgres_session_factory
    original_config = step1_settings()
    seed(factory)
    head(factory, original_config, legacy=request.param, proven=True)
    # Once origin is proven, even the old credential-derived alias changes on
    # rotation. Runtime must retain the original account rather than guess it.
    configuration = step1_settings(lbx_server_username="rotated-synthetic-username")
    transport = PurchaseTransport()
    transport.pool = factory.kw["bind"].pool
    async with source_resources(
        configuration,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        assert purchase.account_id == (
            original_config.lbx_legacy_credential_scope
            if request.param
            else configuration.lbx_external_billing_account_id
        )
        yield configuration, transport, sources, purchase


async def test_billing_retained_scope_worker_cli_and_audited_restore(
    retained_scenario: Scenario, postgres_session_factory: sessionmaker[Session]
) -> None:
    config, transport, sources, purchase = retained_scenario
    factory = postgres_session_factory
    purchase = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert purchase.state == PurchaseIntentState.LINKED
    before = tuple(original(factory, op.id) for op in purchase.operations)
    requests = len(transport.requests)
    worker = BillingWorker(config, factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    activate(transport)
    await reconcile_purchase(sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id)
    state = inspect_evidence(factory, config, purchase.user_id, purchase.id)
    assert state["subscription"]["financial"] == "allowed"
    transport.subscriptions[0]["services"][0]["price"] = 15
    await reconcile_purchase(sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id)
    transport.subscriptions[0]["services"][0]["price"] = 100
    request = resolution_request(purchase, inspect_evidence(factory, config, purchase.user_id, purchase.id))
    result = await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    assert result["outcome"] == "resolved"
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        assert sub.external_billing_account_id == purchase.account_id
        assert sub.financial_access_status == "allowed" and sub.commercial_access_status == "eligible"
        assert sub.projection_valid_until - sub.last_authoritative_read_at == timedelta(hours=6)
        assert db.get(ExternalBillingCustomer, purchase.customer_id).external_billing_account_id == purchase.account_id
        for model in (PaidAccessState, PurchasedAllowance, AccessInvalidationOutbox):
            assert db.scalar(select(func.count()).select_from(model)) == 0
    assert tuple(original(factory, op.id) for op in purchase.operations) == before
    assert all(req.method == "GET" for req in transport.requests[requests:])
    await worker.aclose()


async def test_billing_retained_scope_sweep_inventory_webhook_and_local_expiry(
    retained_scenario: Scenario, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, transport, sources, purchase = retained_scenario
    factory = postgres_session_factory
    purchase = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    with factory() as db:
        db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        db.commit()
    requests = len(transport.requests)
    work.ensure_sweep(factory, config)
    worker = BillingWorker(config, factory, sources.require_lbx())
    assert await worker.tick(WorkLane.LOCAL)
    assert len(transport.requests) == requests
    assert work.inspect_backlog(factory, config)[0] >= 3
    assert await worker.tick(WorkLane.URGENT)
    assert await worker.tick(WorkLane.NORMAL)  # Customer-wide inventory at the retained scope.
    with factory() as db:
        inventory = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == recovery.INVENTORY))
        assert inventory.last_error_classification is None and inventory.attempt_count == 1
        assert inventory.coalescing_key.startswith(purchase.account_id + ":")
    monkeypatch.setattr(entrypoint, "settings", webhook_settings(lbx_server_username="rotated-synthetic-username"))
    app = create_app()
    app.dependency_overrides[get_session_factory] = lambda: factory
    requests = len(transport.requests)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client:
        response = await client.post(PATH, json=hint_payload(), headers={AUTH_HEADER: AUTH_VALUE})
    assert response.status_code == 200 and response.json()["outcome"] == "queued"
    assert len(transport.requests) == requests
    assert await worker.tick(WorkLane.URGENT)
    with factory() as db:
        receipt = db.scalar(select(ExternalBillingWebhookDelivery))
        assert receipt.external_billing_account_id == purchase.account_id and receipt.processing_state == "processed"
        sub = db.scalar(select(ExternalSubscription))
        deadline = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
        sub.projection_valid_until = deadline.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    requests = len(transport.requests)
    assert await worker.tick(WorkLane.LOCAL)
    assert len(transport.requests) == requests
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillingStateObservation)
                .where(BillingStateObservation.evidence_schema_version == "subscription-trust-expiry:v1")
            )
            == 1
        )
    await worker.aclose()


async def test_billing_retained_scope_customer_and_financial_repair_recovery_deadline(
    retained_scenario: Scenario, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    config, transport, sources, purchase = retained_scenario
    factory = postgres_session_factory
    current = customers.reserve_customer(factory, config, TOKEN)
    customers.claim_customer_send(factory, config, TOKEN, current)
    transport.customer = {"user_id": 345, "outer_id": current.outer_key}
    with factory() as db:
        db.execute(delete(BillingWorkItem))
        db.commit()
    assert recovery.repair_batch(factory, config)
    worker = BillingWorker(config, factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    assert customers.reserve_customer(factory, config, TOKEN).provider_id == "345"
    # Create original immutable possible-send evidence in the past, with an
    # existing provider object whose reply was lost. Recovery remains GET-only.
    monkeypatch.setattr(financial, "utc_now", lambda: datetime.now(UTC) - timedelta(hours=3))
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    before = original(factory, operation.id)
    with factory() as db:
        db.execute(delete(BillingWorkItem).where(BillingWorkItem.scope_reference == str(operation.id)))
        db.commit()
    assert recovery.repair_batch(factory, config)
    assert await worker.tick(WorkLane.LOCAL)
    await worker.tick(WorkLane.LOCAL)  # The already-bound agreement may have an earlier deadline.
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert next(op for op in saved.operations if op.id == operation.id).state == State.MANUAL_REVIEW
    assert await worker.tick(WorkLane.URGENT)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.state == PurchaseIntentState.LINKED and saved.held
    assert next(op for op in saved.operations if op.kind == Kind.SUBSCRIPTION).state == State.BOUND
    assert original(factory, operation.id) == before
    with factory() as db:
        deadline = db.scalar(
            select(BillingWorkItem).where(
                BillingWorkItem.work_kind == recovery.DEADLINE, BillingWorkItem.scope_reference == str(operation.id)
            )
        )
        assert deadline.coalescing_key == f"{purchase.account_id}:{operation.id}"
    assert all(req.method == "GET" for req in transport.requests)
    await worker.aclose()


async def test_billing_retained_scope_audited_original_binding(
    retained_scenario: Scenario, postgres_session_factory: sessionmaker[Session]
) -> None:
    config, transport, sources, purchase = retained_scenario
    factory = postgres_session_factory
    current = customers.reserve_customer(factory, config, TOKEN)
    current = customers.claim_customer_send(factory, config, TOKEN, current)
    transport.customer = {"user_id": 345, "outer_id": current.outer_key}
    customers.apply_customer_read(factory, current, provider_id="345", outer_key=current.outer_key)
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    before = original(factory, operation.id)
    financial.financial_pending(factory, purchase, operation, conflict=True)
    request = resolution_request(purchase, inspect_evidence(factory, config, purchase.user_id, purchase.id), bind=True)
    requests = len(transport.requests)
    result = await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    assert result["outcome"] == "resolved"
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.state == PurchaseIntentState.LINKED and saved.account_id == purchase.account_id
    assert original(factory, operation.id) == before
    assert all(req.method == "GET" for req in transport.requests[requests:])


def test_billing_retained_scope_first_proof_after_worker_startup(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    work.ensure_sweep(factory, config)
    head(factory, config, legacy=True, proven=True)
    claim = work.claim_work(factory, config, WorkLane.LOCAL)
    assert claim is not None and claim.kind == work.SWEEP
    assert work.inspect_backlog(factory, config)[0] == 1
    work.finish_sweep(factory, claim)


@pytest.mark.parametrize("proof", ["unproven", "foreign", "ambiguous"])
async def test_billing_retained_scope_rejects_unproven_foreign_or_ambiguous_accounts(
    retained_scenario: Scenario, postgres_session_factory: sessionmaker[Session], proof: str
) -> None:
    config, transport, sources, purchase = retained_scenario
    factory = postgres_session_factory
    other_account = "unproven-storage-scope"
    with factory() as db:
        db.add(
            ExternalBillingCustomer(
                external_billing_account_id=other_account,
                user_id=purchase.user_id,
                billing_customer_key="synthetic-other-customer-" + uuid4().hex,
                provider_origin=None
                if proof == "unproven"
                else config.lbx_provider_origin
                if proof == "ambiguous"
                else "https://foreign.test",
            )
        )
        identity = uuid4()
        db.add(
            work_factory(
                kind=work.RECONCILIATION,
                key=f"{other_account}:{identity}",
                reference=str(identity),
                due=datetime.now(UTC),
            )
        )
        db.commit()
    requests = len(transport.requests)
    worker = BillingWorker(config, factory, sources.require_lbx())
    if proof == "ambiguous":
        with pytest.raises(BillingRefused, match="billing_connection_conflict"):
            await worker.tick(WorkLane.URGENT)
    else:
        assert not await worker.tick(WorkLane.URGENT)
    assert len(transport.requests) == requests
    await worker.aclose()
