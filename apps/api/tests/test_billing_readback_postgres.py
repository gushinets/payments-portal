"""Actual claim/read/apply races with controlled clocks and disposable PostgreSQL."""

from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, func
from sqlalchemy.orm import Session, sessionmaker

from app.composition.readback import apply_bound_readback
from app.composition.sources import SourceResources
from app.domains.purchases.contracts import Purchase
from app.composition.purchase_observation import prepared_subscription_observation
from app.domains.billing import readback, readback_binding, work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.readback_contracts import (
    BoundReadbackSubject,
    OriginalCreateReadbackSubject,
    NEGATIVE_SCHEMA,
    ReadbackApplyResult as Result,
    ReadbackRecheck,
    ScopedReadbackFinding,
)
from app.domains.billing.reconciliation import claim_reconciliation, apply_reconciliation
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import financial, service
from app.infrastructure.preflight import PreflightDeadlineExceeded
from app.integrations.lbx.financial import Subscription
from app.integrations.lbx.readback import read_bound_finding, read_original_create_proof
from app.integrations.lbx.reconciliation import read_subscription_proof
from app.models import (
    BillingStateObservation,
    BillingWorkItem,
    BillingPurchaseScopeHold,
    ExternalSubscription,
    ExternalCreateOperation,
    ManualReviewCase,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    PaidAccessState,
    PurchasedAllowance,
    AccessInvalidationOutbox,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.factories.billing_readback import observation_factory
from apps.api.tests.test_billing_subscription_reconciliation_postgres import (
    scenario as scenario,
    anyio_backend as anyio_backend,
    snapshot,
    activate,
    run,
)
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    synthetic_prepare,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


class Clock:
    def __init__(self) -> None:
        self.now = datetime.now(UTC) + timedelta(seconds=1)

    def tick(self, seconds: int = 1) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    from app.infrastructure.queries import billing_reconciliation as queries
    from app.integrations.lbx import readback as lbx_readback, reconciliation as lbx_reconciliation

    clock = Clock()
    monkeypatch.setattr(queries, "database_now", lambda db: clock.now)
    monkeypatch.setattr(lbx_readback, "utc_now", lambda: clock.now)
    monkeypatch.setattr(lbx_reconciliation, "utc_now", lambda: clock.now)
    return clock


def capture(factory: sessionmaker[Session], purchase: Purchase, clock: Clock) -> BoundReadbackSubject:
    subject = readback.capture_readback(factory, step1_settings(), purchase, deadline=clock.now + timedelta(minutes=5))
    assert isinstance(subject, BoundReadbackSubject)
    return subject


async def finding(sources: SourceResources, subject: BoundReadbackSubject, clock: Clock) -> ScopedReadbackFinding:
    clock.tick()
    async with sources.billing.operation() as budget:
        return await read_bound_finding(sources.require_lbx(), subject, budget=budget)


def persisted(factory: sessionmaker[Session]) -> tuple:
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        observations = tuple(
            db.scalars(select(BillingStateObservation.observation_id).order_by(BillingStateObservation.observation_id))
        )
        queues = tuple(
            (
                row.work_kind,
                row.enqueue_generation,
                row.lease_owner,
                row.work_state,
                row.next_attempt_at,
                row.payload_document,
            )
            for row in db.scalars(select(BillingWorkItem).order_by(BillingWorkItem.work_item_id))
        )
        return snapshot(factory), sub.reconciliation_fencing_token, sub.reconciliation_lease_owner, observations, queues


def assert_negative(factory: sessionmaker[Session], trusted: tuple) -> None:
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        evidence = db.get(BillingStateObservation, sub.latest_observation_id)
        assert sub.financial_access_status == "blocked"
        assert (sub.last_authoritative_read_at, sub.projection_valid_until) == trusted[4:6]
        assert evidence.evidence_schema_version == NEGATIVE_SCHEMA
        assert evidence.completeness_classification == "negative_only"
        assert evidence.observed_at.isoformat() == evidence.evidence_document["read_finished_at"]
        assert evidence.evidence_document["commercial"] == "INCOMPLETE"
        assert sub.reconciliation_lease_owner is None and sub.reconciliation_lease_expires_at is None
        queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == "subscription_reconciliation"))
        assert queue.priority == 1
        from app.infrastructure.queries.billing_reconciliation import database_now

        assert queue.next_attempt_at <= database_now(db)
        if sub.projection_valid_until > sub.last_authoritative_read_at:
            expiry = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == "subscription_trust_expiry"))
            assert expiry.next_attempt_at == sub.projection_valid_until
            assert expiry.payload_document["supporting_observation_id"] == str(sub.latest_observation_id)
        assert not list(db.scalars(select(ManualReviewCase)))
        for model in (PaidAccessState, PurchasedAllowance):
            assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize(
    "order", ["negative_then_old_active", "new_positive_then_stale_negative", "old_read_late_commit"]
)
async def test_readback_three_source_window_races(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, order: str
) -> None:
    transport, sources, purchase = scenario
    factory, config = postgres_session_factory, step1_settings()
    clock.tick()
    activate(transport)
    await run(sources, factory)
    trusted = snapshot(factory)
    if order != "new_positive_then_stale_negative":
        clock.tick()
        positive_subject = claim_reconciliation(factory, config, trusted[0], io_timeout_seconds=600)
        async with sources.billing.operation() as budget:
            positive = await read_subscription_proof(sources.require_lbx(), positive_subject, config, budget=budget)
    clock.tick()
    subject = capture(factory, purchase, clock)
    transport.subscriptions[0].update(current_blocking=1, total_price=None)
    negative = await finding(sources, subject, clock)
    if order == "new_positive_then_stale_negative":
        clock.tick()
        transport.subscriptions[0].update(current_blocking=0, total_price=100)
        positive_subject = claim_reconciliation(factory, config, trusted[0], io_timeout_seconds=600)
        async with sources.billing.operation() as budget:
            positive = await read_subscription_proof(sources.require_lbx(), positive_subject, config, budget=budget)
        clock.tick()
        apply_reconciliation(factory, positive_subject, positive)
        before = persisted(factory)
        assert readback.apply_readback(factory, config, negative) == Result.SUPERSEDED
        assert persisted(factory) == before
        return
    if order == "old_read_late_commit":
        clock.tick()
        apply_reconciliation(factory, positive_subject, positive)
        assert snapshot(factory)[-1] != subject.supporting_observation_id
        trusted = snapshot(factory)
    clock.tick()
    assert readback.apply_readback(factory, config, negative) == Result.APPLIED_NEGATIVE
    assert_negative(factory, trusted)
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        apply_reconciliation(factory, positive_subject, positive)


