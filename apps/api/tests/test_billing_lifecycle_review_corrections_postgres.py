"""Review regressions: real PostgreSQL and synthetic LBX, no live mutation."""

from datetime import UTC, datetime
from dataclasses import replace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import resolve_review
from app.composition.purchases import advance_purchase, recover_financial
from app.core.errors import AppError
from app.domains.billing import background_recovery as recovery
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import apply_customer_read, reserve_customer
from app.domains.billing.customer_conflicts import record_customer_conflict
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import financial, service
from app.integrations.lbx.dto import LbxRead, LbxTariff
from app.integrations.lbx.financial import NewAgreement
from app.integrations.lbx.reconciliation import read_subscription_proof
from app.jobs.billing import BillingWorker
from app.models import BillingWorkItem, ExternalBillingCustomer, ExternalSubscription, ManualReviewCase
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.factories.reconciliation import agreement_factory
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    original,
    synthetic_prepare,
)
from apps.api.tests.test_billing_inventory_resolution_postgres import inventory_review
from apps.api.tests.test_billing_recovery_cli_postgres import PRINCIPAL
from apps.api.tests.test_billing_subscription_reconciliation_postgres import snapshot, run
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("block", [1, 3])
async def test_terminal_block_immediately_supersedes_allowed(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], block: int
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    synthetic_prepare(factory, transport, purchase, uncertain=False)
    await run(sources, factory)
    assert snapshot(factory)[2:4] == ("allowed", "eligible")
    transport.subscriptions[0].update(state=3, current_blocking=block)
    observation = await run(sources, factory)
    assert observation.evidence_document["lifecycle"] == "ended"
    assert snapshot(factory)[1:3] == ("ended", "blocked")


@pytest.mark.parametrize(
    "change,conflict",
    [({"balance_blocks": 0}, True), ({"payment_type": 1}, True), ({"balance_blocks": 99}, False), ({}, False)],
)
async def test_partial_policy_preserves_contradiction_but_not_unknown_values(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, int],
    conflict: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    synthetic_prepare(factory, transport, purchase, uncertain=False)
    await run(sources, factory)
    before = snapshot(factory)
    get_tariff = sources.require_lbx().get_tariff

    async def changed(**kwargs: object) -> LbxRead[LbxTariff]:
        tariff = await get_tariff(**kwargs)
        return replace(tariff, value=tariff.value.model_copy(update={**change, "dynamic_rent": None}))

    monkeypatch.setattr(sources.require_lbx(), "get_tariff", changed)
    observation = await run(sources, factory)
    assert observation.evidence_document["commercial"] == ("COMPLETE_MISMATCH" if conflict else "INCOMPLETE")
    if conflict:
        assert snapshot(factory)[2:4] == ("blocked", "ineligible")
    else:
        assert snapshot(factory) == before
    assert snapshot(factory)[4:6] == before[4:6]


