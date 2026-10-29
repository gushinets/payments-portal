"""REV-5–REV-7 regressions: disposable PostgreSQL and SIMULATED GET-only LBX."""

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import reconcile_purchase, resolve_review
from app.composition.reconciliation import reconcile_subscription
from app.core.errors import AppError
from app.core.time import utc_now
from app.domains.billing import operator_review, work
from app.domains.billing.operator_contracts import ResolutionRequest, ReviewResolution
from app.domains.billing.work_contracts import WorkLane
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase
from app.infrastructure.preflight import PreflightAdmission, PreflightBudget, PreflightPolicy
from app.integrations.lbx.customer import LbxUser
from app.integrations.lbx.errors import LbxScopeMismatch
from app.jobs.billing import BillingWorker
from app.models import (
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ManualReviewCase,
)
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    original,
    synthetic_prepare,
)
from apps.api.tests.test_billing_recovery_cli_postgres import evidence, unchanged_authority, PRINCIPAL

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("result", ["timely_value", "timely_scope_error", "late_value", "late_scope_error"])
async def test_billing_recovery_cli_preserves_only_timely_identity_conflicts(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    result: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    await reconcile_purchase(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        sub_id, trust = sub.subscription_id, (sub.last_authoritative_read_at, sub.projection_valid_until)

    async def customer(**kwargs: object) -> LbxUser:
        if result.startswith("late"):
            await asyncio.sleep(0.2)
        if result.endswith("scope_error"):
            raise LbxScopeMismatch()
        return LbxUser(user_id=345, outer_id="proven-foreign-key")

    async def subscription(*, budget: PreflightBudget, **kwargs: object) -> None:
        async def slow() -> None:
            await asyncio.sleep(1)

        await budget.run(slow)

    monkeypatch.setattr(sources.require_lbx(), "get_user", customer)
    monkeypatch.setattr(sources.require_lbx(), "get_subscription", subscription)
    admission = PreflightAdmission(PreflightPolicy(0.15, 0.03, 1, 0))
    try:
        await reconcile_subscription(
            sources.require_lbx(), admission, step1_settings(), factory=factory, subscription_id=sub_id
        )
    finally:
        await admission.aclose()
    with factory() as db:
        customer_row = db.get(ExternalBillingCustomer, purchase.customer_id)
        sub = db.get(ExternalSubscription, sub_id)
        assert (sub.last_authoritative_read_at, sub.projection_valid_until) == trust
        if result.startswith("timely"):
            assert customer_row.binding_state == Binding.IDENTITY_CONFLICT
            assert sub.financial_access_status == "blocked"
        else:
            assert customer_row.binding_state == Binding.BOUND
            assert sub.financial_access_status == "allowed"
    unchanged_authority(factory, purchase)


def escalated_conflict(
    scenario: tuple, factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> tuple[Purchase, ResolutionRequest]:
    transport, _, purchase = scenario
    clock = financial.utc_now
    monkeypatch.setattr(financial, "utc_now", lambda: clock() - timedelta(hours=3))
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    monkeypatch.setattr(financial, "utc_now", clock)
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.financial_pending(factory, purchase, operation)
    purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.financial_pending(factory, purchase, operation, conflict=True)
    state = evidence(factory, purchase)
    assert {case["reason"] for case in state["reviews"] if case["state"] == "open"} == {
        "external_create_outcome_unknown:subscription",
        "financial_binding_conflict",
    }
    state["reviews"] = [case for case in state["reviews"] if case["reason"] == "financial_binding_conflict"]
    return purchase, resolution_request(purchase, state, bind=True)


@pytest.mark.parametrize("reversed_timestamps", [False, True])
async def test_billing_recovery_cli_bind_after_deadline_audits_related_case_and_replays(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    reversed_timestamps: bool,
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    purchase, request = escalated_conflict(background_scenario, factory, monkeypatch)
    if reversed_timestamps:
        # PostgreSQL now() reflects transaction start. Lock acquisition and
        # the actual transition may occur in a different transaction order.
        with factory() as db:
            case = db.get(ManualReviewCase, request.case_id)
            previous = db.scalar(select(ManualReviewCase).where(ManualReviewCase.review_case_id != request.case_id))
            previous.created_at = case.created_at + timedelta(seconds=1)
            db.commit()
    before = original(factory, request.operation_id)
    count = len(transport.requests)
    await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert original(factory, request.operation_id) == before
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert next(op for op in saved.operations if op.id == request.operation_id).state == State.BOUND
    with factory() as db:
        cases = list(db.scalars(select(ManualReviewCase)))
        assert len(cases) == 2
        for case in cases:
            assert case.case_state == "resolved" and case.resolved_by_principal == PRINCIPAL
            assert case.resolution_document["reason"] == request.reason
            assert case.resolution_document["reference"] == request.reference
            assert case.resolution_document["proof"]["discovery"] == "unique_complete"
            assert case.resolution_document["after"]["external_subscription_id"] == "567"
        related = next(case for case in cases if case.review_case_id != request.case_id)
        assert related.resolution_document["related_to_review_case_id"] == str(request.case_id)
    assert all(req.method == "GET" for req in transport.requests[count:])
    count = len(transport.requests)
    assert (await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL))[
        "outcome"
    ] == "already_resolved"
    assert len(transport.requests) == count
    unchanged_authority(factory, purchase)


@pytest.mark.parametrize("change", ["stale_related", "missing_history", "foreign_related", "audit_failure"])
async def test_billing_recovery_cli_related_deadline_refusals_and_atomic_rollback(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    _, sources, _ = background_scenario
    factory = postgres_session_factory
    purchase, request = escalated_conflict(background_scenario, factory, monkeypatch)
    if change == "stale_related":
        prepared = operator_review.prepare_resolution(
            factory, step1_settings(), request, PRINCIPAL, io_timeout_seconds=60
        )
        assert isinstance(prepared, ReviewResolution)
        monkeypatch.setattr("app.composition.billing_operator.prepare_resolution", lambda *args, **kwargs: prepared)
    if change != "audit_failure":
        with factory() as db:
            related = db.scalar(select(ManualReviewCase).where(ManualReviewCase.review_case_id != request.case_id))
            document = {**related.evidence_document}
            if change == "missing_history":
                document.pop("operation_state_at_conflict")
            elif change == "foreign_related":
                document["create_operation_id"] = str(purchase.id)
            else:
                document["changed_after_prepare"] = True
            related.evidence_document = document
            db.commit()
    else:

        def fail(*args: object, **kwargs: object) -> None:
            raise RuntimeError("audit storage failure")

        monkeypatch.setattr(operator_review, "audit_original_binding", fail)
    with pytest.raises(RuntimeError if change == "audit_failure" else AppError):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    with factory() as db:
        assert all(
            case.case_state == "open" and case.resolution_document is None
            for case in db.scalars(select(ManualReviewCase))
        )
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert next(op for op in saved.operations if op.id == request.operation_id).bound_id is None
    unchanged_authority(factory, purchase)


@pytest.mark.parametrize("result", ["blocked", "incomplete", "allowed"])
@pytest.mark.parametrize("running", [False, True])
async def test_billing_recovery_cli_schedules_urgent_without_losing_worker_ownership(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], result: str, running: bool
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.URGENT)
        with factory() as db:
            job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
            assert job.priority == 0
            job_id = job.work_item_id
            if running:
                job.next_attempt_at = utc_now()
                db.commit()
        claim = work.claim_work(factory, step1_settings(), WorkLane.NORMAL) if running else None
        assert not running or claim is not None
        with factory() as db:
            if result == "allowed":
                work.enroll_subscription(db, db.scalar(select(ExternalSubscription)), hint=True)
                db.commit()
            job = db.get(BillingWorkItem, job_id)
            before = (job.lease_owner, job.lease_expires_at, job.enqueue_generation)
        if result == "blocked":
            transport.subscriptions[0]["current_blocking"] = 1
        elif result == "incomplete":
            transport.subscriptions[0]["total_price"] = None
        await reconcile_purchase(
            sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
        with factory() as db:
            job = db.get(BillingWorkItem, job_id)
            assert (job.lease_owner, job.lease_expires_at) == before[:2]
            assert job.priority == 1 and (as_utc(job.next_attempt_at) - utc_now()).total_seconds() <= 300
            assert job.enqueue_generation == before[2] + (result != "allowed")
            if claim:
                work.finish(db, work.verify_claim(db, claim), claim, due=utc_now() + timedelta(minutes=15))
                db.commit()
        unchanged_authority(factory, purchase)
    finally:
        await worker.aclose()


async def test_billing_recovery_cli_urgent_cadence_includes_elapsed_source_read(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    synthetic_prepare(factory, transport, purchase, uncertain=False)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.URGENT)
        now = utc_now()
        with factory() as db:
            work.schedule_reconciliation(
                db,
                db.scalar(select(ExternalSubscription)),
                None,
                complete=False,
                attempt_started_at=now - timedelta(minutes=4),
            )
            db.commit()
        with factory() as db:
            job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
            assert job.priority == 1 and as_utc(job.next_attempt_at) <= now + timedelta(minutes=1)
    finally:
        await worker.aclose()
