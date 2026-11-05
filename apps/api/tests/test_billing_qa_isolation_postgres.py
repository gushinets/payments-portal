"""ANY-715 QA acceptance: same-tariff products remain independent. SIMULATED LBX."""

from __future__ import annotations

from collections.abc import AsyncIterator
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.sources import SourceResources, source_resources
from app.domains.billing import background_recovery, work
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import service
from app.domains.purchases.financial import financial_pending
from app.domains.purchases.contracts import Purchase
from app.jobs.billing import BillingWorker
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    BillingWorkItem,
    ExternalSubscription,
    ManualReviewCase,
    PaidAccessState,
    PurchasedAllowance,
    ExternalCreateOperationKind as Kind,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_billing_subscription_reconciliation_postgres import scenario as scenario
from apps.api.tests.test_billing_worker_postgres import historical_link
from apps.api.tests.test_any709_step3_postgres import TOKEN

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
PRODUCTS = ("proposal_ai", "brief_decoder")


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def two_products(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> AsyncIterator[tuple[PurchaseTransport, SourceResources, tuple[Purchase, Purchase], BillingWorker]]:
    transport, sources, first = scenario
    second = historical_link(postgres_session_factory, first, transport, "brief_decoder", 1)
    for subscription in transport.subscriptions:
        subscription.update(
            state=2,
            current_blocking=0,
            last_tariffication_period_start="2026-10-01",
            last_tariffication_period_end="2026-11-01",
        )
    worker = BillingWorker(step1_settings(), postgres_session_factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.URGENT)
        assert await worker.tick(WorkLane.URGENT)
        yield transport, sources, (first, second), worker
    finally:
        await worker.aclose()


def product_snapshot(factory: sessionmaker[Session], product: str) -> dict[str, object]:
    """Compare persisted facts, complete queue rows and evidence of the untouched product."""
    with factory() as db:
        subscription = dict(
            db.execute(select(ExternalSubscription.__table__).where(ExternalSubscription.product_id == product))
            .one()
            ._mapping
        )
        queue = db.execute(
            select(BillingWorkItem.__table__)
            .where(BillingWorkItem.scope_reference == str(subscription["subscription_id"]))
            .order_by(BillingWorkItem.work_item_id)
        )
        observations = db.scalars(
            select(BillingStateObservation.observation_id)
            .where(BillingStateObservation.product_id == product)
            .order_by(BillingStateObservation.observation_id)
        )
        scope = db.execute(
            select(BillingProductAccessScope.__table__).where(BillingProductAccessScope.product_id == product)
        ).one()
        return {
            "subscription": subscription,
            "queue": [dict(row._mapping) for row in queue],
            "observations": tuple(observations),
            "scope": dict(scope._mapping),
        }


def assert_scoped_inventory_hint(before: dict, after: dict) -> None:
    """Inventory may hint its proven neighbor, never change facts or queue ownership."""
    for field in ("subscription", "observations", "scope"):
        assert after[field] == before[field]
    old_jobs = {row["work_item_id"]: row for row in before["queue"]}
    new_jobs = {row["work_item_id"]: row for row in after["queue"]}
    assert new_jobs.keys() == old_jobs.keys()
    hints = 0
    for identity, previous in old_jobs.items():
        current = new_jobs[identity]
        if previous["work_kind"] != work.RECONCILIATION:
            assert current == previous
            continue
        hints += 1
        assert current["enqueue_generation"] == previous["enqueue_generation"] + 1
        assert current["priority"] == 1
        assert current["next_attempt_at"] <= min(previous["next_attempt_at"], datetime.now(UTC))
        changed = {"enqueue_generation", "priority", "next_attempt_at", "updated_at"}
        assert {key: value for key, value in current.items() if key not in changed} == {
            key: value for key, value in previous.items() if key not in changed
        }
    assert hints == 1


def subscription_for(factory: sessionmaker[Session], product: str) -> ExternalSubscription:
    with factory() as db:
        return db.scalars(select(ExternalSubscription).where(ExternalSubscription.product_id == product)).one()


def make_due(factory: sessionmaker[Session], subscription_id: UUID) -> None:
    with factory() as db:
        job = db.scalars(
            select(BillingWorkItem).where(
                BillingWorkItem.work_kind == work.RECONCILIATION,
                BillingWorkItem.scope_reference == str(subscription_id),
            )
        ).one()
        job.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        job.priority = 1
        db.commit()


def retained_history(factory: sessionmaker[Session], purchases: tuple[Purchase, Purchase]) -> tuple:
    current = tuple(service.read_purchase(factory, purchase.user_id, purchase.id) for purchase in purchases)
    assert all(purchase.held for purchase in current)
    return tuple(
        (
            purchase.accepted,
            tuple((operation.id, operation.key, operation.bound_id) for operation in purchase.operations),
        )
        for purchase in current
    )


def assert_no_access_writes(factory: sessionmaker[Session]) -> None:
    with factory() as db:
        for model in (PaidAccessState, PurchasedAllowance, AccessInvalidationOutbox):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert all(scope.primary_subscription_id is None for scope in db.scalars(select(BillingProductAccessScope)))
        assert all(item.resulting_access_revision is None for item in db.scalars(select(BillingStateObservation)))


async def review_product(
    factory: sessionmaker[Session],
    transport: PurchaseTransport,
    purchase: Purchase,
    worker: BillingWorker,
    conflict: str,
) -> None:
    if conflict == "commercial":
        subscription = subscription_for(factory, purchase.accepted.selection.product_id)
        source = next(
            row
            for row in transport.subscriptions
            if str(row["subscription_id"]) == subscription.external_subscription_id
        )
        original = deepcopy(source)
        source["services"][0]["price"] = 15
        make_due(factory, subscription.subscription_id)
        assert await worker.tick(WorkLane.URGENT)
        source.clear()
        source.update(original)
    else:
        operation = next(op for op in purchase.operations if op.kind == Kind(conflict))
        financial_pending(factory, purchase, operation, conflict=True)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("conflict", ("commercial", "agreement", "subscription"))
async def test_clean_inventory_preserves_other_product_and_payment_while_review_stays_open(
    two_products: tuple,
    postgres_session_factory: sessionmaker[Session],
    product: str,
    conflict: str,
) -> None:
    transport, sources, purchases, worker = two_products
    factory = postgres_session_factory
    reviewed = next(purchase for purchase in purchases if purchase.accepted.selection.product_id == product)
    other = next(purchase for purchase in purchases if purchase.id != reviewed.id)
    untouched = product_snapshot(factory, other.accepted.selection.product_id)
    history = retained_history(factory, purchases)
    await review_product(factory, transport, reviewed, worker, conflict)
    before = service.read_purchase(factory, reviewed.user_id, reviewed.id)
    assert before.state == "manual_review"
    reviewed_facts = product_snapshot(factory, product)
    with factory() as db:
        reviews = tuple(db.scalars(select(ManualReviewCase.review_case_id)))
    request_start = len(transport.requests)
    background_recovery.repair_batch(factory, step1_settings())
    assert await worker.tick(WorkLane.NORMAL)
    assert_scoped_inventory_hint(untouched, product_snapshot(factory, other.accepted.selection.product_id))
    after_inventory = product_snapshot(factory, product)
    assert_scoped_inventory_hint(reviewed_facts, after_inventory)
    reviewed_facts = after_inventory
    assert service.read_purchase(factory, reviewed.user_id, reviewed.id) == before
    widget = await bootstrap_account(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=other.id)
    assert widget.purchase_id == other.id and widget.credential
    assert product_snapshot(factory, product) == reviewed_facts
    assert service.read_purchase(factory, reviewed.user_id, reviewed.id) == before
    with factory() as db:
        assert tuple(db.scalars(select(ManualReviewCase.review_case_id))) == reviews
        assert all(case.case_state == "open" for case in db.scalars(select(ManualReviewCase)))
        inventory = db.scalars(
            select(BillingWorkItem).where(BillingWorkItem.work_kind == background_recovery.INVENTORY)
        ).one()
        assert inventory.last_error_classification is None and inventory.priority == 0
    assert retained_history(factory, purchases) == history
    assert all(request.method == "GET" for request in transport.requests[request_start:])
    assert_no_access_writes(factory)


@pytest.mark.parametrize("failure", ("terms", "foreign", "incomplete", "duplicate"))
async def test_reviewed_other_product_still_requires_fresh_owned_effective_term_proof(
    two_products: tuple,
    postgres_session_factory: sessionmaker[Session],
    failure: str,
) -> None:
    transport, _, purchases, worker = two_products
    factory = postgres_session_factory
    reviewed, other = purchases
    history = retained_history(factory, purchases)
    await review_product(factory, transport, reviewed, worker, "commercial")
    subscription = subscription_for(factory, reviewed.accepted.selection.product_id)
    source = next(
        row for row in transport.subscriptions if str(row["subscription_id"]) == subscription.external_subscription_id
    )
    if failure == "terms":
        source["services"][0]["price"] = 15
    elif failure == "foreign":
        next(row for row in transport.agreements if row["agreement_id"] == source["agreement_id"])["user_id"] = 999
    elif failure == "incomplete":
        source["services"] = None
    else:
        transport.subscriptions.append({**deepcopy(source), "subscription_id": 999})
    untouched = product_snapshot(factory, other.accepted.selection.product_id)
    request_start = len(transport.requests)
    background_recovery.repair_batch(factory, step1_settings())
    assert await worker.tick(WorkLane.NORMAL)
    with factory() as db:
        inventory = db.scalars(
            select(BillingWorkItem).where(BillingWorkItem.work_kind == background_recovery.INVENTORY)
        ).one()
        assert inventory.last_error_classification == (
            "inventory_incomplete" if failure == "incomplete" else "inventory_conflict"
        )
        assert inventory.priority == 1
        assert all(case.case_state == "open" for case in db.scalars(select(ManualReviewCase)))
    if failure == "incomplete":
        assert_scoped_inventory_hint(untouched, product_snapshot(factory, other.accepted.selection.product_id))
    else:
        assert service.read_purchase(factory, other.user_id, other.id).state == "manual_review"
    assert service.read_purchase(factory, reviewed.user_id, reviewed.id).state == "manual_review"
    assert retained_history(factory, purchases) == history
    assert all(request.method == "GET" for request in transport.requests[request_start:])
    assert_no_access_writes(factory)


@pytest.mark.parametrize("product", PRODUCTS)
async def test_billing_qa_product_lifecycle_isolation(
    two_products: tuple,
    postgres_session_factory: sessionmaker[Session],
    product: str,
) -> None:
    transport, _, purchases, worker = two_products
    factory = postgres_session_factory
    target = subscription_for(factory, product)
    other = next(item for item in PRODUCTS if item != product)
    untouched = product_snapshot(factory, other)
    history = retained_history(factory, purchases)
    source = next(
        item for item in transport.subscriptions if str(item["subscription_id"]) == target.external_subscription_id
    )
    request_start = len(transport.requests)
    for state, blocking, lifecycle, financial, reason in (
        (-2, 0, "inactive", "blocked", "waiting"),
        (2, 0, "active", "allowed", "active"),
        (2, 1, "active", "blocked", "financial_block"),
        (2, 3, "active", "blocked", "administrative_block"),
        (3, 0, "ended", "blocked", "ended"),
    ):
        source.update(state=state, current_blocking=blocking)
        make_due(factory, target.subscription_id)
        assert await worker.tick(WorkLane.URGENT)
        current = subscription_for(factory, product)
        assert (current.lifecycle_status, current.financial_access_status) == (lifecycle, financial)
        with factory() as db:
            evidence = db.get(BillingStateObservation, current.latest_observation_id)
            assert reason in evidence.evidence_document["reasons"]
        assert product_snapshot(factory, other) == untouched
        assert retained_history(factory, purchases) == history

    source["state"] = 2
    make_due(factory, target.subscription_id)
    assert await worker.tick(WorkLane.URGENT)
    current = subscription_for(factory, product)
    assert (current.lifecycle_status, current.financial_access_status) == ("ended", "blocked")
    with factory() as db:
        assert db.scalars(select(ManualReviewCase.reason_code)).one() == "subscription_terminal_revival_conflict"
    assert product_snapshot(factory, other) == untouched
    assert retained_history(factory, purchases) == history
    assert all(request.method == "GET" for request in transport.requests[request_start:])
    assert_no_access_writes(factory)


@pytest.mark.parametrize("product", PRODUCTS)
@pytest.mark.parametrize("failure", ("timeout", "not_found", "incomplete", "mismatch", "foreign_agreement"))
async def test_billing_qa_product_failure_expiry_and_recovery_isolation(
    two_products: tuple,
    postgres_session_factory: sessionmaker[Session],
    product: str,
    failure: str,
) -> None:
    transport, _, purchases, _ = two_products
    factory = postgres_session_factory
    target = subscription_for(factory, product)
    other = next(item for item in PRODUCTS if item != product)
    untouched = product_snapshot(factory, other)
    history = retained_history(factory, purchases)
    request_start = len(transport.requests)
    fault_enabled = True

    def respond(request: httpx.Request) -> httpx.Response:
        if fault_enabled and request.url.path.endswith("/subscriptions/" + target.external_subscription_id):
            transport.requests.append(request)
            if failure == "timeout":
                raise httpx.ReadTimeout("Simulated subscription-specific timeout", request=request)
            if failure == "not_found":
                return httpx.Response(404)
            source = deepcopy(
                next(
                    item
                    for item in transport.subscriptions
                    if str(item["subscription_id"]) == target.external_subscription_id
                )
            )
            if failure == "incomplete":
                source["total_price"] = None
            elif failure == "mismatch":
                source["services"][0]["price"] = 15
                source["total_price"] = 15
            else:
                source["agreement_id"] = 999
            return transport.response(source)
        return transport.respond(request)

    config = step1_settings()
    async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
        worker = BillingWorker(config, factory, sources.require_lbx())
        try:
            make_due(factory, target.subscription_id)
            assert await worker.tick(WorkLane.URGENT)
            failed = subscription_for(factory, product)
            assert (failed.last_authoritative_read_at, failed.projection_valid_until) == (
                target.last_authoritative_read_at,
                target.projection_valid_until,
            )
            conflict = failure in {"mismatch", "foreign_agreement"}
            with factory() as db:
                attempt = db.scalars(
                    select(BillingStateObservation)
                    .where(BillingStateObservation.subscription_id == target.subscription_id)
                    .order_by(BillingStateObservation.observed_at.desc())
                ).first()
                reasons = attempt.evidence_document["reasons"]
            assert not any(reason.startswith("customer:") for reason in reasons), reasons
            assert failed.financial_access_status == ("blocked" if conflict else "allowed"), reasons
            if not conflict:
                assert failed.latest_observation_id == target.latest_observation_id
            assert product_snapshot(factory, other) == untouched

            # Expire only this product's finite support while its source still fails.
            with factory() as db:
                row = db.get(ExternalSubscription, target.subscription_id)
                row.projection_valid_until = datetime.now(UTC) - timedelta(seconds=1)
                row.last_authoritative_read_at = row.projection_valid_until - timedelta(hours=6)
                work.schedule_reconciliation(db, row, None, complete=False)
                db.commit()
            before_local = len(transport.requests)
            assert await worker.tick(WorkLane.LOCAL)
            assert len(transport.requests) == before_local
            with factory() as db:
                boundaries = list(
                    db.scalars(
                        select(BillingStateObservation).where(
                            BillingStateObservation.evidence_schema_version == "subscription-trust-expiry:v1"
                        )
                    )
                )
                assert len(boundaries) == 1 and boundaries[0].subscription_id == target.subscription_id
            expired = subscription_for(factory, product)
            assert product_snapshot(factory, other) == untouched

            fault_enabled = False
            make_due(factory, target.subscription_id)
            assert await worker.tick(WorkLane.URGENT)
            recovered = subscription_for(factory, product)
            if conflict:
                assert recovered.financial_access_status == "blocked"
                assert recovered.commercial_access_status == "ineligible"
                assert recovered.projection_valid_until == expired.projection_valid_until
            else:
                assert recovered.financial_access_status == "allowed"
                assert recovered.projection_valid_until > expired.projection_valid_until
                assert recovered.projection_valid_until - recovered.last_authoritative_read_at == timedelta(hours=6)
            assert product_snapshot(factory, other) == untouched
            assert retained_history(factory, purchases) == history
            assert all(
                request.method == "GET"
                for request in transport.requests[request_start:]
                if not request.url.path.endswith("/auth")
            )
            assert_no_access_writes(factory)
        finally:
            await worker.aclose()