@pytest.mark.parametrize(
    "case", ["binding", "hold", "consent", "customer_fence", "customer_key", "origin", "operation_key"]
)
async def test_readback_rechecks_original_provenance(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, case: str
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    transport.subscriptions[0]["current_blocking"] = 1
    subject = capture(factory, purchase, clock)
    proof = await finding(sources, subject, clock)
    with factory() as db:
        if case == "binding":
            db.get(ExternalSubscription, subject.subscription_id).external_subscription_id = "568"
        elif case == "hold":
            db.delete(db.get(BillingPurchaseScopeHold, (purchase.user_id, purchase.accepted.selection.product_id)))
        elif case == "consent":
            # Legal evidence is append-only in PostgreSQL. A different retained
            # event witness must be refused without mutating that evidence.
            proof = replace(proof, subject=replace(subject, legal_acceptance_event_id=uuid4()))
        elif case == "customer_key":
            proof = replace(proof, subject=replace(subject, customer=replace(subject.customer, outer_key="changed")))
        elif case == "origin":
            changed_purchase = replace(
                purchase, accepted=purchase.accepted.model_copy(update={"provider_origin": "https://foreign.test"})
            )
            proof = replace(proof, subject=replace(subject, purchase=changed_purchase))
        elif case == "operation_key":
            changed_purchase = replace(
                purchase, operations=(replace(purchase.operations[0], key="changed"), *purchase.operations[1:])
            )
            proof = replace(proof, subject=replace(subject, purchase=changed_purchase))
        else:
            db.get(ExternalCreateOperation, subject.customer.operation_id).send_fence = uuid4()
        db.commit()
    before = persisted(factory)
    with pytest.raises(BillingRefused):
        readback.apply_readback(factory, step1_settings(), proof)
    assert persisted(factory) == before


@pytest.mark.parametrize(
    "case", ["fence", "overlap", "legacy_overlap", "exhausted", "second_conflict", "incomplete_reread"]
)
async def test_readback_one_reread_or_explicit_hint(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    transport, sources, purchase = scenario
    factory, config = postgres_session_factory, step1_settings()
    activate(transport)
    await run(sources, factory)
    trusted = snapshot(factory)
    subject = capture(factory, purchase, clock)
    transport.subscriptions[0]["current_blocking"] = 1
    proof = await finding(sources, subject, clock)
    with factory() as db:
        sub = db.get(ExternalSubscription, subject.subscription_id)
        if case in {"overlap", "legacy_overlap"}:
            latest = db.get(BillingStateObservation, sub.latest_observation_id)
            finish = clock.tick()
            overlapping = BillingStateObservation(
                observation_kind=latest.observation_kind,
                external_billing_account_id=latest.external_billing_account_id,
                user_id=latest.user_id,
                product_id=latest.product_id,
                access_scope_id=latest.access_scope_id,
                subscription_id=latest.subscription_id,
                observed_at=finish,
                evidence_document={**latest.evidence_document, "read_finished_at": finish.isoformat()},
                evidence_schema_version="prepared-subscription:v1"
                if case == "legacy_overlap"
                else latest.evidence_schema_version,
                completeness_classification=latest.completeness_classification,
                result_classification=latest.result_classification,
            )
            db.add(overlapping)
            db.flush()
            sub.latest_observation_id = overlapping.observation_id
        else:
            sub.reconciliation_fencing_token += 1
        db.commit()
    before = persisted(factory)
    transport.pool = factory.kw["bind"].pool
    calls = 0
    get = sources.require_lbx().get_subscription

    async def reread(**kwargs: object) -> Subscription:
        nonlocal calls
        calls += 1
        clock.tick()
        if case == "second_conflict":
            with factory() as db:
                db.get(ExternalSubscription, subject.subscription_id).reconciliation_fencing_token += 1
                db.commit()
        if case == "incomplete_reread":
            return (await get(**kwargs)).model_copy(update={"state": 99})
        return await get(**kwargs)

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", reread)
    clock.tick()
    async with sources.billing.operation() as budget:
        with monkeypatch.context() as patch:
            if case == "exhausted":

                def exhausted() -> None:
                    raise PreflightDeadlineExceeded()

                patch.setattr(budget, "check", exhausted)
            result = await apply_bound_readback(
                sources.require_lbx(), config, factory=factory, finding=proof, budget=budget
            )

    hint = case in {"exhausted", "second_conflict", "incomplete_reread"}
    assert result == (Result.HINT_ONLY if hint else Result.APPLIED_NEGATIVE)
    assert calls == (0 if case == "exhausted" else 1)
    if hint:
        after = persisted(factory)
        assert after[0] == before[0] and after[3] == before[3]
        assert after[1] == before[1] + int(case == "second_conflict")
    else:
        assert_negative(factory, trusted)


@pytest.mark.parametrize("failure", ["write", "before_commit", "lost_ack"])
async def test_readback_atomicity_and_acknowledgement(
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    transport.subscriptions[0]["current_blocking"] = 1
    subject = capture(factory, purchase, clock)
    proof = await finding(sources, subject, clock)
    before = persisted(factory)
    commit, enroll = Session.commit, readback.enroll_subscription

    def failed_commit(db: Session) -> None:
        if failure == "lost_ack":
            commit(db)
        else:
            db.flush()
        raise RuntimeError("synthetic commit failure")

    def failed_write(db: Session, sub: ExternalSubscription, *, hint: bool = False) -> None:
        enroll(db, sub, hint=hint)
        db.flush()
        raise RuntimeError("synthetic write failure")

    with monkeypatch.context() as patch:
        patch.setattr(readback, "enroll_subscription", failed_write) if failure == "write" else patch.setattr(
            Session, "commit", failed_commit
        )
        with pytest.raises(RuntimeError):
            readback.apply_readback(factory, step1_settings(), proof)
    if failure != "lost_ack":
        assert persisted(factory) == before
    else:
        assert_negative(factory, before[0])
        fresh = capture(factory, purchase, clock)
        assert fresh.fence == subject.fence + 1
        assert fresh.supporting_observation_id != subject.supporting_observation_id
        assert transport.creates("/subscriptions") == 1


@pytest.mark.parametrize("claim_mode", ["own", "foreign", "expired"])
async def test_readback_queue_owner_and_generation(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, claim_mode: str
) -> None:
    transport, sources, purchase = scenario
    factory, config = postgres_session_factory, step1_settings()
    subject = capture(factory, purchase, clock)
    transport.subscriptions[0]["current_blocking"] = 1
    claim = work.claim_work(factory, config, WorkLane.URGENT)
    assert claim is not None
    proof = await finding(sources, subject, clock)
    if claim_mode == "expired":
        clock.now = claim.expires_at + timedelta(seconds=1)
        before = persisted(factory)
        with pytest.raises(BillingRefused, match="billing_work_stale"):
            readback.apply_readback(factory, config, proof, work_claim=claim)
        assert persisted(factory) == before
        return
    assert (
        readback.apply_readback(factory, config, proof, work_claim=claim if claim_mode == "own" else None)
        == Result.APPLIED_NEGATIVE
    )
    with factory() as db:
        row = work.verify_claim(db, claim)
        assert row.lease_owner == claim.owner and row.enqueue_generation > claim.generation
        work.finish(db, row, claim, due=None)
        assert row.work_state == "pending"
        db.commit()
    assert_negative(factory, snapshot(factory))


@pytest.mark.parametrize("receipt", [False, True])
@pytest.mark.parametrize("failure", [None, "rollback", "lost_ack", "concurrent"])
async def test_first_binding_context_and_atomic_history(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    receipt: bool,
    failure: str | None,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.financial_pending(factory, purchase, op)
    if receipt:
        financial.record_receipt(factory, purchase, replace(op, may_send=True), 567)
    purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    subject = readback.capture_readback(factory, config, purchase, deadline=clock.tick() + timedelta(minutes=5))
    assert isinstance(subject, OriginalCreateReadbackSubject)
    transport.subscriptions[0]["state"] = 3
    clock.tick()
    async with sources.billing.operation() as budget:
        proof = await read_original_create_proof(sources.require_lbx(), subject, budget=budget)
    observation = prepared_subscription_observation(
        Subscription.model_validate(transport.subscriptions[0]), purchase, terminal=True
    )
    if failure == "concurrent":
        financial.bind_financial(factory, purchase, subject.operation, 567, observation=observation)
        with factory() as db, pytest.raises(ReadbackRecheck):
            readback_binding.begin_first_binding(db, config, subject, proof)
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 1
        return
    commit = Session.commit

    def finish(db: Session) -> None:
        if failure == "lost_ack":
            commit(db)
        elif failure is None:
            commit(db)
            return
        else:
            db.flush()
        raise RuntimeError("synthetic binding commit failure")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", finish)

        def bind() -> Result:
            with factory() as db:
                context = readback_binding.begin_first_binding(db, config, subject, proof)
                outcome = financial.bind_financial_in_transaction(
                    db, purchase, subject.operation, 567, observation=observation, first_binding=context
                )
                db.commit()
                return outcome

        if failure is None:
            assert bind() == Result.APPLIED_NEGATIVE
        else:
            with pytest.raises(RuntimeError):
                bind()
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        original = db.get(ExternalCreateOperation, op.id)
        if failure == "rollback":
            assert sub is None and original.operation_state == State.UNKNOWN
            assert not list(db.scalars(select(BillingStateObservation)))
        else:
            assert sub.lifecycle_status == "ended" and sub.financial_access_status == "blocked"
            assert sub.projection_valid_until == sub.last_authoritative_read_at
            assert sub.reconciliation_fencing_token == 1 and original.operation_state == State.BOUND
            evidence = db.get(BillingStateObservation, sub.latest_observation_id)
            assert evidence.evidence_schema_version == NEGATIVE_SCHEMA
            assert evidence.evidence_document["original_create"]["fence"] == str(subject.operation.fence)
            assert evidence.evidence_document["expected_fence"] is None
            assert db.scalar(select(func.count()).select_from(BillingStateObservation)) == 2
        assert (
            original.unknown_since is not None and original.recovery_hint_document["request"] == subject.saved_command
        )


@pytest.mark.parametrize("exhausted", [False, True])
async def test_concurrent_first_binding_uses_real_bound_subject(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    exhausted: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    subject = readback.capture_readback(factory, config, purchase, deadline=clock.tick() + timedelta(minutes=5))
    assert isinstance(subject, OriginalCreateReadbackSubject)
    transport.subscriptions[0]["state"] = 3
    async with sources.billing.operation() as budget:
        clock.tick()
        proof = await read_original_create_proof(sources.require_lbx(), subject, budget=budget)
        observation = prepared_subscription_observation(
            Subscription.model_validate(transport.subscriptions[0]), purchase, terminal=True
        )
        financial.bind_financial(factory, purchase, subject.operation, 567, observation=observation)
        before = persisted(factory)
        clock.tick()
        with monkeypatch.context() as patch:
            if exhausted:

                def unavailable() -> None:
                    raise PreflightDeadlineExceeded()

                patch.setattr(budget, "check", unavailable)
            result = await apply_bound_readback(
                sources.require_lbx(),
                config,
                factory=factory,
                finding=ScopedReadbackFinding(subject, proof.negative),
                budget=budget,
            )
        assert result == (Result.HINT_ONLY if exhausted else Result.APPLIED_NEGATIVE)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 1
        assert db.scalar(select(func.count()).select_from(BillingStateObservation)) == (1 if exhausted else 2)
    if exhausted:
        assert persisted(factory)[:4] == before[:4]
    else:
        assert_negative(factory, before[0])


@pytest.mark.parametrize("case", ["missing_terms", "ambiguous", "changed_receipt", "changed_fence"])
async def test_original_negative_never_substitutes_for_create_proof(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, case: str
) -> None:
    from app.integrations.lbx.errors import LbxResponseInvalid

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    subject = readback.capture_readback(factory, config, purchase, deadline=clock.tick() + timedelta(minutes=5))
    transport.subscriptions[0]["state"] = 3
    if case == "missing_terms":
        transport.subscriptions[0]["total_price"] = None
    elif case == "ambiguous":
        transport.subscriptions.append({**transport.subscriptions[0], "subscription_id": 568})
    clock.tick()
    async with sources.billing.operation() as budget:
        if case in {"missing_terms", "ambiguous"}:
            with pytest.raises(LbxResponseInvalid):
                await read_original_create_proof(sources.require_lbx(), subject, budget=budget)
        else:
            proof = await read_original_create_proof(sources.require_lbx(), subject, budget=budget)
            if case == "changed_receipt":
                financial.record_receipt(factory, purchase, replace(subject.operation, may_send=True), 568)
            else:
                with factory() as db:
                    db.get(ExternalCreateOperation, subject.operation.id).send_fence = uuid4()
                    db.commit()
            with factory() as db, pytest.raises(BillingRefused):
                readback_binding.begin_first_binding(db, config, subject, proof)
    with factory() as db:
        assert not list(db.scalars(select(ExternalSubscription)))
        assert not list(db.scalars(select(BillingStateObservation)))


@pytest.mark.parametrize("prior", ["ended", "review"])
async def test_negative_preserves_terminal_and_genuine_review(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, prior: str
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    activate(transport)
    if prior == "ended":
        transport.subscriptions[0]["state"] = 3
    else:
        transport.subscriptions[0]["services"][0]["price"] = transport.subscriptions[0]["total_price"] = 150
    await run(sources, factory)
    trusted = snapshot(factory)
    with factory() as db:
        reviews = tuple(db.scalars(select(ManualReviewCase.review_case_id)))
    subject = capture(factory, purchase, clock)
    transport.subscriptions[0].update(state=2, current_blocking=1, total_price=None)
    proof = await finding(sources, subject, clock)
    assert readback.apply_readback(factory, step1_settings(), proof) == Result.APPLIED_NEGATIVE
    after = snapshot(factory)
    assert after[4:6] == trusted[4:6]
    assert after[1:4] == (("ended", "blocked", trusted[3]) if prior == "ended" else ("active", "blocked", "ineligible"))
    with factory() as db:
        assert tuple(db.scalars(select(ManualReviewCase.review_case_id))) == reviews
        assert all(row.case_state == "open" for row in db.scalars(select(ManualReviewCase)))


@pytest.mark.parametrize("case", ["deadline", "future", "before_capture", "wrong_agreement", "wrong_subscription"])
async def test_readback_window_and_exact_negative_scope(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, case: str
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    subject = capture(factory, purchase, clock)
    transport.subscriptions[0]["current_blocking"] = 1
    proof = await finding(sources, subject, clock)
    before = persisted(factory)
    if case == "deadline":
        proof = replace(proof, subject=replace(subject, deadline=clock.now))
    elif case == "future":
        proof = replace(proof, negative=replace(proof.negative, read_finished_at=clock.now + timedelta(seconds=1)))
    elif case == "before_capture":
        proof = replace(
            proof, negative=replace(proof.negative, read_started_at=subject.captured_at - timedelta(seconds=1))
        )
    else:
        proof = replace(
            proof,
            negative=replace(
                proof.negative,
                **({"agreement_id": "999"} if case == "wrong_agreement" else {"provider_subscription_id": "999"}),
            ),
        )
    if case.startswith("wrong_"):
        with pytest.raises(BillingRefused, match="subscription_provenance_changed"):
            readback.apply_readback(factory, step1_settings(), proof)
        assert persisted(factory) == before
    else:
        assert readback.apply_readback(factory, step1_settings(), proof) == Result.HINT_ONLY
        assert persisted(factory)[:4] == before[:4]


async def test_first_binding_context_cannot_cross_transaction_boundary(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    subject = readback.capture_readback(factory, config, purchase, deadline=clock.tick() + timedelta(minutes=5))
    transport.subscriptions[0]["state"] = 3
    clock.tick()
    async with sources.billing.operation() as budget:
        proof = await read_original_create_proof(sources.require_lbx(), subject, budget=budget)
    with factory() as db:
        context = readback_binding.begin_first_binding(db, config, subject, proof)
        db.rollback()
        with pytest.raises(BillingRefused):
            readback_binding.apply_first_binding_negative(db, context)
    with factory() as db:
        assert not list(db.scalars(select(ExternalSubscription)))


async def test_closed_agreement_negative_survives_unavailable_subscription(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.integrations.lbx.errors import LbxUnavailable

    transport, sources, purchase = scenario
    factory = postgres_session_factory
    subject = capture(factory, purchase, clock)
    trusted = snapshot(factory)
    transport.agreements[0]["close_date"] = "2026-11-05"

    async def unavailable(**kwargs: object) -> None:
        raise LbxUnavailable()

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", unavailable)
    proof = await finding(sources, subject, clock)
    assert proof.negative.basis == "agreement"
    assert readback.apply_readback(factory, step1_settings(), proof) == Result.APPLIED_NEGATIVE
    assert snapshot(factory)[1] == "ended"
    assert_negative(factory, trusted)


async def test_reconciliation_time_guard_rejects_newer_support_with_same_fence(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock
) -> None:
    from dataclasses import asdict
    from app.domains.billing.reconciliation_contracts import RECONCILIATION_SCHEMA

    transport, sources, _ = scenario
    factory, config = postgres_session_factory, step1_settings()
    activate(transport)
    subject = claim_reconciliation(factory, config, snapshot(factory)[0], io_timeout_seconds=600)
    async with sources.billing.operation() as budget:
        incoming = await read_subscription_proof(sources.require_lbx(), subject, config, budget=budget)
        clock.tick()
        newer = await read_subscription_proof(sources.require_lbx(), subject, config, budget=budget)
    document = asdict(newer)
    document.update(
        read_started_at=newer.read_started_at.isoformat(), read_finished_at=newer.read_finished_at.isoformat()
    )
    with factory() as db:
        sub = db.get(ExternalSubscription, subject.subscription_id)
        previous = db.get(BillingStateObservation, sub.latest_observation_id)
        support = BillingStateObservation(
            observation_kind=previous.observation_kind,
            external_billing_account_id=sub.external_billing_account_id,
            user_id=sub.user_id,
            product_id=sub.product_id,
            subscription_id=sub.subscription_id,
            observed_at=newer.read_finished_at,
            evidence_schema_version=RECONCILIATION_SCHEMA,
            evidence_document=document,
            completeness_classification="complete",
            result_classification="COMPLETE_MATCH",
        )
        db.add(support)
        db.flush()
        sub.latest_observation_id = support.observation_id
        db.commit()
    before = persisted(factory)
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        apply_reconciliation(factory, subject, incoming)
    assert persisted(factory) == before


@pytest.mark.parametrize("owner", ["own", "foreign"])
async def test_first_binding_preserves_recovery_claim_owner(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, owner: str
) -> None:
    from apps.api.tests.test_billing_background_recovery_postgres import due

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    subject = readback.capture_readback(factory, config, purchase, deadline=clock.tick() + timedelta(minutes=5))
    due(factory, "external_create_recovery", subject.operation.id)
    claim = work.claim_work(factory, config, WorkLane.URGENT)
    assert claim.kind == "external_create_recovery" and claim.reference == str(subject.operation.id)
    transport.subscriptions[0]["state"] = 3
    clock.tick()
    async with sources.billing.operation() as budget:
        proof = await read_original_create_proof(sources.require_lbx(), subject, budget=budget)
    observation = prepared_subscription_observation(
        Subscription.model_validate(transport.subscriptions[0]), purchase, terminal=True
    )
    with factory() as db:
        context = readback_binding.begin_first_binding(db, config, subject, proof)
        outcome = financial.bind_financial_in_transaction(
            db,
            purchase,
            subject.operation,
            567,
            observation=observation,
            first_binding=context,
            work_claim=claim if owner == "own" else None,
        )
        db.commit()
    assert outcome == Result.APPLIED_NEGATIVE
    with factory() as db:
        row = db.get(BillingWorkItem, claim.id)
        assert row.work_state == ("completed" if owner == "own" else "running")
        assert row.lease_owner == (None if owner == "own" else claim.owner)
        if owner == "foreign":
            work.verify_claim(db, claim)


@pytest.mark.parametrize("positive_trust", [False, True])
async def test_negative_history_repairs_only_existing_trust_deadline(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, positive_trust: bool
) -> None:
    transport, sources, purchase = scenario
    factory, config = postgres_session_factory, step1_settings()
    if positive_trust:
        activate(transport)
        await run(sources, factory)
    trusted = snapshot(factory)
    subject = capture(factory, purchase, clock)
    transport.subscriptions[0].update(current_blocking=1, total_price=None)
    negative = await finding(sources, subject, clock)
    assert readback.apply_readback(factory, config, negative) == Result.APPLIED_NEGATIVE
    support = snapshot(factory)[-1]
    assert work.reconciliation_outcome(factory, support) == ("negative", negative.negative.read_finished_at)
    with factory() as db:
        immutable_document = db.get(BillingStateObservation, support).evidence_document
        db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
        db.commit()
    requests = len(transport.requests)
    assert work.enroll_batch(factory, config) == int(positive_trust)
    assert work.enroll_batch(factory, config) == 0
    with factory() as db:
        expiry = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
        assert (expiry is not None) == positive_trust
        if expiry:
            assert expiry.next_attempt_at == trusted[5]
            assert expiry.payload_document == {
                "supporting_observation_id": str(support),
                "deadline": trusted[5].isoformat(),
            }
    clock.now = trusted[5] + timedelta(seconds=1)
    with factory() as db:
        for row in db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind != work.EXPIRY)):
            row.next_attempt_at = clock.now + timedelta(days=1)
        db.commit()
    claim = work.claim_work(factory, config, WorkLane.LOCAL)
    if positive_trust:
        assert claim.kind == work.EXPIRY
        work.expire_trust(factory, claim)
    else:
        assert claim is None
    assert work.claim_work(factory, config, WorkLane.LOCAL) is None
    assert len(transport.requests) == requests
    assert snapshot(factory)[4:6] == trusted[4:6]
    assert snapshot(factory)[-1] == support
    with factory() as db:
        assert db.get(BillingStateObservation, support).evidence_document == immutable_document
        expiries = list(
            db.scalars(
                select(BillingStateObservation).where(
                    BillingStateObservation.evidence_schema_version == "subscription-trust-expiry:v1"
                )
            )
        )
        assert len(expiries) == int(positive_trust)
        if expiries:
            assert expiries[0].basis_observation_id == support
            assert expiries[0].effective_at == trusted[5]
        for model in (PaidAccessState, PurchasedAllowance, AccessInvalidationOutbox):
            assert db.scalar(select(func.count()).select_from(model)) == 0


@pytest.mark.parametrize("schema", ["prepared-subscription:v1", "financial-terminal:v1"])
async def test_legacy_support_is_ordered_without_rewriting_history(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, schema: str
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        previous = db.get(BillingStateObservation, sub.latest_observation_id)
        terminal = schema == "financial-terminal:v1"
        point = Subscription.model_validate(transport.subscriptions[0])
        if terminal:
            point = point.model_copy(update={"state": 3})
        preparation = prepared_subscription_observation(point, purchase, terminal=terminal)
        old = observation_factory(previous, schema=schema, document=asdict(preparation))
        old.completeness_classification = "original_terms_only" if terminal else "preparation_only"
        old.result_classification = "terminal_not_paid" if terminal else "not_paid_verified"
        db.add(old)
        db.flush()
        sub.latest_observation_id = old.observation_id
        db.commit()
        db.refresh(old)
        old_id, old_document = old.observation_id, old.evidence_document
    trusted = snapshot(factory)
    subject = capture(factory, purchase, clock)
    transport.subscriptions[0].update(current_blocking=1, total_price=None)
    negative = await finding(sources, subject, clock)
    assert readback.apply_readback(factory, step1_settings(), negative) == Result.APPLIED_NEGATIVE
    assert_negative(factory, trusted)
    with factory() as db:
        old = db.get(BillingStateObservation, old_id)
        assert (old.evidence_schema_version, old.evidence_document) == (schema, old_document)


@pytest.mark.parametrize("corruption", ["missing_start", "naive_time", "reverse_window", "wrong_finish", "not_object"])
async def test_malformed_negative_support_requires_recheck_without_writes(
    scenario: tuple, postgres_session_factory: sessionmaker[Session], clock: Clock, corruption: str
) -> None:
    transport, sources, purchase = scenario
    factory = postgres_session_factory
    transport.subscriptions[0].update(current_blocking=1)
    first = await finding(sources, capture(factory, purchase, clock), clock)
    assert readback.apply_readback(factory, step1_settings(), first) == Result.APPLIED_NEGATIVE
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        old = db.get(BillingStateObservation, sub.latest_observation_id)
        document = dict(old.evidence_document)
        if corruption == "missing_start":
            document.pop("read_started_at")
        elif corruption == "naive_time":
            document["read_started_at"] = clock.now.replace(tzinfo=None).isoformat()
        elif corruption == "reverse_window":
            document["read_started_at"] = (clock.now + timedelta(seconds=20)).isoformat()
        elif corruption == "wrong_finish":
            document["read_finished_at"] = (clock.now - timedelta(seconds=1)).isoformat()
        else:
            document = []
        malformed = observation_factory(old, schema=NEGATIVE_SCHEMA, document=document)
        db.add(malformed)
        db.flush()
        sub.latest_observation_id = malformed.observation_id
        db.commit()
    clock.tick()
    second = await finding(sources, capture(factory, purchase, clock), clock)
    before = persisted(factory)
    with pytest.raises(ReadbackRecheck):
        readback.apply_readback(factory, step1_settings(), second)
    assert persisted(factory) == before