@pytest.mark.parametrize("entrypoint", ["inventory", "financial_recovery"])
async def test_customer_conflict_withdraws_all_subscriptions_and_fences_old_proof(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], entrypoint: str
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    with factory() as db:
        ids = list(db.scalars(select(ExternalSubscription.subscription_id)))
    from app.composition.reconciliation import reconcile_subscription

    for subscription_id in ids:
        await reconcile_subscription(
            sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=subscription_id
        )
    with factory() as db:
        assert all(
            (sub.financial_access_status, sub.commercial_access_status) == ("allowed", "eligible")
            for sub in db.scalars(select(ExternalSubscription))
        )
        before = {
            sub.subscription_id: (sub.last_authoritative_read_at, sub.projection_valid_until)
            for sub in db.scalars(select(ExternalSubscription))
        }
        target = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.purchase_intent_id == purchase.id)
        )
    subject = claim_reconciliation(factory, config, target, io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        stale = await read_subscription_proof(sources.require_lbx(), subject, config, budget=budget)
    recovery.repair_batch(factory, config)
    transport.customer["outer_id"] = "foreign-key"
    if entrypoint == "inventory":
        worker = BillingWorker(config, factory, sources.require_lbx())
        try:
            assert await worker.tick(WorkLane.NORMAL)
        finally:
            await worker.aclose()
    else:
        with pytest.raises(AppError):
            await recover_financial(sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id)
    with factory() as db:
        assert db.scalar(select(ExternalBillingCustomer)).binding_state == "identity_conflict"
        assert all(
            (sub.financial_access_status, sub.commercial_access_status) == ("blocked", "ineligible")
            for sub in db.scalars(select(ExternalSubscription))
        )
    with factory() as db:
        assert {
            sub.subscription_id: (sub.last_authoritative_read_at, sub.projection_valid_until)
            for sub in db.scalars(select(ExternalSubscription))
        } == before
        assert all(
            queue.priority == 1 and queue.next_attempt_at <= datetime.now(UTC)
            for queue in db.scalars(
                select(BillingWorkItem).where(BillingWorkItem.work_kind == "subscription_reconciliation")
            )
        )
    with pytest.raises(BillingRefused):
        apply_reconciliation(factory, subject, stale)
    current = reserve_customer(factory, config, TOKEN)
    apply_customer_read(factory, current, provider_id=current.provider_id, outer_key=current.outer_key)
    # Pair restoration alone cannot revive old positive facts or a pre-conflict claim.
    with pytest.raises(BillingRefused):
        apply_reconciliation(factory, subject, stale)
    with factory() as db:
        assert all(sub.commercial_access_status == "ineligible" for sub in db.scalars(select(ExternalSubscription)))
    assert service.read_purchase(factory, sibling.user_id, sibling.id).accepted == sibling.accepted


@pytest.mark.parametrize("case", ["ended", "closed"])
@pytest.mark.parametrize("entrypoint", ["advance", "unknown_recovery"])
async def test_terminal_original_recovers_without_false_review_or_create(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], case: str, entrypoint: str
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=entrypoint == "unknown_recovery")
    history = {op.id: original(factory, op.id) for op in purchase.operations}
    if case == "ended":
        transport.subscriptions[0]["state"] = 3
    else:
        transport.agreements[0]["close_date"] = "2026-11-03"
    calls = len(transport.requests)
    if entrypoint == "advance":
        await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=purchase.id)
    else:
        await recover_financial(
            sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.state == "linked" and saved.held and saved.accepted == purchase.accepted
    assert all(op.state == "bound" for op in saved.operations)
    assert {op.id: original(factory, op.id) for op in saved.operations} == history
    with factory() as db:
        assert not list(db.scalars(select(ManualReviewCase)))
        sub = db.scalar(select(ExternalSubscription))
        assert sub.financial_access_status != "allowed" and sub.projection_valid_until <= datetime.now(UTC)
    await run(sources, factory)
    assert snapshot(factory)[1:3] == ("ended", "blocked")
    assert all(request.method == "GET" for request in transport.requests[calls:])


@pytest.mark.parametrize("case", ["ended", "closed"])
async def test_operator_can_bind_proven_terminal_original_without_paid_trust(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], case: str
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == "subscription")
    financial.financial_pending(factory, purchase, operation, conflict=True)
    if case == "ended":
        transport.subscriptions[0]["state"] = 3
    else:
        transport.agreements[0]["close_date"] = "2026-11-03"
    evidence = inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id)
    result = await resolve_review(
        sources,
        step1_settings(),
        factory=factory,
        request=resolution_request(purchase, evidence, bind=True),
        principal=PRINCIPAL,
    )
    assert result["outcome"] == "resolved"
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.state == "linked" and all(op.state == "bound" for op in saved.operations)
    assert snapshot(factory)[2] != "allowed"
    await run(sources, factory)
    assert snapshot(factory)[1:3] == ("ended", "blocked")


