"""Real PostgreSQL and SIMULATED GET proof for privileged operator transitions."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import reconcile_purchase, resolve_review
from app.composition.purchases import recover_financial
from app.core.errors import AppError
from app.domains.billing import operator_review
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.operator_review import prepare_resolution
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase
from app.integrations.lbx.financial import NewAgreement
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingPurchaseScopeHold,
    BillingStateObservation,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    ManualReviewCase,
    PaidAccessState,
    PurchasedAllowance,
)
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.factories.reconciliation import agreement_factory
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    original,
    synthetic_prepare,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
PRINCIPAL = "os-euid:1000"


def evidence(factory: sessionmaker[Session], purchase: Purchase) -> dict:
    return inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id)


async def conflict(scenario: tuple, factory: sessionmaker[Session]) -> tuple:
    transport, sources, purchase = scenario
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    transport.subscriptions[0]["services"][0]["price"] = 15
    await reconcile_purchase(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    transport.subscriptions[0]["services"][0]["price"] = 100
    return purchase, resolution_request(purchase, evidence(factory, purchase))


def unchanged_authority(factory: sessionmaker[Session], purchase: Purchase, *, holds: int = 1) -> None:
    assert service.read_purchase(factory, purchase.user_id, purchase.id).held
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == holds
        assert all(scope.primary_subscription_id is None for scope in db.scalars(select(BillingProductAccessScope)))
        assert all(obs.resulting_access_revision is None for obs in db.scalars(select(BillingStateObservation)))
        for model in (PaidAccessState, PurchasedAllowance, AccessInvalidationOutbox):
            assert db.scalar(select(func.count()).select_from(model)) == 0


async def test_billing_recovery_cli_restore_original_audit_and_replay(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    purchase, request = await conflict(background_scenario, factory)
    before = tuple(original(factory, op.id) for op in purchase.operations)
    count = len(transport.requests)
    result = await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert result["outcome"] == "resolved"
    financial.financial_pending(
        factory, purchase, next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION), conflict=True
    )
    state = evidence(factory, purchase)
    assert state["subscription"]["financial"] == "allowed" and state["state"] == "linked"
    with factory() as db:
        case = db.get(ManualReviewCase, request.case_id)
        assert case.case_state == "resolved" and case.resolved_by_principal == PRINCIPAL
        audit = case.resolution_document
        assert audit["reason"] == request.reason and audit["reference"] == request.reference
        assert audit["before"]["external_subscription_id"] == audit["after"]["external_subscription_id"] == "567"
        assert audit["observation_id"] == result["observation_id"]
        assert audit["proof"]["commercial"] == "COMPLETE_MATCH"
    assert tuple(original(factory, op.id) for op in purchase.operations) == before
    assert all(req.method == "GET" for req in transport.requests[count:])
    count = len(transport.requests)
    assert (await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL))[
        "outcome"
    ] == "already_resolved"
    assert len(transport.requests) == count
    with pytest.raises(BillingRefused, match="billing_review_stale"):
        await resolve_review(
            sources,
            step1_settings(),
            factory=factory,
            request=request.model_copy(update={"reason": "Different request"}),
            principal=PRINCIPAL,
        )
    unchanged_authority(factory, purchase)


@pytest.mark.parametrize("kind", [Kind.AGREEMENT, Kind.SUBSCRIPTION])
async def test_billing_recovery_cli_bind_original_requires_explicit_review(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], kind: Kind
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    if kind == Kind.SUBSCRIPTION:
        purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
        op = next(op for op in purchase.operations if op.kind == kind)
    else:
        op = next(op for op in purchase.operations if op.kind == kind)
        command = NewAgreement(user_id=345, organization_id=21, agreement_number=op.key, create_date=date(2026, 10, 27))
        op = financial.claim_financial(
            factory, purchase, op, command.request_document(), configuration=step1_settings(), token=TOKEN
        )
        point = agreement_factory().model_dump()
        point.update(agreement_number=op.key, create_date="2026-10-27")
        transport.agreements.append(point)
    financial.financial_pending(factory, purchase, op, conflict=True)
    request = resolution_request(purchase, evidence(factory, purchase), bind=True)
    before = original(factory, op.id)
    count = len(transport.requests)
    with pytest.raises(BillingRefused, match="purchase_review_required"):
        await recover_financial(
            sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
    assert evidence(factory, purchase)["reviews"][0]["state"] == "open"
    await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert original(factory, op.id) == before
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert next(item for item in saved.operations if item.id == op.id).state == State.BOUND
    if kind == Kind.SUBSCRIPTION:
        assert saved.state == "linked" and evidence(factory, saved)["work"]
        # Binding is preparation, never an operator grant or source-trust renewal.
        assert evidence(factory, saved)["subscription"]["financial"] == "unverified"
    with factory() as db:
        case = db.get(ManualReviewCase, request.case_id)
        assert case.resolution_document["proof"]["discovery"] == "unique_complete"
        assert case.resolution_document["before"]["operations"] != case.resolution_document["after"]["operations"]
    assert all(req.method == "GET" for req in transport.requests[count:])
    count = len(transport.requests)
    assert (await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL))[
        "outcome"
    ] == "already_resolved"
    assert len(transport.requests) == count
    unchanged_authority(factory, purchase)


@pytest.mark.parametrize(
    "change", ["case", "observation", "fence", "incomplete", "foreign", "terminal", "unrelated", "principal"]
)
async def test_billing_recovery_cli_restore_refusals(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], change: str
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    purchase, request = await conflict(background_scenario, factory)
    principal = PRINCIPAL
    if change in {"case", "observation", "fence"}:
        key, value = {
            "case": ("expected_case_digest", "sha256:" + "0" * 64),
            "observation": ("expected_observation_id", uuid4()),
            "fence": ("expected_reconciliation_fence", 999),
        }[change]
        request = request.model_copy(update={key: value})
    elif change == "incomplete":
        transport.subscriptions[0]["total_price"] = None
    elif change == "foreign":
        transport.agreements[0]["user_id"] = 999
    elif change == "terminal":
        with factory() as db:
            db.scalar(select(ExternalSubscription)).lifecycle_status = Lifecycle.ENDED
            db.commit()
    elif change == "unrelated":
        with factory() as db:
            case = db.get(ManualReviewCase, request.case_id)
            db.add(
                ManualReviewCase(
                    reason_code="customer_inventory_conflict",
                    scope_kind=case.scope_kind,
                    scope_reference=case.scope_reference,
                    evidence_schema_version="test:v1",
                    evidence_document={},
                    case_state="open",
                )
            )
            db.commit()
    else:
        principal = "untrusted"
    with pytest.raises(BillingRefused):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=principal)
    with factory() as db:
        assert db.get(ManualReviewCase, request.case_id).case_state == "open"
    unchanged_authority(factory, purchase)


@pytest.mark.parametrize(
    "change",
    [
        "zero",
        "multiple",
        "foreign",
        "incomplete",
        "pending",
        "unsent",
        "fence",
        "request",
        "capped",
        "policy",
        "legacy",
        "already_bound",
    ],
)
async def test_billing_recovery_cli_bind_refusals(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], change: str
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    if change != "pending":
        purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    if change == "unsent":
        financial.proven_not_sent(factory, purchase, replace(op, may_send=True))
        purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
        op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.financial_pending(factory, purchase, op, conflict=True)
    request = resolution_request(purchase, evidence(factory, purchase), bind=True)
    before = original(factory, op.id)
    if change == "zero":
        transport.hide.add("/subscriptions")
    elif change in {"multiple", "capped"}:
        transport.subscriptions.extend(
            {**transport.subscriptions[0], "subscription_id": 999 + index}
            for index in range(100 if change == "capped" else 1)
        )
    elif change == "foreign":
        transport.agreements[0]["user_id"] = 999
    elif change == "incomplete":
        transport.subscriptions[0]["total_price"] = None
    elif change == "policy":
        transport.offer.replace("tariff", '"payment_type":0', '"payment_type":1')
    elif change == "fence":
        request = request.model_copy(update={"expected_operation_fence": uuid4()})
    elif change == "request":
        request = request.model_copy(update={"operation_id": uuid4()})
    elif change == "legacy":
        with factory() as db:
            case = db.get(ManualReviewCase, request.case_id)
            case.evidence_document = {
                key: value for key, value in case.evidence_document.items() if key != "operation_state_at_conflict"
            }
            db.commit()
        request = resolution_request(purchase, evidence(factory, purchase), bind=True)
    elif change == "already_bound":
        from apps.api.tests.test_billing_worker_postgres import historical_link

        historical_link(factory, purchase, transport, "brief_decoder", 1)
        transport.subscriptions[0]["subscription_id"] = 568
    with pytest.raises(AppError):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert original(factory, op.id) == before
    assert evidence(factory, purchase)["reviews"][0]["state"] == "open"
    unchanged_authority(factory, purchase, holds=2 if change == "already_bound" else 1)


@pytest.mark.parametrize("mode", ["restore", "bind"])
async def test_billing_recovery_cli_atomic_audit_rollback(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    if mode == "restore":
        purchase, request = await conflict(background_scenario, factory)
    else:
        purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
        op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
        financial.financial_pending(factory, purchase, op, conflict=True)
        request = resolution_request(purchase, evidence(factory, purchase), bind=True)
    before = service.read_purchase(factory, purchase.user_id, purchase.id)
    with factory() as db:
        observations = db.scalar(select(func.count()).select_from(BillingStateObservation))

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected audit failure")

    monkeypatch.setattr(operator_review, "audit_resolution", fail)
    with pytest.raises(RuntimeError, match="injected audit"):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    after = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert before == after
    with factory() as db:
        assert db.get(ManualReviewCase, request.case_id).case_state == "open"
        assert db.scalar(select(func.count()).select_from(BillingStateObservation)) == observations
    unchanged_authority(factory, purchase)


async def test_billing_recovery_cli_competing_poll_invalidates_operator_proof(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, sources, _ = background_scenario
    factory = postgres_session_factory
    purchase, request = await conflict(background_scenario, factory)
    context = prepare_resolution(factory, step1_settings(), request, PRINCIPAL, io_timeout_seconds=60)
    assert context.purchase.id == purchase.id
    # Ordinary polling advances the observation/fence but keeps the known review.
    await reconcile_purchase(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    monkeypatch.setattr("app.composition.billing_operator.prepare_resolution", lambda *args, **kwargs: context)
    with pytest.raises(BillingRefused, match="billing_review_stale"):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert evidence(factory, purchase)["reviews"][0]["state"] == "open"
    unchanged_authority(factory, purchase)


async def test_billing_recovery_cli_inspection_is_read_only_and_redacted(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    import json
    from sqlalchemy import event

    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    statements: list[str] = []
    engine = factory.kw["bind"]

    def record(
        connection: object, cursor: object, statement: str, parameters: object, context: object, executemany: bool
    ) -> None:
        statements.append(statement.upper())

    count = len(transport.requests)
    event.listen(engine, "before_cursor_execute", record)
    try:
        output = evidence(factory, purchase)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(transport.requests) == count
    assert not any(
        "FOR UPDATE" in statement or statement.startswith(("INSERT", "UPDATE", "DELETE")) for statement in statements
    )
    assert any("READ ONLY" in statement for statement in statements)
    serialized = json.dumps(output)
    assert transport.customer["outer_id"] not in serialized
    assert "recovery_hint_document" not in serialized and "agreement_number" not in serialized
    assert output["work"] and output["subscription"] and output["operations"]


async def test_billing_recovery_cli_worker_and_operator_apply_are_atomic_competitors(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    import asyncio
    from starlette.concurrency import run_in_threadpool
    from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation
    from app.integrations.lbx.reconciliation import read_subscription_proof
    from app.domains.billing.operator_contracts import ReviewResolution

    _, sources, _ = background_scenario
    factory = postgres_session_factory
    purchase, request = await conflict(background_scenario, factory)
    resolution = prepare_resolution(factory, step1_settings(), request, PRINCIPAL, io_timeout_seconds=60)
    assert isinstance(resolution, ReviewResolution)
    with factory() as db:
        sub_id = db.scalar(select(ExternalSubscription.subscription_id))
    subject = claim_reconciliation(factory, step1_settings(), sub_id, io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        proof = await read_subscription_proof(sources.require_lbx(), subject, step1_settings(), budget=budget)
    results = await asyncio.gather(
        run_in_threadpool(apply_reconciliation, factory, subject, proof, resolution=resolution),
        run_in_threadpool(apply_reconciliation, factory, subject, proof),
        return_exceptions=True,
    )
    assert sum(isinstance(result, BillingRefused) for result in results) == 1
    with factory() as db:
        case = db.get(ManualReviewCase, request.case_id)
        sub = db.get(ExternalSubscription, sub_id)
        if case.case_state == "resolved":
            assert case.resolution_document["observation_id"] == str(sub.latest_observation_id)
            assert sub.financial_access_status == "allowed"
        else:
            assert sub.financial_access_status == "blocked" and case.resolution_document is None
    unchanged_authority(factory, purchase)


async def test_billing_recovery_cli_binding_rejects_fence_changed_during_source_read(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.financial_pending(factory, purchase, op, conflict=True)
    request = resolution_request(purchase, evidence(factory, purchase), bind=True)
    get = sources.require_lbx().get_subscription

    async def supersede(**kwargs: object) -> object:
        result = await get(**kwargs)
        with factory() as db:
            db.get(ExternalCreateOperation, op.id).send_fence = uuid4()
            db.commit()
        return result

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", supersede)
    with pytest.raises(BillingRefused, match="billing_review_stale"):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    with factory() as db:
        assert db.get(ManualReviewCase, request.case_id).case_state == "open"
        assert db.get(ExternalCreateOperation, op.id).bound_external_object_id is None
    unchanged_authority(factory, purchase)


async def test_billing_recovery_cli_worker_proof_telemetry_distinguishes_incomplete_progress(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    from app.domains.billing import work
    from app.domains.billing.work_contracts import WorkLane
    from app.jobs.billing import BillingWorker
    from apps.api.tests.test_billing_background_recovery_postgres import due

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    synthetic_prepare(factory, transport, purchase, uncertain=False)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.URGENT)
        verified = worker.last_verified_subscription_at
        assert verified is not None and worker.last_progress_at is not None
        with factory() as db:
            sub_id = db.scalar(select(ExternalSubscription.subscription_id))
        transport.subscriptions[0]["total_price"] = None
        due(factory, work.RECONCILIATION, sub_id)
        assert await worker.tick(WorkLane.NORMAL)
        assert worker.last_verified_subscription_at == verified
        assert worker.last_progress_at > verified
    finally:
        await worker.aclose()


async def test_billing_recovery_cli_refuses_saved_request_mismatch_despite_matching_source(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    op = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    command = NewAgreement(user_id=345, organization_id=21, agreement_number=op.key, create_date=date(2026, 10, 27))
    saved_request = {**command.request_document(), "is_offer": True}
    claimed = financial.claim_financial(
        factory, purchase, op, saved_request, configuration=step1_settings(), token=TOKEN
    )
    point = agreement_factory().model_dump()
    point.update(agreement_number=op.key, create_date="2026-10-27")
    transport.agreements.append(point)
    financial.financial_pending(factory, purchase, claimed, conflict=True)
    request = resolution_request(purchase, evidence(factory, purchase), bind=True)
    before = original(factory, op.id)
    with pytest.raises(BillingRefused, match="purchase_history_unproven"):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert original(factory, op.id) == before
    assert evidence(factory, purchase)["reviews"][0]["state"] == "open"
    unchanged_authority(factory, purchase)


async def test_billing_recovery_cli_can_restore_ended_facts_without_revival_or_hold_release(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    purchase, _ = await conflict(background_scenario, factory)
    transport.subscriptions[0]["state"] = 3
    await reconcile_purchase(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    request = resolution_request(purchase, evidence(factory, purchase))
    result = await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert result["outcome"] == "resolved"
    sub = evidence(factory, purchase)["subscription"]
    assert sub["lifecycle"] == "ended" and sub["financial"] == "blocked"
    unchanged_authority(factory, purchase)
