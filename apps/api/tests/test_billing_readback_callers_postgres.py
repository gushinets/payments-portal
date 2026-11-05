"""Stage 3 production entrypoints: scoped effects, original recovery and payment admission."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.billing_operator import resolve_review
from app.composition.purchases import advance_purchase, recover_financial
from app.composition.reconciliation import reconcile_subscription
from app.core.errors import AppError
from app.domains.billing import work
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.readback_contracts import NEGATIVE_SCHEMA
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import financial, service
from app.models import (
    BillingStateObservation,
    BillingWorkItem,
    ExternalSubscription,
    ManualReviewCase,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
)
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    synthetic_prepare,
    original,
)
from apps.api.tests.test_billing_subscription_reconciliation_postgres import run, snapshot
from apps.api.tests.test_billing_inventory_resolution_postgres import inventory_review
from apps.api.tests.test_billing_recovery_cli_postgres import PRINCIPAL

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("entrypoint", ["advance", "widget"])
@pytest.mark.parametrize("case", ["waiting", "financial_block", "admin_block", "ended", "closed"])
@pytest.mark.parametrize("missing", ["total_price", "service_price", None])
async def test_bound_callers_commit_independent_negative_before_strict_admission(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    entrypoint: str,
    case: str,
    missing: str | None,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    await run(sources, factory)
    before = snapshot(factory)
    history = {op.id: original(factory, op.id) for op in purchase.operations}
    with factory() as db:
        count = db.scalar(select(func.count()).select_from(BillingStateObservation))
        sub = db.get(ExternalSubscription, before[0])
        fence = sub.reconciliation_fencing_token
    point = transport.subscriptions[0]
    if case == "waiting":
        point["state"] = -2
    elif case in {"financial_block", "admin_block"}:
        point["current_blocking"] = 1 if case == "financial_block" else 3
    elif case == "ended":
        point["state"] = 3
    else:
        transport.agreements[0]["close_date"] = "2026-11-03"
    if missing == "total_price":
        point["total_price"] = None
    elif missing == "service_price":
        point["services"][0]["price"] = None
    calls = len(transport.requests)
    if entrypoint == "advance":
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    elif missing or case in {"ended", "closed"}:
        with pytest.raises(AppError) as error:
            await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert error.value.code == "purchase_not_prepared"
    else:
        result = await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.purchase_id == purchase.id and result.credential
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.state == purchase.state and saved.held and saved.accepted == purchase.accepted
    assert tuple(op.admission_snapshot() for op in saved.operations) == tuple(
        op.admission_snapshot() for op in purchase.operations
    )
    assert {op.id: original(factory, op.id) for op in saved.operations} == history
    with factory() as db:
        sub = db.get(ExternalSubscription, before[0])
        evidence = db.get(BillingStateObservation, sub.latest_observation_id)
        assert sub.financial_access_status == "blocked"
        assert sub.lifecycle_status == (
            "ended" if case in {"ended", "closed"} else "inactive" if case == "waiting" else "active"
        )
        assert sub.commercial_access_status == "eligible"
        assert (sub.last_authoritative_read_at, sub.projection_valid_until) == before[4:6]
        assert sub.reconciliation_fencing_token == fence + 1
        assert evidence.evidence_schema_version == NEGATIVE_SCHEMA
        assert evidence.evidence_document["commercial"] == "INCOMPLETE"
        if missing:
            assert "effective_terms_incomplete" in evidence.evidence_document["reasons"]
        assert db.scalar(select(func.count()).select_from(BillingStateObservation)) == count + 1
        assert not list(db.scalars(select(ManualReviewCase)))
        queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        assert queue.scope_reference == str(sub.subscription_id) and queue.priority == 1
        assert queue.next_attempt_at <= datetime.now(UTC)
        recoveries = list(
            db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == "external_create_recovery"))
        )
        assert all(row.work_state in {"done", "completed"} for row in recoveries)
    assert all(req.method == "GET" for req in transport.requests[calls:])
    claim = work.claim_work(factory, config, WorkLane.URGENT)
    assert claim.kind == work.RECONCILIATION and claim.reference == str(before[0])
    await reconcile_subscription(
        sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=before[0], work_claim=claim
    )
    assert snapshot(factory)[2] == "blocked"
    if missing:
        assert snapshot(factory)[4:6] == before[4:6]


@pytest.mark.parametrize("receipt", [False, True])
@pytest.mark.parametrize("closed", [False, True])
async def test_actual_unknown_terminal_first_binding_is_atomic_and_get_only(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    receipt: bool,
    closed: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    if receipt:
        financial.record_receipt(factory, purchase, replace(op, may_send=True), 567)
    financial.financial_pending(factory, purchase, op)
    purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    assert op.state == State.UNKNOWN and op.candidate_id == ("567" if receipt else None)
    history = original(factory, op.id)
    transport.subscriptions[0]["state"] = 3
    if closed:
        transport.agreements[0]["close_date"] = "2026-11-03"
    calls = len(transport.requests)
    await recover_financial(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.state == "linked" and saved.held and saved.accepted == purchase.accepted
    assert all(op.state == State.BOUND for op in saved.operations)
    assert original(factory, op.id) == history
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        assert sub.lifecycle_status == "ended" and sub.financial_access_status == "blocked"
        assert sub.reconciliation_fencing_token == 1
        evidence = db.get(BillingStateObservation, sub.latest_observation_id)
        assert evidence.evidence_schema_version == NEGATIVE_SCHEMA
        assert evidence.evidence_document["original_create"]["state"] == State.UNKNOWN
        schemas = list(db.scalars(select(BillingStateObservation.evidence_schema_version)))
        assert schemas.count("financial-terminal:v1") == schemas.count(NEGATIVE_SCHEMA) == 1
        assert not list(db.scalars(select(ManualReviewCase)))
        queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        assert queue.priority == 1 and queue.next_attempt_at <= datetime.now(UTC)
    # One original child point; the binder's own history/fence never causes a reread.
    reads = transport.requests[calls:]
    assert sum(req.url.path.endswith("/subscriptions/567") for req in reads) == 1
    assert all(req.method == "GET" for req in reads)


@pytest.mark.parametrize("failure", ["incomplete_terms", "unknown_lifecycle"])
async def test_unknown_with_receipt_and_negative_cannot_invent_original_proof(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    failure: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.record_receipt(factory, purchase, replace(op, may_send=True), 567)
    financial.financial_pending(factory, purchase, op)
    transport.agreements[0]["close_date"] = "2026-11-03"
    transport.subscriptions[0]["state"] = 3 if failure == "incomplete_terms" else 99
    if failure == "incomplete_terms":
        transport.subscriptions[0]["total_price"] = None
    await recover_financial(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    with factory() as db:
        assert db.scalar(select(ExternalSubscription)) is None
        assert not list(db.scalars(select(ManualReviewCase)))
        queue = db.scalar(
            select(BillingWorkItem).where(
                BillingWorkItem.scope_reference == str(op.id), BillingWorkItem.work_kind == "external_create_recovery"
            )
        )
        assert queue.work_state == "pending" and queue.payload_document["candidate_id"] == "567"
    assert (
        next(
            op
            for op in service.read_purchase(factory, purchase.user_id, purchase.id).operations
            if op.kind == Kind.SUBSCRIPTION
        ).state
        == State.UNKNOWN
    )


@pytest.mark.parametrize("terminal", [False, True])
async def test_operator_inventory_applies_neighbor_effect_without_resolving_neighbor(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    terminal: bool,
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    target, neighbor = await inventory_review(background_scenario, factory, two=True)
    if terminal:
        transport.subscriptions[1]["state"] = 3
    else:
        transport.subscriptions[1]["current_blocking"] = 3
    before = service.read_purchase(factory, neighbor.user_id, neighbor.id)
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == neighbor.id))
        sub_id, fence, trust = (
            sub.subscription_id,
            sub.reconciliation_fencing_token,
            (sub.last_authoritative_read_at, sub.projection_valid_until),
        )
        cases = {
            case.review_case_id
            for case in db.scalars(select(ManualReviewCase))
            if case.evidence_document.get("purchase_intent_id") == str(neighbor.id)
        }
    request = resolution_request(target, inspect_evidence(factory, step1_settings(), target.user_id, target.id))
    await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert service.read_purchase(factory, neighbor.user_id, neighbor.id) == before
    with factory() as db:
        sub = db.get(ExternalSubscription, sub_id)
        assert sub.financial_access_status == "blocked" and sub.reconciliation_fencing_token == fence + 1
        assert sub.lifecycle_status == ("ended" if terminal else "active")
        assert (sub.last_authoritative_read_at, sub.projection_valid_until) == trust
        assert all(db.get(ManualReviewCase, case_id).case_state == "open" for case_id in cases)
        audit = db.get(ManualReviewCase, request.case_id).resolution_document
        assert audit["inventory_proof"]["scoped_outcomes"] == [
            {"purchase_intent_id": str(neighbor.id), "outcome": "APPLIED_NEGATIVE"}
        ]
        assert db.get(BillingStateObservation, sub.latest_observation_id).evidence_schema_version == NEGATIVE_SCHEMA


@pytest.mark.parametrize("failure", ["before_commit", "lost_ack"])
async def test_original_caller_binding_commit_failure_covers_entire_unit(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    from app.domains.purchases import financial_readback

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.record_receipt(factory, purchase, replace(op, may_send=True), 567)
    financial.financial_pending(factory, purchase, op)
    history = original(factory, op.id)
    transport.subscriptions[0]["state"] = 3
    bind, commit = financial_readback.bind_original_readback, Session.commit

    def failing_commit(db: Session) -> None:
        if failure == "lost_ack":
            commit(db)
        else:
            db.flush()
        raise RuntimeError("simulated binding commit failure")

    def bind_failure(*args: object, **kwargs: object) -> object:
        with monkeypatch.context() as patch:
            patch.setattr(Session, "commit", failing_commit)
            return bind(*args, **kwargs)

    monkeypatch.setattr(financial_readback, "bind_original_readback", bind_failure)
    with pytest.raises(RuntimeError, match="simulated binding commit failure"):
        await recover_financial(
            sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
    assert original(factory, op.id) == history
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        schemas = list(db.scalars(select(BillingStateObservation.evidence_schema_version)))
        queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        if failure == "lost_ack":
            assert sub is not None and sub.lifecycle_status == "ended" and sub.financial_access_status == "blocked"
            assert schemas.count("financial-terminal:v1") == schemas.count(NEGATIVE_SCHEMA) == 1
            assert queue is not None and queue.priority == 1
        else:
            assert sub is None and queue is None
            assert "financial-terminal:v1" not in schemas and NEGATIVE_SCHEMA not in schemas
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    target = next(op for op in saved.operations if op.kind == Kind.SUBSCRIPTION)
    assert target.state == (State.BOUND if failure == "lost_ack" else State.UNKNOWN)


async def test_operator_neighbor_effect_rolls_back_with_audit_failure(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domains.billing import operator_review

    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    target, neighbor = await inventory_review(background_scenario, factory, two=True)
    transport.subscriptions[1]["state"] = 3
    before = service.read_purchase(factory, neighbor.user_id, neighbor.id)
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == neighbor.id))
        expected = (
            sub.lifecycle_status,
            sub.financial_access_status,
            sub.reconciliation_fencing_token,
            sub.latest_observation_id,
        )
        count = db.scalar(select(func.count()).select_from(BillingStateObservation))
    request = resolution_request(target, inspect_evidence(factory, step1_settings(), target.user_id, target.id))

    def fail_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated audit failure")

    monkeypatch.setattr(operator_review, "audit_resolution", fail_audit)
    with pytest.raises(RuntimeError, match="simulated audit failure"):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert service.read_purchase(factory, neighbor.user_id, neighbor.id) == before
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == neighbor.id))
        assert (
            sub.lifecycle_status,
            sub.financial_access_status,
            sub.reconciliation_fencing_token,
            sub.latest_observation_id,
        ) == expected
        assert db.scalar(select(func.count()).select_from(BillingStateObservation)) == count
        assert db.get(ManualReviewCase, request.case_id).case_state == "open"


async def test_account_only_widget_does_not_read_broken_subscription(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    synthetic_prepare(factory, transport, purchase, uncertain=False)
    transport.subscriptions[0].update(state=99, total_price=None)
    calls = len(transport.requests)
    result = await bootstrap_account(sources, step1_settings(), factory=factory, token=TOKEN)
    assert result.credential and result.purchase_id is None
    assert not any("/subscriptions" in req.url.path for req in transport.requests[calls:])


@pytest.mark.parametrize("exhausted", [False, True])
async def test_original_caller_concurrent_canonical_creation_uses_real_bound_reread(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    exhausted: bool,
) -> None:
    from starlette.concurrency import run_in_threadpool
    from app.composition.purchase_observation import prepared_subscription_observation
    from app.domains.purchases import financial_readback
    from app.integrations.lbx.financial import Subscription

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.financial_pending(factory, purchase, op)
    purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    transport.subscriptions[0]["state"] = 3
    get = sources.require_lbx().get_subscription
    reads, budget_used = 0, None

    async def competing_bind(**kwargs: object) -> Subscription:
        nonlocal reads, budget_used
        point = await get(**kwargs)
        reads += 1
        budget_used = kwargs["budget"]
        if reads == 1:
            await run_in_threadpool(
                financial.bind_financial,
                factory,
                purchase,
                op,
                567,
                observation=prepared_subscription_observation(point, purchase, terminal=True),
            )
        return point

    bind = financial_readback.bind_original_readback

    def before_apply(*args: object, **kwargs: object) -> object:
        if exhausted:
            budget_used._work_deadline = 0
        return bind(*args, **kwargs)

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", competing_bind)
    monkeypatch.setattr(financial_readback, "bind_original_readback", before_apply)
    if exhausted:
        with pytest.raises(AppError) as error:
            await recover_financial(
                sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
            )
        assert error.value.code == "purchase_pending"
    else:
        await recover_financial(
            sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
    assert reads == (1 if exhausted else 2)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 1
        schemas = list(db.scalars(select(BillingStateObservation.evidence_schema_version)))
        assert schemas.count("financial-terminal:v1") == 1
        assert schemas.count(NEGATIVE_SCHEMA) == (0 if exhausted else 1)
        sub = db.scalar(select(ExternalSubscription))
        assert sub.financial_access_status == ("unverified" if exhausted else "blocked")
        queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        assert queue.priority == 1 and queue.next_attempt_at <= datetime.now(UTC)


async def test_bound_legacy_recovery_drains_without_http_and_repairs_only_real_subscription(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.composition.billing_background import recover_operation
    from app.domains.billing.work_contracts import WorkLane
    from starlette.concurrency import run_in_threadpool

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    with factory() as db:
        for queue in db.scalars(select(BillingWorkItem)):
            if queue.work_kind == "external_create_recovery" and queue.scope_reference == str(op.id):
                queue.work_state = "pending"
                queue.priority = 1
            else:
                queue.work_state = "completed"
        db.commit()
    claim = work.claim_work(factory, step1_settings(), WorkLane.URGENT)
    assert claim.kind == "external_create_recovery"
    calls = len(transport.requests)
    async with sources.billing.operation() as budget:
        await recover_operation(
            sources.require_lbx(),
            sources.billing,
            step1_settings(),
            factory=factory,
            claim=claim,
            budget=budget,
            delegate=run_in_threadpool,
        )
    assert len(transport.requests) == calls
    with factory() as db:
        assert db.get(BillingWorkItem, claim.id).work_state == "completed"
        queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        assert queue.work_state == "pending" and queue.scope_reference == str(snapshot(factory)[0])


async def test_closed_bound_agreement_restricts_even_when_child_point_fails(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.lbx.errors import LbxResponseInvalid

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    await run(sources, factory)
    before = snapshot(factory)
    transport.agreements[0]["close_date"] = "2026-11-03"

    async def unavailable(**kwargs: object) -> None:
        raise LbxResponseInvalid()

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", unavailable)
    with pytest.raises(AppError) as error:
        await bootstrap_account(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert error.value.code == "purchase_not_prepared"
    assert snapshot(factory)[1:3] == ("ended", "blocked")
    assert snapshot(factory)[4:6] == before[4:6]
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        evidence = db.get(BillingStateObservation, sub.latest_observation_id)
        assert evidence.evidence_schema_version == NEGATIVE_SCHEMA
        assert evidence.evidence_document["basis"] == "agreement"
        assert "subscription" not in evidence.evidence_document["reads"]
        assert not list(db.scalars(select(ManualReviewCase)))


async def test_operator_target_uses_final_full_proof_after_earlier_terminal_point(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.integrations.lbx.financial import Subscription

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.financial_pending(factory, purchase, op, conflict=True)
    request = resolution_request(
        purchase, inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id), bind=True
    )
    get = sources.require_lbx().get_subscription
    count = 0

    async def changing_point(**kwargs: object) -> Subscription:
        nonlocal count
        count += 1
        point = await get(**kwargs)
        return point.model_copy(update={"state": 3 if count == 1 else 2, "current_blocking": 0})

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", changing_point)
    await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert count == 2
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        assert sub.lifecycle_status == "active" and sub.financial_access_status == "unverified"
        assert sub.reconciliation_fencing_token == 0
        assert NEGATIVE_SCHEMA not in list(db.scalars(select(BillingStateObservation.evidence_schema_version)))
        assert db.get(ManualReviewCase, request.case_id).case_state == "resolved"


@pytest.mark.parametrize("no_send", [False, True])
async def test_closed_agreement_never_sends_pending_or_proven_not_sent_child(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    no_send: bool,
) -> None:
    from datetime import date
    from app.integrations.lbx.financial import NewAgreement, NewSubscription
    from apps.api.tests.factories.reconciliation import agreement_factory

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    agreement = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    claimed = financial.claim_financial(
        factory,
        purchase,
        agreement,
        NewAgreement(
            user_id=345, organization_id=21, agreement_number=agreement.key, create_date=date(2026, 10, 27)
        ).request_document(),
        configuration=step1_settings(),
        token=TOKEN,
    )
    financial.bind_financial(factory, purchase, claimed, 456)
    point = agreement_factory().model_dump()
    point.update(agreement_number=agreement.key, close_date="2026-11-03")
    transport.agreements.append(point)
    purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    child = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    if no_send:
        claimed = financial.claim_financial(
            factory,
            purchase,
            child,
            NewSubscription(
                agreement_id=456, tariff_id=701, period_id=901, tariff_service_id=1001, quantity=1, outer_id=child.key
            ).request_document(),
            configuration=step1_settings(),
            token=TOKEN,
        )
        financial.proven_not_sent(factory, purchase, claimed)
    calls = len(transport.requests)
    await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=purchase.id)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert next(op for op in saved.operations if op.kind == Kind.SUBSCRIPTION).state == (
        State.PROVEN_NOT_SENT if no_send else State.PENDING
    )
    with factory() as db:
        assert db.scalar(select(ExternalSubscription)) is None
        assert not list(db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION)))
        assert not list(db.scalars(select(ManualReviewCase)))
    assert all(req.method == "GET" for req in transport.requests[calls:])


@pytest.mark.parametrize("case", ["blocked_partial", "closed_partial"])
async def test_ordinary_inventory_keeps_neighbor_negative_before_competition_refusal(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    case: str,
) -> None:
    from app.domains.billing import background_recovery as recovery
    from app.domains.billing.work_contracts import WorkLane
    from app.jobs.billing import BillingWorker
    from apps.api.tests.test_billing_worker_postgres import historical_link

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    await run(sources, factory)
    before = snapshot(factory)
    neighbor = historical_link(factory, purchase, transport, "brief_decoder", 1)
    transport.subscriptions[1]["total_price"] = None
    if case == "blocked_partial":
        transport.subscriptions[1]["current_blocking"] = 3
    else:
        transport.agreements[1]["close_date"] = "2026-11-03"
    recovery.repair_batch(factory, step1_settings())
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.NORMAL)
    finally:
        await worker.aclose()
    assert snapshot(factory) == before
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == neighbor.id))
        assert sub.financial_access_status == "blocked"
        evidence = db.get(BillingStateObservation, sub.latest_observation_id)
        assert evidence.evidence_schema_version == NEGATIVE_SCHEMA
        assert evidence.evidence_document["commercial"] == "INCOMPLETE"
        assert "effective_terms_incomplete" in evidence.evidence_document["reasons"]
        assert not list(db.scalars(select(ManualReviewCase)))
        queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == recovery.INVENTORY))
        assert queue.last_error_classification == ("inventory_incomplete" if case == "blocked_partial" else None)
    assert service.read_purchase(factory, neighbor.user_id, neighbor.id).accepted == neighbor.accepted