async def test_customer_conflict_commit_failure_rolls_back_with_subscription_denial(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    synthetic_prepare(factory, transport, purchase, uncertain=False)
    await run(sources, factory)
    before = snapshot(factory)
    current = service.customer_for_purchase(factory, config, purchase)

    def failed_commit(db: Session) -> None:
        raise RuntimeError("synthetic rollback")

    with monkeypatch.context() as patch:
        patch.setattr(Session, "commit", failed_commit)
        with pytest.raises(RuntimeError, match="synthetic rollback"):
            record_customer_conflict(factory, current, None, provider_id=current.provider_id)
    assert snapshot(factory) == before
    with factory() as db:
        assert db.scalar(select(ExternalBillingCustomer)).binding_state == "bound"
        assert not list(db.scalars(select(ManualReviewCase)))


@pytest.mark.parametrize("entrypoint", ["advance", "recovery"])
async def test_closed_original_agreement_does_not_authorize_next_create(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], entrypoint: str
) -> None:
    from datetime import date

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    operation = next(op for op in purchase.operations if op.kind == "agreement")
    command = NewAgreement(
        user_id=345, organization_id=21, agreement_number=operation.key, create_date=date(2026, 10, 27)
    )
    financial.claim_financial(
        factory, purchase, operation, command.request_document(), configuration=config, token=TOKEN
    )
    transport.agreements.append(
        agreement_factory()
        .model_copy(update={"agreement_number": operation.key, "close_date": "2026-11-03"})
        .model_dump()
    )
    calls = len(transport.requests)
    for _ in range(2):
        if entrypoint == "advance":
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        else:
            await recover_financial(sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.state != "manual_review" and saved.held
    assert next(op for op in saved.operations if op.kind == "agreement").state == "bound"
    assert next(op for op in saved.operations if op.kind == "subscription").state == "pending"
    assert all(request.method == "GET" for request in transport.requests[calls:])
    assert not transport.subscriptions


@pytest.mark.parametrize("case", ["ended", "closed"])
async def test_terminal_advance_hints_reconciliation_without_replacing_authority_or_reviving_trust(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], case: str
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    synthetic_prepare(factory, transport, purchase, uncertain=False)
    await run(sources, factory)
    before = snapshot(factory)
    if case == "ended":
        transport.subscriptions[0]["state"] = 3
    else:
        transport.agreements[0]["close_date"] = "2026-11-03"
    await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert snapshot(factory) == before
    with factory() as db:
        queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == "subscription_reconciliation"))
        assert queue.priority == 1 and queue.next_attempt_at <= datetime.now(UTC)
    await run(sources, factory)
    assert snapshot(factory)[1:3] == ("ended", "blocked")
    transport.subscriptions[0]["state"] = 2
    transport.agreements[0]["close_date"] = None
    await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert snapshot(factory)[1:3] == ("ended", "blocked")
    observation = await run(sources, factory)
    assert observation.result_classification == "subscription_terminal_revival_conflict"


async def test_terminal_recovery_hint_survives_an_earlier_reconciliation_without_false_revival(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    synthetic_prepare(factory, transport, purchase, uncertain=False)
    await run(sources, factory)
    subject = claim_reconciliation(factory, config, snapshot(factory)[0], io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        old_proof = await read_subscription_proof(sources.require_lbx(), subject, config, budget=budget)
    transport.subscriptions[0]["state"] = 3
    await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    apply_reconciliation(factory, subject, old_proof)
    with factory() as db:
        assert not list(db.scalars(select(ManualReviewCase)))
        queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == "subscription_reconciliation"))
        assert queue.priority == 1 and queue.next_attempt_at <= datetime.now(UTC)
    await run(sources, factory)
    assert snapshot(factory)[1:3] == ("ended", "blocked")


@pytest.mark.parametrize("closed", ["2026-11-03", "2026-11-03 12:00:00", "invalid"])
async def test_closed_sibling_does_not_create_inventory_conflict(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], closed: str
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    historical_link(factory, purchase, transport, "brief_decoder", 1)
    transport.agreements[1]["close_date"] = closed
    assert transport.subscriptions[1]["state"] == 2
    recovery.repair_batch(factory, step1_settings())
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.NORMAL)
    finally:
        await worker.aclose()
    assert service.read_purchase(factory, purchase.user_id, purchase.id).state == "linked"
    with factory() as db:
        assert not list(db.scalars(select(ManualReviewCase)))
        queue = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == recovery.INVENTORY))
        assert queue.last_error_classification == ("inventory_incomplete" if closed == "invalid" else None)


async def test_operator_resolution_accepts_closed_sibling_without_resolving_it(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    first, second = await inventory_review(background_scenario, factory, two=True)
    transport.agreements[1]["close_date"] = "2026-11-03"
    evidence = inspect_evidence(factory, step1_settings(), first.user_id, first.id)
    result = await resolve_review(
        sources, step1_settings(), factory=factory, request=resolution_request(first, evidence), principal=PRINCIPAL
    )
    assert result["outcome"] == "resolved"
    assert service.read_purchase(factory, first.user_id, first.id).state == "linked"
    assert service.read_purchase(factory, second.user_id, second.id).state == "manual_review"
