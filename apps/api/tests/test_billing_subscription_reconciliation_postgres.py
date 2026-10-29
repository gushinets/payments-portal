"""Disposable PostgreSQL and synthetic LBX: proof/apply, history and writer races."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from collections.abc import AsyncIterator

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.composition.purchases import advance_purchase
from app.composition.purchase_observation import prepared_subscription_observation as _observation
from app.composition.reconciliation import reconcile_subscription
from app.composition.sources import SourceResources, source_resources
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import apply_customer_read
from app.domains.billing.reconciliation import claim_reconciliation, apply_reconciliation
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase
from app.infrastructure.preflight import PreflightAdmission, PreflightPolicy
from app.integrations.lbx.financial import Subscription
from app.integrations.lbx.reconciliation import read_subscription_proof
from app.models import (
    BillingProductAccessScope,
    BillingPurchaseScopeHold,
    BillingStateObservation,
    ExternalSubscription,
    ManualReviewCase,
    PaidAccessState,
    PurchasedAllowance,
    PurchaseIntent,
    PurchaseIntentState,
    ExternalCreateOperationKind as Kind,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_step3_postgres import setup_purchase, accept, TOKEN

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def scenario(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> AsyncIterator[tuple[PurchaseTransport, SourceResources, Purchase]]:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    async with source_resources(
        step1_settings(),
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        purchase = await advance_purchase(
            sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        yield transport, sources, purchase


def snapshot(factory: sessionmaker[Session]) -> tuple:
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        return (
            sub.subscription_id,
            sub.lifecycle_status,
            sub.financial_access_status,
            sub.commercial_access_status,
            sub.last_authoritative_read_at,
            sub.projection_valid_until,
            sub.latest_observation_id,
        )


def activate(transport: PurchaseTransport) -> None:
    transport.subscriptions[0].update(
        {"state": 2, "last_tariffication_period_start": "2026-10-01", "last_tariffication_period_end": "2026-11-01"}
    )


async def run(sources: SourceResources, factory: sessionmaker[Session]) -> BillingStateObservation:
    observation_id = await reconcile_subscription(
        sources.require_lbx(), sources.billing, step1_settings(), factory=factory, subscription_id=snapshot(factory)[0]
    )
    with factory() as db:
        return db.get(BillingStateObservation, observation_id)


async def test_billing_subscription_reconciliation_lifecycle_history_and_minimum_reads(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    before = len(transport.requests)
    waiting = await run(sources, factory)
    assert waiting.evidence_document["financial"] == "blocked"
    assert waiting.evidence_document["calendar_complete"] is False
    requests = [request for request in transport.requests[before:] if not request.url.path.endswith("/auth")]
    assert [(request.method, request.url.path.rsplit("/", 2)[-2:]) for request in requests] == [
        ("GET", ["users", "345"]),
        ("GET", ["agreements", "456"]),
        ("GET", ["tariffs", "701"]),
        ("GET", ["subscriptions", "567"]),
    ]
    with factory() as db:
        scope = db.scalar(select(BillingProductAccessScope))
        assert scope.primary_subscription_id is None and waiting.access_scope_id == scope.access_scope_id
    activate(transport)
    transport.change_price()
    transport.subscriptions[0]["services"][0]["tariff_price"] = 999
    first = await run(sources, factory)
    assert first.evidence_document["financial"] == "allowed"
    state = snapshot(factory)
    assert state[5] - state[4] == timedelta(hours=6)
    assert state[4].isoformat() == first.evidence_document["read_started_at"]
    for block, reason in ((1, "financial_block"), (3, "administrative_block")):
        transport.subscriptions[0]["current_blocking"] = block
        evidence = await run(sources, factory)
        assert reason in evidence.evidence_document["reasons"] and snapshot(factory)[2] == "blocked"
    transport.subscriptions[0].update(
        {
            "current_blocking": 0,
            "last_tariffication_period_start": "2026-11-01",
            "last_tariffication_period_end": "2026-12-01",
        }
    )
    renewal = await run(sources, factory)
    assert renewal.evidence_document["financial"] == "allowed"
    assert renewal.evidence_document["calendar"]["last_tariffication_period_start"] == "2026-11-01"
    transport.subscriptions[0]["state"] = 3
    transport.agreements[0]["close_date"] = "2026-11-05"
    ended = await run(sources, factory)
    assert ended.evidence_document["lifecycle"] == "ended"
    assert snapshot(factory)[1:3] == ("ended", "blocked")
    transport.agreements[0]["close_date"] = None
    transport.subscriptions[0]["state"] = 2
    revival = await run(sources, factory)
    assert revival.result_classification == "subscription_terminal_revival_conflict"
    assert snapshot(factory)[1:4] == ("ended", "blocked", "ineligible")
    current = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert current.id == purchase.id and current.accepted == purchase.accepted and current.held
    assert [(op.id, op.key, op.bound_id) for op in current.operations] == [
        (op.id, op.key, op.bound_id) for op in purchase.operations
    ]
    with factory() as db:
        for model in (PaidAccessState, PurchasedAllowance):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 1
        assert all(item.resulting_access_revision is None for item in db.scalars(select(BillingStateObservation)))


async def test_billing_subscription_reconciliation_incomplete_outage_and_negative(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    activate(transport)
    await run(sources, factory)
    good = snapshot(factory)
    for change in ({"total_price": None}, {"state": 999}, {"last_tariffication_period_end": None}):
        original = dict(transport.subscriptions[0])
        transport.subscriptions[0].update(change)
        attempt = await run(sources, factory)
        assert attempt.completeness_classification == "incomplete"
        assert snapshot(factory) == good
        transport.subscriptions[0] = original
    from app.integrations.lbx.errors import LbxUnavailable

    original_get = sources.require_lbx().get_tariff

    async def unavailable(**kwargs: object) -> None:
        raise LbxUnavailable()

    monkeypatch.setattr(sources.require_lbx(), "get_tariff", unavailable)
    await run(sources, factory)
    assert snapshot(factory) == good
    # Advance the controlled clock beyond the old trust deadline. Provider
    # failure still cannot move it or invent a grace interval.
    from app.infrastructure.queries import billing_reconciliation as reconciliation_queries
    from app.integrations.lbx import reconciliation as lbx_reconciliation

    def later() -> datetime:
        return datetime.now(UTC) + timedelta(hours=7)

    monkeypatch.setattr(reconciliation_queries, "database_now", lambda db: later())
    monkeypatch.setattr(lbx_reconciliation, "utc_now", later)
    await run(sources, factory)
    assert snapshot(factory) == good and good[5] < later()
    transport.subscriptions[0]["current_blocking"] = 1
    negative = await run(sources, factory)
    assert negative.completeness_classification == "incomplete"
    assert snapshot(factory)[2] == "blocked" and snapshot(factory)[4:6] == good[4:6]
    monkeypatch.setattr(sources.require_lbx(), "get_tariff", original_get)
    transport.subscriptions[0]["current_blocking"] = 0
    await run(sources, factory)
    assert snapshot(factory)[2] == "allowed"


async def test_billing_subscription_reconciliation_known_review_and_effective_mismatch(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    await run(sources, factory)
    trusted = snapshot(factory)
    transport.subscriptions[0]["services"][0]["price"] = 15
    mismatch = await run(sources, factory)
    assert mismatch.result_classification == "subscription_commercial_mismatch"
    assert snapshot(factory)[2:4] == ("blocked", "ineligible")
    assert snapshot(factory)[4:6] == trusted[4:6]
    transport.subscriptions[0]["services"][0]["price"] = 100
    matched = await run(sources, factory)
    assert matched.result_classification == "review_required" and snapshot(factory)[2] == "blocked"
    with pytest.raises(BillingRefused, match="purchase_review_required"):
        await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=purchase.id)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 1
        assert db.get(PurchaseIntent, purchase.id).state == PurchaseIntentState.MANUAL_REVIEW


async def test_billing_subscription_reconciliation_preserves_preparation_with_competing_writers(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    subject = claim_reconciliation(factory, step1_settings(), snapshot(factory)[0], io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        proof = await read_subscription_proof(sources.require_lbx(), subject, step1_settings(), budget=budget)
    # Preparation can rotate its send fences during the read without changing
    # permanent identity. Either writer order must preserve authoritative facts.
    await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=purchase.id)
    apply_reconciliation(factory, subject, proof)
    good = snapshot(factory)
    transport.subscriptions[0]["state"] = -2
    await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert snapshot(factory) == good
    latest = service.read_purchase(factory, purchase.user_id, purchase.id)
    op = next(op for op in latest.operations if op.kind == Kind.SUBSCRIPTION)
    subject = claim_reconciliation(factory, step1_settings(), good[0], io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        proof = await read_subscription_proof(sources.require_lbx(), subject, step1_settings(), budget=budget)
    prepared = _observation(Subscription.model_validate(transport.effective_subscription()), latest)
    await asyncio.gather(
        run_in_threadpool(apply_reconciliation, factory, subject, proof),
        run_in_threadpool(financial.bind_financial, factory, latest, op, 567, observation=prepared),
    )
    result = snapshot(factory)
    assert result[1:3] == ("inactive", "blocked")
    with factory() as db:
        assert db.get(BillingStateObservation, result[-1]).evidence_schema_version == "subscription-reconciliation:v1"


async def test_billing_subscription_reconciliation_fences_and_original_customer_restoration(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    activate(transport)
    sub_id = snapshot(factory)[0]
    first = claim_reconciliation(factory, step1_settings(), sub_id, io_timeout_seconds=60)
    with pytest.raises(BillingRefused, match="subscription_reconciliation_busy"):
        claim_reconciliation(factory, step1_settings(), sub_id, io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        old_proof = await read_subscription_proof(sources.require_lbx(), first, step1_settings(), budget=budget)
    with factory() as db:
        db.get(ExternalSubscription, sub_id).reconciliation_lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    second = claim_reconciliation(factory, step1_settings(), sub_id, io_timeout_seconds=60)
    assert second.fence > first.fence and second.owner != first.owner
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        apply_reconciliation(factory, first, old_proof)
    async with sources.billing.operation() as budget:
        fresh_proof = await read_subscription_proof(sources.require_lbx(), second, step1_settings(), budget=budget)
    apply_reconciliation(factory, second, fresh_proof)
    transport.customer["outer_id"] = "foreign-key"
    conflict = await run(sources, factory)
    assert "customer_identity_conflict" in conflict.evidence_document["reasons"]
    assert snapshot(factory)[2:4] == ("blocked", "ineligible")
    with factory() as db:
        assert not list(db.scalars(select(ManualReviewCase).where(ManualReviewCase.scope_kind == "subscription")))
    # Reuse the approved customer restoration policy, never generalize it to a
    # financial conflict. An explicit account open obtains this current snapshot.
    from app.domains.billing.customers import reserve_customer

    customer = reserve_customer(factory, step1_settings(), TOKEN)
    transport.customer["outer_id"] = customer.outer_key
    apply_customer_read(factory, customer, provider_id="345", outer_key=customer.outer_key)
    await run(sources, factory)
    assert snapshot(factory)[2:4] == ("allowed", "eligible")


async def test_billing_subscription_reconciliation_preexisting_financial_review(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    good = snapshot(factory)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    with factory() as db:
        db.add(
            ManualReviewCase(
                reason_code="financial_binding_conflict",
                scope_kind="create_operation",
                scope_reference=str(op.id),
                evidence_schema_version="financial-review:v1",
                evidence_document={"purchase_intent_id": str(purchase.id)},
                case_state="open",
            )
        )
        db.commit()
    evidence = await run(sources, factory)
    assert evidence.result_classification == "review_required"
    assert snapshot(factory)[2:4] == ("blocked", "ineligible")
    assert snapshot(factory)[4:6] == good[4:6]
    with factory() as db:
        assert db.scalar(select(ManualReviewCase)).case_state == "open"


async def test_billing_subscription_reconciliation_total_budget_and_404(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    activate(transport)
    await run(sources, factory)
    good = snapshot(factory)
    original_get = sources.require_lbx().get_user

    async def slow(**kwargs: object) -> None:
        await asyncio.sleep(0.2)

    monkeypatch.setattr(sources.require_lbx(), "get_user", slow)
    admission = PreflightAdmission(PreflightPolicy(0.06, 0.01, 1, 0))
    try:
        observation_id = await reconcile_subscription(
            sources.require_lbx(), admission, step1_settings(), factory=factory, subscription_id=good[0]
        )
    finally:
        await admission.aclose()
    assert snapshot(factory) == good
    with factory() as db:
        evidence = db.get(BillingStateObservation, observation_id)
        assert evidence.evidence_document["reasons"] == ["read_budget_exhausted"]
    monkeypatch.setattr(sources.require_lbx(), "get_user", original_get)
    # A real decoded HTTP 404 remains incomplete source evidence, not deletion.
    async with source_resources(
        step1_settings(),
        lbx_transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(404) if request.url.path.endswith("/subscriptions/567") else transport.respond(request)
            )
        ),
    ) as other:
        evidence = await run(other, factory)
        assert evidence.completeness_classification == "incomplete"
        assert snapshot(factory) == good


async def test_billing_subscription_reconciliation_contradictory_times_preserve_prior_trust(
    scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    activate(transport)
    await run(sources, factory)
    before = snapshot(factory)
    transport.subscriptions[0].update(
        subscription_instance_start_date="2026-10-01 12:00:00",
        last_tariffication_period_start="2026-10-01 00:00:00",
        last_tariffication_period_end="2026-11-01 12:00:00",
        subscription_instance_end_date="2026-11-01 00:00:00",
    )
    observation = await run(sources, factory)
    assert observation.completeness_classification == "incomplete"
    assert observation.evidence_document["calendar_complete"] is False
    assert snapshot(factory) == before
