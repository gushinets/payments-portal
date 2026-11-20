"""ANY-864 worker/PG/API regressions; external LBX and Kernel are synthetic."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
import time

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.backend_consumers import initialize_backend_consumers
from app.composition.paid_reads import paid_read_resources
from app.composition.purchases import advance_purchase, confirm_purchase, review_purchase
from app.composition.sources import source_resources
from app.domains.billing import paid_router, work
from app.domains.billing.work_contracts import WorkLane
from app.domains.catalog.link_publication import publish_product_link
from app.jobs.billing import BillingWorker
from app.main import create_app
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    ExternalSubscription,
    ManualReviewCase,
    PurchasedAllowance,
)
from apps.api.tests.factories.purchase_terms import reviewed_meaning
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.backend_consumers import backend_consumer
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed
from apps.api.tests.test_paid_access_rebase_postgres import effective
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def monthly_brief(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[Scenario]:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings(purchase_test_terms_enabled=True, paid_access_clock_skew_seconds=10)
    initialize_backend_consumers(config.model_copy(update={"backend_consumers": (backend_consumer(),)}), factory)
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(product_id="brief_decoder")),
        expected_previous_revision=0,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    )
    transport = PurchaseTransport()
    transport.pool = factory.kw["bind"].pool
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, documents, terms = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="brief_decoder"
        )
        purchase = await confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="any864-monthly",
            meaning=reviewed_meaning("brief_decoder", link.mapping_revision_id, offer.fingerprint, documents, terms),
        )
        assert purchase.accepted.technical_terms.offer.quantity == 300
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        with factory() as db:
            subscription_id = db.scalar(select(ExternalSubscription.subscription_id))
            assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) is None
            assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0
        transport.subscriptions[0].update(
            state=2,
            current_blocking=0,
            subscription_start_date="2026-11-13 00:00:00",
            subscription_instance_start_date="2026-11-13 00:00:00",
            last_tariffication_period_start="2026-11-13",
            last_tariffication_period_end="2026-12-12",
        )
        yield Scenario(factory, config, transport, sources, subscription_id)


async def run_due_worker(scenario: Scenario) -> None:
    with scenario.factory() as db:
        work.enroll_subscription(db, db.get(ExternalSubscription, scenario.subscription_id), hint=True)
        db.commit()
    worker = BillingWorker(scenario.config, scenario.factory, scenario.sources.require_lbx())
    try:
        for _ in range(20):
            if not await worker.tick(WorkLane.URGENT):
                break
        else:
            pytest.fail("ordinary worker did not drain its bounded due-work fixture")
    finally:
        await worker.aclose()


async def test_monthly_instance_worker_issues_accepted_allowance_and_preserves_cycle_history(
    monthly_brief: Scenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    scenario = monthly_brief
    await run_due_worker(scenario)
    revision, document = effective(scenario.factory)
    assert revision == 1
    assert document["grants"] == [{"product_id": "brief_decoder", "valid_until": None}]
    assert len(document["allowances"]) == 1
    allowance = document["allowances"][0]
    assert (allowance["product_id"], allowance["metric_key"], allowance["unit"], allowance["quantity"]) == (
        "brief_decoder",
        "brief_decoder.test_analyses",
        "analysis",
        300,
    )
    with scenario.factory() as db:
        row = db.scalar(select(PurchasedAllowance))
        original_id = row.allowance_id
        frozen_calendar, frozen_terms = row.calendar_document, row.terms_document
        assert row.cycle_schema_version == "calendar:v1"
        assert row.provider_cycle_key == "date:2026-11-13:2026-12-12"
        assert row.period_start is None and row.period_end is None
        assert row.provider_cycle_start is None and row.provider_cycle_end is None
        scope = db.scalar(select(BillingProductAccessScope))
        assert scope.primary_subscription_id == scenario.subscription_id
        source = db.get(ExternalSubscription, scenario.subscription_id)
        observation = db.get(BillingStateObservation, source.latest_observation_id)
        assert observation.evidence_document["calendar"]["subscription_instance_start_date"] == "2026-11-13 00:00:00"
        assert observation.evidence_document["cycle"]["anchor"] == "2026-11-13"
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == revision
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0

    app = create_app()
    monkeypatch.setattr(paid_router, "settings", scenario.config)
    before_requests = len(scenario.transport.requests)
    async with (
        paid_read_resources(scenario.config, factory=scenario.factory) as reads,
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://portal.test") as client,
    ):
        app.state.paid_reads = reads
        response = await client.get("/api/paid-access", headers={"Authorization": "Bearer " + TOKEN})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["access_revision"] == revision
        assert response.json()["allowances"] == [
            {
                "allowance_id": str(original_id),
                "product_id": "brief_decoder",
                "metric_key": "brief_decoder.test_analyses",
                "unit": "analysis",
                "quantity": 300,
                "provenance": "SIMULATED",
            }
        ]
    assert len(scenario.transport.requests) == before_requests

    scenario.transport.subscriptions[0]["subscription_instance_start_date"] = "2026-11-13T00:00:00.000000"
    await run_due_worker(scenario)
    assert effective(scenario.factory) == (revision, document)

    scenario.transport.subscriptions[0]["current_blocking"] = 1
    await run_due_worker(scenario)
    assert effective(scenario.factory) == (revision + 1, {"grants": [], "allowances": []})
    scenario.transport.subscriptions[0]["current_blocking"] = 0
    await run_due_worker(scenario)
    assert effective(scenario.factory) == (revision + 2, document)

    scenario.transport.subscriptions[0].update(
        last_tariffication_period_start="2026-12-13", last_tariffication_period_end="2027-01-12"
    )
    await run_due_worker(scenario)
    later_revision, later = effective(scenario.factory)
    assert later_revision == revision + 3
    assert len(later["allowances"]) == 1
    assert later["allowances"][0]["allowance_id"] != allowance["allowance_id"]
    assert later["allowances"][0]["quantity"] == 300
    await run_due_worker(scenario)
    assert effective(scenario.factory) == (later_revision, later)
    with scenario.factory() as db:
        original = db.get(PurchasedAllowance, original_id)
        assert (original.calendar_document, original.terms_document, original.quantity) == (
            frozen_calendar,
            frozen_terms,
            300,
        )
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 2
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == later_revision
    assert [scenario.transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")] == [1, 1, 1]


async def test_monthly_instance_worker_resolves_prior_cycle_review_from_fresh_proof(monthly_brief: Scenario) -> None:
    scenario = monthly_brief
    scenario.transport.subscriptions[0]["subscription_instance_start_date"] = "2026-11-13 12:00:00"
    await run_due_worker(scenario)
    revision, before = effective(scenario.factory)
    assert revision == 1 and len(before["grants"]) == 1 and before["allowances"] == []
    with scenario.factory() as db:
        review = db.scalars(select(ManualReviewCase)).one()
        review_id = review.review_case_id
        assert review.reason_code == "allowance_cycle_conflict" and review.case_state == "open"
    scenario.transport.subscriptions[0]["subscription_instance_start_date"] = "2026-11-13 00:00:00"
    await run_due_worker(scenario)
    current_revision, current = effective(scenario.factory)
    assert current_revision == revision + 1
    assert current["grants"] == before["grants"] and len(current["allowances"]) == 1
    assert current["allowances"][0]["quantity"] == 300
    with scenario.factory() as db:
        review = db.get(ManualReviewCase, review_id)
        assert review.case_state == "resolved" and review.resolved_by_principal == "system:original-cycle-proof"
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 1
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1
    await run_due_worker(scenario)
    assert effective(scenario.factory) == (current_revision, current)


@pytest.mark.parametrize(
    "sentinel",
    ["1970-01-01T00:00:00", "1970-01-01 00:00:00.000000", "1970-01-01T00:00:00.0"],
)
async def test_epoch_sentinel_worker_never_issues_or_resets_allowance(monthly_brief: Scenario, sentinel: str) -> None:
    scenario = monthly_brief
    point = scenario.transport.subscriptions[0]
    point.update(
        subscription_start_date="2026-11-01 00:00:00",
        subscription_instance_start_date=sentinel,
        last_tariffication_period_start="2026-11-01",
        last_tariffication_period_end="2026-11-30",
    )
    await run_due_worker(scenario)
    revision, document = effective(scenario.factory)
    assert len(document["grants"]) == 1 and document["allowances"] == []
    with scenario.factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0
        source = db.get(ExternalSubscription, scenario.subscription_id)
        observation = db.get(BillingStateObservation, source.latest_observation_id)
        assert observation.evidence_document["calendar"]["subscription_instance_start_date"] == sentinel
        assert observation.evidence_document["cycle"] is None
        assert db.scalars(select(ManualReviewCase.reason_code)).one() == "allowance_cycle_conflict"
    await run_due_worker(scenario)
    assert effective(scenario.factory) == (revision, document)

    point["subscription_instance_start_date"] = "2026-11-01 00:00:00"
    await run_due_worker(scenario)
    _, valid = effective(scenario.factory)
    assert len(valid["allowances"]) == 1 and valid["allowances"][0]["quantity"] == 300
    with scenario.factory() as db:
        original = db.scalars(select(PurchasedAllowance)).one()
        original_id, original_calendar = original.allowance_id, original.calendar_document

    point.update(
        subscription_instance_start_date=sentinel,
        last_tariffication_period_start="2026-12-01",
        last_tariffication_period_end="2026-12-31",
    )
    await run_due_worker(scenario)
    assert effective(scenario.factory)[1] == document
    with scenario.factory() as db:
        original = db.scalars(select(PurchasedAllowance)).one()
        assert (original.allowance_id, original.calendar_document, original.quantity) == (
            original_id,
            original_calendar,
            300,
        )
