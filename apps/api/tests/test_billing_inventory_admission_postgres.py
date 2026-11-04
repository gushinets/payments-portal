"""Inventory preserves original recovery and no-send admission; simulated LBX."""

from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import advance_purchase, recover_financial
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import PurchaseRefused
from app.jobs.billing import BillingWorker
from app.models import (
    AccessInvalidationOutbox,
    BillingStateObservation,
    BillingWorkItem,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ManualReviewCase,
    PaidAccessState,
    PurchasedAllowance,
)
from apps.api.tests.factories.reconciliation import agreement_factory, subscription_factory
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    due,
    job,
    original,
    synthetic_prepare,
)
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("inventory_first", [False, True])
@pytest.mark.parametrize("unknown", [False, True])
async def test_original_uncertain_candidate_recovers_in_either_inventory_order(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    inventory_first: bool,
    unknown: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    if unknown:
        financial.financial_pending(factory, purchase, operation)
        purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    history = original(factory, operation.id)
    recovery.repair_batch(factory, config)
    worker = BillingWorker(config, factory, sources.require_lbx())
    calls = len(transport.requests)
    try:
        if inventory_first:
            assert await worker.tick(WorkLane.NORMAL)
            assert service.read_purchase(factory, purchase.user_id, purchase.id) == purchase
            queue = job(factory, recovery.INVENTORY, purchase.customer_id)
            assert queue.last_error_classification == "inventory_incomplete" and queue.priority == 1
        assert await worker.tick(WorkLane.URGENT)
        current = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert current.state == "linked" and current.held and current.accepted == purchase.accepted
        assert next(op for op in current.operations if op.id == operation.id).state == State.BOUND
        assert original(factory, operation.id) == history
        if inventory_first:
            due(factory, recovery.INVENTORY, purchase.customer_id)
        assert await worker.tick(WorkLane.URGENT if inventory_first else WorkLane.NORMAL)
        assert job(factory, recovery.INVENTORY, purchase.customer_id).last_error_classification is None
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
            assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 1
            for model in (PaidAccessState, PurchasedAllowance, AccessInvalidationOutbox):
                assert db.scalar(select(func.count()).select_from(model)) == 0
        assert all(request.method == "GET" for request in transport.requests[calls:])
    finally:
        await worker.aclose()


@pytest.mark.parametrize("inventory_first", [False, True])
@pytest.mark.parametrize("sibling", [False, True])
async def test_deadline_only_review_preserves_original_and_sibling_inventory_recovery(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    inventory_first: bool,
    sibling: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    past = datetime.now(UTC) - timedelta(hours=3)
    with monkeypatch.context() as clock_patch:
        clock_patch.setattr(financial, "utc_now", lambda: past)
        purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    neighbor = historical_link(factory, purchase, transport, "brief_decoder", 1) if sibling else None
    # Keep this attempt focused on inventory and the original recovery job.
    with factory() as db:
        for queue in db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)):
            queue.next_attempt_at = datetime.now(UTC) + timedelta(days=1)
        db.commit()
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    history = original(factory, operation.id)
    recovery.repair_batch(factory, config)
    worker = BillingWorker(config, factory, sources.require_lbx())
    calls = len(transport.requests)
    try:
        assert await worker.tick(WorkLane.LOCAL)
        await worker.tick(WorkLane.LOCAL)
        escalated = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert escalated.state == "manual_review"
        with factory() as db:
            assert list(db.scalars(select(ManualReviewCase.reason_code))) == [
                "external_create_outcome_unknown:subscription"
            ]
        if inventory_first:
            assert await worker.tick(WorkLane.NORMAL)
            assert service.read_purchase(factory, purchase.user_id, purchase.id) == escalated
            assert job(factory, recovery.INVENTORY, purchase.customer_id).last_error_classification == (
                "inventory_incomplete"
            )
        assert await worker.tick(WorkLane.URGENT)
        if inventory_first:
            due(factory, recovery.INVENTORY, purchase.customer_id)
        assert await worker.tick(WorkLane.URGENT if inventory_first else WorkLane.NORMAL)
        current = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert current.state == "linked" and current.held and current.accepted == purchase.accepted
        assert original(factory, operation.id) == history
        assert [(op.id, op.key) for op in current.operations] == [(op.id, op.key) for op in purchase.operations]
        assert job(factory, recovery.INVENTORY, purchase.customer_id).last_error_classification is None
        if neighbor is not None:
            assert service.read_purchase(factory, neighbor.user_id, neighbor.id) == neighbor
        with factory() as db:
            cases = list(db.scalars(select(ManualReviewCase)))
            assert len(cases) == 1 and cases[0].case_state == "resolved"
            assert cases[0].resolved_by_principal == "system:financial-point-read"
            for model in (PaidAccessState, PurchasedAllowance, AccessInvalidationOutbox):
                assert db.scalar(select(func.count()).select_from(model)) == 0
        assert all(request.method == "GET" for request in transport.requests[calls:])
    finally:
        await worker.aclose()


@pytest.mark.parametrize("unsent", [False, True])
@pytest.mark.parametrize("competing,try_advance", [(False, False), (True, False), (True, True)])
async def test_no_send_purchase_can_continue_after_temporary_inventory_conflict(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    unsent: bool,
    competing: bool,
    try_advance: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    if unsent:
        purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
        operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
        financial.proven_not_sent(factory, purchase, replace(operation, may_send=True))
        transport.subscriptions.clear()  # A completed typed no-send created no subscription.
        purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    before = purchase.operations
    if competing:
        agreement = agreement_factory().model_dump()
        agreement.update(agreement_id=9000, agreement_number="unowned-agreement")
        point = subscription_factory().model_dump()
        point.update(subscription_id=9001, agreement_id=9000, total_price=100)
        point["services"][0].update(multiplicator=1, price=100)
        transport.agreements.append(agreement)
        transport.subscriptions.append(point)
    recovery.repair_batch(factory, config)
    worker = BillingWorker(config, factory, sources.require_lbx())
    calls = len(transport.requests)
    try:
        assert await worker.tick(WorkLane.NORMAL)
        admitted = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert admitted.state == purchase.state and admitted.held and admitted.accepted == purchase.accepted
        assert tuple(replace(op, fence=old.fence) for old, op in zip(before, admitted.operations)) == before
        if competing:
            for old, op in zip(before, admitted.operations):
                assert (op.fence != old.fence) == (old.state in {State.PENDING, State.PROVEN_NOT_SENT})
            queue = job(factory, recovery.INVENTORY, purchase.customer_id)
            assert queue.last_error_classification == "inventory_conflict" and queue.priority == 1
            with factory() as db:
                observation = db.scalars(
                    select(BillingStateObservation).where(
                        BillingStateObservation.evidence_schema_version == "customer-inventory:v1"
                    )
                ).one()
                assert observation.result_classification == "admission_blocked"
            if try_advance:
                with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
                    await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
                current = service.read_purchase(factory, purchase.user_id, purchase.id)
                assert current == admitted
            transport.subscriptions = [row for row in transport.subscriptions if row["subscription_id"] != 9001]
            transport.agreements = [row for row in transport.agreements if row["agreement_id"] != 9000]
            due(factory, recovery.INVENTORY, purchase.customer_id)
            assert await worker.tick(WorkLane.URGENT)
        else:
            assert admitted == purchase
        assert all(request.method == "GET" for request in transport.requests[calls:])
        result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.state == "linked" and result.held and result.accepted == purchase.accepted
        assert [(op.id, op.key) for op in result.operations] == [(op.id, op.key) for op in before]
        assert transport.creates("/agreements") == (0 if unsent else 1)
        assert transport.creates("/subscriptions") == 1
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
    finally:
        await worker.aclose()


@pytest.mark.parametrize("failure", ["duplicate", "foreign", "terms", "receipt", "competitor"])
@pytest.mark.parametrize("escalated", [False, True])
async def test_uncertain_original_inventory_still_records_real_conflicts(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    escalated: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    with monkeypatch.context() as clock_patch:
        if escalated:
            past = datetime.now(UTC) - timedelta(hours=3)
            clock_patch.setattr(financial, "utc_now", lambda: past)
        purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    if failure == "duplicate":
        transport.subscriptions.append({**deepcopy(transport.subscriptions[0]), "subscription_id": 999})
    elif failure == "foreign":
        transport.agreements[0]["user_id"] = 999
    elif failure == "terms":
        transport.subscriptions[0]["services"][0]["price"] = 101
    elif failure == "receipt":
        financial.record_receipt(factory, purchase, replace(operation, may_send=True), 999)
    else:
        agreement = {**transport.agreements[0], "agreement_id": 9000, "agreement_number": "unowned-agreement"}
        transport.agreements.append(agreement)
        transport.subscriptions.append(
            {**deepcopy(transport.subscriptions[0]), "subscription_id": 9001, "agreement_id": 9000}
        )
    recovery.repair_batch(factory, config)
    worker = BillingWorker(config, factory, sources.require_lbx())
    calls = len(transport.requests)
    try:
        if escalated:
            assert await worker.tick(WorkLane.LOCAL)
            await worker.tick(WorkLane.LOCAL)
        assert await worker.tick(WorkLane.NORMAL)
        current = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert current.state == "manual_review" and current.held
        target = next(op for op in current.operations if op.kind == Kind.SUBSCRIPTION)
        assert target.state == State.MANUAL_REVIEW and target.bound_id is None
        with factory() as db:
            reasons = set(db.scalars(select(ManualReviewCase.reason_code)))
            assert reasons == {"customer_inventory_conflict"} | (
                {"external_create_outcome_unknown:subscription"} if escalated else set()
            )
        assert all(request.method == "GET" for request in transport.requests[calls:])
    finally:
        await worker.aclose()


async def test_deadline_with_known_conflict_still_requires_audited_resolution(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    past = datetime.now(UTC) - timedelta(hours=3)
    with monkeypatch.context() as clock_patch:
        clock_patch.setattr(financial, "utc_now", lambda: past)
        purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    recovery.repair_batch(factory, config)
    worker = BillingWorker(config, factory, sources.require_lbx())
    calls = len(transport.requests)
    try:
        assert await worker.tick(WorkLane.LOCAL)
        await worker.tick(WorkLane.LOCAL)
        current = service.read_purchase(factory, purchase.user_id, purchase.id)
        operation = next(op for op in current.operations if op.kind == Kind.SUBSCRIPTION)
        financial.financial_pending(factory, current, operation, conflict=True)
        # Matching source facts cannot clear a known conflict alongside the deadline.
        assert await worker.tick(WorkLane.NORMAL)
        with pytest.raises(PurchaseRefused, match="purchase_review_required"):
            await recover_financial(sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id)
        current = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert current.state == "manual_review" and current.held and current.accepted == purchase.accepted
        assert next(op for op in current.operations if op.kind == Kind.SUBSCRIPTION).bound_id is None
        with factory() as db:
            cases = list(db.scalars(select(ManualReviewCase)))
            assert {case.reason_code for case in cases} == {
                "external_create_outcome_unknown:subscription",
                "financial_binding_conflict",
                "customer_inventory_conflict",
            }
            assert all(case.case_state == "open" for case in cases)
        assert all(request.method == "GET" for request in transport.requests[calls:])
    finally:
        await worker.aclose()
