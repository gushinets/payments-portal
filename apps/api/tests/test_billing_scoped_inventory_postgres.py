"""SIMULATED source proof; one inventory owner across admission and operator exits."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.composition.billing import bootstrap_account
from app.composition.billing_operator import resolve_review
from app.composition.sources import SourceResources
from app.domains.catalog.publication import SessionFactory
from app.domains.billing.work_contracts import WorkClaim
from app.domains.purchases.contracts import Purchase
from app.domains.purchases.inventory_contracts import InventoryResult
from app.integrations.lbx.errors import LbxScopeMismatch
from app.integrations.lbx.financial import Subscription
from app.jobs.billing import BillingWorker
from apps.api.tests.support.any709_step3 import PurchaseTransport
from app.composition.purchase_inventory import collect_inventory
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.customers import lock_user
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseRefused
from app.domains.purchases.inventory import validate_inventory
from app.infrastructure.preflight import PreflightBudget
from app.models import (
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ManualReviewCase,
    ExternalCreateOperation,
)
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_subscription_inventory_postgres import add_external_subscription
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    original,
    synthetic_prepare,
)
from apps.api.tests.test_billing_worker_postgres import historical_link
from apps.api.tests.test_any709_step3_postgres import TOKEN

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
PRINCIPAL = "os-euid:1000"


async def inventory(
    sources: SourceResources,
    factory: SessionFactory,
    purchase: Purchase,
    *,
    claim: WorkClaim | None = None,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
) -> InventoryResult:
    current = service.customer_for_purchase(factory, step1_settings(), purchase)
    async with sources.billing.operation(bound_scope=False) as budget:
        return await collect_inventory(
            sources.require_lbx(),
            sources.billing,
            step1_settings(),
            factory=factory,
            customer=current,
            budget=budget,
            work_claim=claim,
            delegate=delegate,
        )


async def conflict_case(
    sources: SourceResources,
    factory: SessionFactory,
    transport: PurchaseTransport,
    purchase: Purchase,
) -> dict:
    recovery.repair_batch(factory, step1_settings())
    claim = work.claim_work(factory, step1_settings(), WorkLane.NORMAL)
    assert claim and claim.kind == recovery.INVENTORY
    result = await inventory(sources, factory, purchase, claim=claim)
    assert purchase.id in result.conflicts
    recovery.apply_inventory(factory, claim, result, "inventory_conflict")
    return inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id)


@pytest.mark.parametrize("missing_calendar", [False, True])
async def test_known_review_is_scoped_and_own_committed_versions_remain_valid(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    missing_calendar: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    second = historical_link(factory, first, transport, "brief_decoder", 1)
    transport.subscriptions[0]["services"][0]["price"] = 15
    if missing_calendar:
        transport.subscriptions[0]["last_tariffication_period_start"] = None
        transport.subscriptions[0]["last_tariffication_period_end"] = None
    result = await inventory(sources, factory, first)
    assert result.complete and not result.conflicts and not result.pending
    result.require_clear(second)
    with factory() as db:
        lock_user(db, first.user_id)
        validate_inventory(db, result)
        cases = list(db.scalars(select(ManualReviewCase)))
        assert [case.reason_code for case in cases] == ["subscription_commercial_mismatch"]
    assert service.read_purchase(factory, first.user_id, first.id).state == "manual_review"
    assert service.read_purchase(factory, second.user_id, second.id).state == "linked"
    again = await inventory(sources, factory, first)
    assert again.complete and not again.conflicts
    again.require_clear(second)


async def test_busy_known_candidate_is_incomplete_without_unleased_point_reads(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        sub.reconciliation_lease_owner = "another-owner"
        sub.reconciliation_lease_expires_at = datetime.now(UTC) + timedelta(minutes=5)
        db.commit()
    start = len(transport.requests)
    result = await inventory(sources, factory, purchase)
    assert not result.complete and not result.conflicts
    assert not any(req.url.path.endswith("/subscriptions/567") for req in transport.requests[start:])
    with factory() as db:
        assert db.scalar(select(ExternalSubscription)).reconciliation_lease_owner == "another-owner"
        assert not list(db.scalars(select(ManualReviewCase)))


@pytest.mark.parametrize("bind", [False, True], ids=["restore-canonical", "bind-pending-original"])
async def test_inventory_review_has_exact_audited_exit_and_reads_target_once(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    bind: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=bind)
    immutable = tuple(original(factory, op.id) for op in purchase.operations)
    add_external_subscription(transport, -2)
    evidence = await conflict_case(sources, factory, transport, purchase)
    request = resolution_request(purchase, evidence, bind=bind)
    # Correct the actual competing source object; keep the original alive.
    transport.subscriptions[-1]["state"] = 3
    start = len(transport.requests)
    outcome = await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert outcome["outcome"] == "resolved"
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.state == "linked" and saved.held
    assert tuple(original(factory, op.id) for op in purchase.operations) == immutable
    requests = transport.requests[start:]
    assert all(req.method == "GET" for req in requests)
    for path in ("/users/345", "/agreements/456", "/subscriptions/567"):
        assert sum(req.url.path.endswith(path) for req in requests) == 1
    with factory() as db:
        case = db.get(ManualReviewCase, request.case_id)
        assert case.case_state == "resolved" and case.resolved_by_principal == PRINCIPAL
        assert case.resolution_document["resolution"] == request.resolution
        assert case.resolution_document["before"]["operations"] != case.resolution_document["after"]["operations"]
    assert (await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL))[
        "outcome"
    ] == "already_resolved"


@pytest.mark.parametrize("failure", ["competitor", "incomplete", "concurrent-operation", "concurrent-sibling"])
async def test_operator_inventory_cannot_clear_unproved_or_stale_result(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = (
        historical_link(factory, purchase, transport, "brief_decoder", 1) if failure == "concurrent-sibling" else None
    )
    add_external_subscription(transport, -2)
    evidence = await conflict_case(sources, factory, transport, purchase)
    request = resolution_request(purchase, evidence)
    if failure != "competitor":
        transport.subscriptions[-1]["state"] = 3
    client = sources.require_lbx()
    discover = client.discover_subscriptions
    calls = 0

    async def interleaved(*, user_id: int, budget: PreflightBudget, **kwargs: Any) -> tuple[Subscription, ...]:
        nonlocal calls
        rows = await discover(user_id=user_id, budget=budget, **kwargs)
        calls += 1
        if failure == "incomplete" and calls == 2:
            return rows[:-1]
        if failure in {"concurrent-operation", "concurrent-sibling"} and calls == 2:
            target = sibling or purchase
            with factory() as db:
                operation = next(op for op in target.operations if op.kind == Kind.SUBSCRIPTION)
                db.get(ExternalCreateOperation, operation.id).send_fence = uuid4()
                db.commit()
        return rows

    monkeypatch.setattr(client, "discover_subscriptions", interleaved)
    with pytest.raises(BillingRefused):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    with factory() as db:
        case = db.get(ManualReviewCase, request.case_id)
        assert case.case_state == "open" and case.resolution_document is None
        assert (
            db.scalar(
                select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchase.id)
            ).commercial_access_status
            == "ineligible"
        )


async def test_pending_candidate_does_not_hide_later_competitor_and_only_stage3_binds(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    result = await inventory(sources, factory, purchase)
    assert result.complete and result.pending == (purchase.id,) and not result.conflicts
    with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
        result.require_clear(purchase)
    assert (
        next(
            op
            for op in service.read_purchase(factory, purchase.user_id, purchase.id).operations
            if op.kind == Kind.SUBSCRIPTION
        ).bound_id
        is None
    )
    add_external_subscription(transport, -2)
    result = await inventory(sources, factory, purchase)
    assert result.pending == (purchase.id,) and result.conflicts == (purchase.id,)
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        result.require_clear(purchase, original=True)


async def test_canonical_negative_survives_incomplete_discovery(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    transport.agreements[0]["close_date"] = "2026-10-28"
    from app.integrations.lbx.errors import LbxResponseInvalid

    async def incomplete(**kwargs: Any) -> tuple[Subscription, ...]:
        raise LbxResponseInvalid()

    monkeypatch.setattr(sources.require_lbx(), "discover_subscriptions", incomplete)
    result = await inventory(sources, factory, purchase)
    assert not result.complete and not result.conflicts
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        assert sub.lifecycle_status == "ended" and sub.financial_access_status == "blocked"
        assert not list(db.scalars(select(ManualReviewCase)))


async def test_restore_tracks_its_sibling_transition_without_resolving_sibling_review(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.composition.billing_operator import reconcile_purchase

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    transport.subscriptions[0]["services"][0]["price"] = 15
    await reconcile_purchase(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    request = resolution_request(purchase, inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id))
    transport.subscriptions[0]["services"][0]["price"] = 100
    transport.subscriptions[1]["services"][0]["price"] = 15
    result = await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert result["outcome"] == "resolved"
    assert service.read_purchase(factory, purchase.user_id, purchase.id).state == "linked"
    assert service.read_purchase(factory, sibling.user_id, sibling.id).state == "manual_review"
    with factory() as db:
        cases = list(db.scalars(select(ManualReviewCase)))
        assert len(cases) == 2
        assert sum(case.case_state == "resolved" for case in cases) == 1
        assert db.get(ManualReviewCase, request.case_id).case_state == "resolved"


async def test_restore_resolves_only_proved_related_inventory_and_canonical_cases(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    transport.subscriptions[0]["services"][0]["price"] = 15
    add_external_subscription(transport, -2)
    evidence = await conflict_case(sources, factory, transport, purchase)
    assert len(evidence["reviews"]) == 2
    request = resolution_request(purchase, evidence)
    transport.subscriptions[0]["services"][0]["price"] = 100
    transport.subscriptions[-1]["state"] = 3
    await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    with factory() as db:
        cases = list(db.scalars(select(ManualReviewCase)))
        assert len(cases) == 2 and all(case.case_state == "resolved" for case in cases)
        assert all(case.resolved_by_principal == PRINCIPAL for case in cases)
        assert all(case.resolution_document["proof"]["commercial"] == "COMPLETE_MATCH" for case in cases)


async def test_closed_foreign_agreement_is_not_a_live_competitor(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    add_external_subscription(transport, -2)
    transport.agreements[-1]["close_date"] = "2026-10-28"
    result = await inventory(sources, factory, purchase)
    assert result.complete and not result.conflicts and not result.pending
    result.require_clear(purchase)


async def test_background_competitor_preserves_unsent_history_without_review(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    immutable = tuple(original(factory, op.id) for op in purchase.operations)
    add_external_subscription(transport, -2)
    evidence = await conflict_case(sources, factory, transport, purchase)
    assert not evidence["reviews"]
    current = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert current.state != "manual_review" and current.held
    assert all(op.state == "pending" for op in current.operations)
    assert all(op.fence != prior.fence for op, prior in zip(current.operations, purchase.operations))
    assert tuple(original(factory, op.id) for op in current.operations) == immutable
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("entrypoint", ["collect_inventory", "worker"])
@pytest.mark.parametrize("conflict", ["original_key", "scope_error"])
async def test_inventory_customer_conflict_preserves_only_proven_original_key_recovery(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
    conflict: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    customer = service.customer_for_purchase(factory, config, purchase)
    client = sources.require_lbx()
    get_user = client.get_user
    creates = tuple(transport.creates(path) for path in ("/users", "/agreements", "/subscriptions"))
    started = len(transport.requests)
    if conflict == "original_key":
        transport.customer["outer_id"] = "synthetic-wrong-key"
    else:

        async def scope_error(**kwargs: Any) -> None:
            raise LbxScopeMismatch()

        monkeypatch.setattr(client, "get_user", scope_error)
    if entrypoint == "collect_inventory":
        result = await inventory(sources, factory, purchase)
        assert not result.complete
    else:
        recovery.repair_batch(factory, config)
        worker = BillingWorker(config, factory, client)
        try:
            assert await worker.tick(WorkLane.NORMAL)
        finally:
            await worker.aclose()
    with factory() as db:
        case = db.scalars(select(ManualReviewCase)).one()
        assert (case.scope_kind, case.scope_reference) == ("create_operation", str(customer.operation_id))
        assert case.case_state == "open"
        assert case.reason_code == (
            "customer_original_key_mismatch" if conflict == "original_key" else "customer_identity_conflict"
        )
        case_id = case.review_case_id
        assert db.get(ExternalBillingCustomer, customer.customer_id).binding_state == Binding.IDENTITY_CONFLICT
    transport.customer["outer_id"] = customer.outer_key
    monkeypatch.setattr(client, "get_user", get_user)
    before_open = len(transport.requests)
    if conflict == "original_key":
        widget = await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        assert widget.credential
        assert any(request.url.path.endswith("/users/345") for request in transport.requests[before_open:])
    else:
        # A generic source-scope contradiction has no paired original-ID proof.
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        assert len(transport.requests) == before_open
    with factory() as db:
        current = db.scalars(select(ExternalBillingCustomer)).one()
        operation = db.get(ExternalCreateOperation, customer.operation_id)
        case = db.get(ManualReviewCase, case_id)
        assert (current.customer_id, current.provider_customer_id, current.billing_customer_key) == (
            customer.customer_id,
            customer.provider_id,
            customer.outer_key,
        )
        assert (operation.bound_external_object_id, operation.request_correlation_key) == (
            customer.provider_id,
            customer.outer_key,
        )
        if conflict == "original_key":
            assert current.binding_state == Binding.BOUND and operation.operation_state == State.BOUND
            assert case.case_state == "resolved" and case.resolved_by_principal == "system:customer-point-read"
            assert case.resolution_document["proof"] == "original_customer_point_read"
        else:
            assert (
                current.binding_state == Binding.IDENTITY_CONFLICT and operation.operation_state == State.MANUAL_REVIEW
            )
            assert case.case_state == "open" and case.resolution_document is None
    assert tuple(transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")) == creates
    assert all(request.method == "GET" for request in transport.requests[started:])
    assert service.read_purchase(factory, purchase.user_id, purchase.id) == purchase


@pytest.mark.parametrize(
    "tariff,ended,closed", [(999, False, False), (701, False, False), (999, True, False), (999, False, True)]
)
async def test_dedicated_agreement_competitor_is_scoped_independently_of_tariff(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    tariff: int,
    ended: bool,
    closed: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    extra = {**transport.subscriptions[0], "subscription_id": 9999, "tariff_id": tariff, "state": 3 if ended else 2}
    transport.subscriptions.append(extra)
    if closed:
        transport.agreements[0]["close_date"] = "2026-11-05"
    recovery.repair_batch(factory, step1_settings())
    claim = work.claim_work(factory, step1_settings(), WorkLane.NORMAL)
    assert claim and claim.kind == recovery.INVENTORY
    result = await inventory(sources, factory, purchase, claim=claim)
    assert result.complete
    conflict = not ended and not closed
    assert (purchase.id in result.conflicts) is conflict
    assert (sibling.id in result.conflicts) is (conflict and tariff == 701)
    if conflict:
        with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
            result.require_clear(purchase, original=True)
    else:
        result.require_clear(purchase, original=True)
    recovery.apply_inventory(factory, claim, result, "inventory_conflict" if conflict else None)
    with factory() as db:
        reviews = list(db.scalars(select(ManualReviewCase)))
        if conflict:
            owner_sub = db.scalar(
                select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchase.id)
            )
            assert owner_sub.commercial_access_status == "ineligible"
            assert reviews
        else:
            assert not reviews
    if conflict:
        evidence = inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id)
        request = resolution_request(purchase, evidence)
        with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
            await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
        with factory() as db:
            case = db.get(ManualReviewCase, request.case_id)
            assert case.case_state == "open" and case.resolution_document is None
    assert not any(req.method == "POST" for req in transport.requests)


@pytest.mark.parametrize("conflict", ["original_key", "scope_error"])
@pytest.mark.parametrize("entrypoint", ["collector", "worker"])
async def test_unknown_candidate_customer_conflict_invalidates_every_subscription(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    conflict: str,
    entrypoint: str,
) -> None:
    from app.composition.billing_background import inventory_customer
    from app.composition.purchases import recover_financial
    from app.composition.reconciliation import read_subscription_proof, reconcile_subscription
    from app.domains.billing.reconciliation import claim_reconciliation, apply_reconciliation
    from app.domains.purchases.inventory_contracts import InventoryStale

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    historical_link(factory, purchase, transport, "brief_decoder", 1)
    transport.subscriptions[1].update(
        state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-11-01"
    )
    with factory() as db:
        sibling_id = db.scalar(select(ExternalSubscription.subscription_id))
    await reconcile_subscription(
        sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=sibling_id
    )
    old = claim_reconciliation(factory, config, sibling_id, io_timeout_seconds=60)
    async with sources.billing.operation(bound_scope=False) as budget:
        old_proof = await read_subscription_proof(sources.require_lbx(), old, config, factory=factory, budget=budget)
    client = sources.require_lbx()
    get_user = client.get_user
    reads = 0

    async def changed_second_read(**kwargs: Any) -> Any:
        nonlocal reads
        reads += 1
        if reads == 2:
            if conflict == "scope_error":
                raise LbxScopeMismatch()
            return (await get_user(**kwargs)).model_copy(update={"outer_id": "changed-original-key"})
        return await get_user(**kwargs)

    monkeypatch.setattr(client, "get_user", changed_second_read)
    recovery.repair_batch(factory, config)
    claim = work.claim_work(factory, config, WorkLane.NORMAL)
    assert claim and claim.kind == recovery.INVENTORY
    if entrypoint == "collector":
        with pytest.raises(InventoryStale):
            await inventory(sources, factory, purchase, claim=claim)
    else:
        async with sources.billing.operation(bound_scope=False) as budget:
            await inventory_customer(
                client, sources.billing, config, factory=factory, claim=claim, budget=budget, delegate=run_in_threadpool
            )
    assert reads == 2
    with factory() as db:
        customer = db.get(ExternalBillingCustomer, purchase.customer_id)
        assert customer.binding_state == Binding.IDENTITY_CONFLICT
        sub = db.get(ExternalSubscription, sibling_id)
        assert (sub.financial_access_status, sub.commercial_access_status) == ("blocked", "ineligible")
        assert sub.reconciliation_fencing_token > old.fence
        assert sub.reconciliation_lease_owner is None and sub.reconciliation_lease_expires_at is None
        cases = list(db.scalars(select(ManualReviewCase)))
        assert len(cases) == 1 and cases[0].scope_kind == "create_operation"
        assert cases[0].scope_reference == str(old.customer.operation_id)
        assert cases[0].reason_code == (
            "customer_original_key_mismatch" if conflict == "original_key" else "customer_identity_conflict"
        )
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        apply_reconciliation(factory, old, old_proof)
    monkeypatch.setattr(client, "get_user", get_user)
    if conflict == "original_key":
        await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        saved = await recover_financial(
            sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
        assert saved.state == "linked" and saved.accepted == purchase.accepted
        with factory() as db:
            assert db.get(ExternalBillingCustomer, purchase.customer_id).binding_state == Binding.BOUND
            assert all(case.case_state == "resolved" for case in db.scalars(select(ManualReviewCase)))
    else:
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN)
    assert not any(req.method == "POST" for req in transport.requests)


@pytest.mark.parametrize(
    "case,omitted",
    [
        ("dedicated", False),
        ("moved", False),
        ("moved-other-tariff", False),
        ("lag", False),
        ("misleading", False),
        ("ended", False),
        ("closed", False),
        ("busy", False),
        ("dedicated", True),
        ("moved", True),
        ("moved-other-tariff", True),
        ("ended", True),
        ("closed", True),
    ],
)
async def test_known_sibling_cannot_hide_a_shared_dedicated_agreement(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    omitted: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    transport.pool = factory.kw["bind"].pool
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-11-01")
    old = old_proof = None
    if case == "busy":
        from app.composition.reconciliation import reconcile_subscription, read_subscription_proof
        from app.domains.billing.reconciliation import claim_reconciliation

        with factory() as db:
            sibling_id = db.scalar(
                select(ExternalSubscription.subscription_id).where(
                    ExternalSubscription.purchase_intent_id == sibling.id
                )
            )
        await reconcile_subscription(
            sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=sibling_id
        )
        old = claim_reconciliation(factory, config, sibling_id, io_timeout_seconds=60)
        async with sources.billing.operation(bound_scope=False) as budget:
            old_proof = await read_subscription_proof(
                sources.require_lbx(), old, config, factory=factory, budget=budget
            )
    if case not in {"dedicated", "misleading"}:
        transport.subscriptions[1]["agreement_id"] = 456
    if case in {"moved-other-tariff", "busy"}:
        transport.subscriptions[1]["tariff_id"] = 999
    if case == "ended":
        transport.subscriptions[1]["state"] = 3
    if case == "closed":
        transport.agreements[0]["close_date"] = "2026-11-05"
    if case in {"lag", "misleading"}:
        discover = sources.require_lbx().discover_subscriptions

        async def stale_listing(**kwargs: Any) -> tuple[Subscription, ...]:
            rows = await discover(**kwargs)
            return tuple(
                row.model_copy(update={"agreement_id": 457 if case == "lag" else 456})
                if row.subscription_id == 568
                else row
                for row in rows
            )

        monkeypatch.setattr(sources.require_lbx(), "discover_subscriptions", stale_listing)
    if omitted:
        discover = sources.require_lbx().discover_subscriptions

        async def omit_known(**kwargs: Any) -> tuple[Subscription, ...]:
            return tuple(row for row in await discover(**kwargs) if row.subscription_id != 568)

        monkeypatch.setattr(sources.require_lbx(), "discover_subscriptions", omit_known)
    recovery.repair_batch(factory, config)
    claim = work.claim_work(factory, config, WorkLane.NORMAL)
    assert claim and claim.kind == recovery.INVENTORY
    result = await inventory(sources, factory, purchase, claim=claim)
    conflict = case in {"moved", "moved-other-tariff", "lag", "busy"}
    assert (purchase.id in result.conflicts) is conflict
    assert (sibling.id in result.conflicts) is conflict
    if case == "dedicated":
        assert result.complete and not result.conflicts
    reason = "inventory_conflict" if result.conflicts else "inventory_incomplete" if not result.complete else None
    recovery.apply_inventory(factory, claim, result, reason)
    if old is not None:
        from app.domains.billing.reconciliation import apply_reconciliation

        with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
            apply_reconciliation(factory, old, old_proof)
    with factory() as db:
        target = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchase.id))
        assert target.commercial_access_status == ("ineligible" if conflict else "eligible")
    if conflict:
        with pytest.raises(BillingRefused, match="purchase_not_prepared"):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        evidence = inspect_evidence(factory, config, purchase.user_id, purchase.id)
        request = resolution_request(purchase, evidence)
        with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
            await resolve_review(sources, config, factory=factory, request=request, principal=PRINCIPAL)
        with factory() as db:
            case_row = db.get(ManualReviewCase, request.case_id)
            assert case_row.case_state == "open" and case_row.resolution_document is None
    elif case == "closed":
        with pytest.raises(BillingRefused, match="purchase_not_prepared"):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    else:
        widget = await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert widget.credential and widget.purchase_id == purchase.id
    with factory() as db:
        # Neither discovery nor a changed provider relationship may rebind history.
        first = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == purchase.id))
        second = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == sibling.id))
        assert (first.external_subscription_id, first.external_agreement_id) == ("567", "456")
        assert (second.external_subscription_id, second.external_agreement_id) == ("568", "457")
    assert not any(req.method == "POST" for req in transport.requests)


async def test_known_sibling_is_never_an_unknown_original_candidate(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    transport.subscriptions.pop(0)
    transport.subscriptions[0]["agreement_id"] = 456
    result = await inventory(sources, factory, purchase)
    assert purchase.id in result.conflicts and purchase.id not in result.pending
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    operation = next(op for op in saved.operations if op.kind == Kind.SUBSCRIPTION)
    assert operation.bound_id is None and operation.state == State.POSSIBLE_SEND
    saved_sibling = service.read_purchase(factory, sibling.user_id, sibling.id)
    assert next(op for op in saved_sibling.operations if op.kind == Kind.SUBSCRIPTION).bound_id == "568"
    assert not any(req.method == "POST" for req in transport.requests)


@pytest.mark.parametrize("conflict", ["none", "original_key", "scope_error"])
async def test_restore_original_persists_customer_negative_before_busy_inventory(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    conflict: str,
) -> None:
    from app.composition.reconciliation import read_subscription_proof, reconcile_subscription
    from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-11-01")
    with factory() as db:
        identities = {sub.purchase_intent_id: sub.subscription_id for sub in db.scalars(select(ExternalSubscription))}
    for identity in identities.values():
        await reconcile_subscription(
            sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=identity
        )
    transport.subscriptions[0]["services"][0]["price"] = 150
    await reconcile_subscription(
        sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=identities[purchase.id]
    )
    transport.subscriptions[0]["services"][0]["price"] = 100
    request = resolution_request(purchase, inspect_evidence(factory, config, purchase.user_id, purchase.id))
    client = sources.require_lbx()
    get_user = client.get_user
    if conflict == "none":
        result = await resolve_review(sources, config, factory=factory, request=request, principal=PRINCIPAL)
        assert result["outcome"] == "resolved"
    else:
        old = claim_reconciliation(factory, config, identities[sibling.id], io_timeout_seconds=60)
        async with sources.billing.operation(bound_scope=False) as budget:
            old_proof = await read_subscription_proof(client, old, config, factory=factory, budget=budget)
        reads = 0

        async def negative_read(**kwargs: Any) -> Any:
            nonlocal reads
            reads += 1
            if conflict == "scope_error":
                raise LbxScopeMismatch()
            return (await get_user(**kwargs)).model_copy(update={"outer_id": "changed-original-key"})

        monkeypatch.setattr(client, "get_user", negative_read)
        with pytest.raises(PurchaseRefused, match="billing_review_stale"):
            await resolve_review(sources, config, factory=factory, request=request, principal=PRINCIPAL)
        assert reads == 1
        with factory() as db:
            assert db.get(ExternalBillingCustomer, purchase.customer_id).binding_state == Binding.IDENTITY_CONFLICT
            for sub in db.scalars(select(ExternalSubscription)):
                assert (sub.financial_access_status, sub.commercial_access_status) == ("blocked", "ineligible")
                assert sub.reconciliation_lease_owner is None and sub.reconciliation_lease_expires_at is None
            assert db.get(ExternalSubscription, identities[sibling.id]).reconciliation_fencing_token > old.fence
            case = db.get(ManualReviewCase, request.case_id)
            assert case.case_state == "open" and case.resolution_document is None
            customer_cases = list(
                db.scalars(select(ManualReviewCase).where(ManualReviewCase.scope_kind == "create_operation"))
            )
            assert len(customer_cases) == 1
            assert customer_cases[0].scope_reference == str(old.customer.operation_id)
            assert customer_cases[0].reason_code == (
                "customer_original_key_mismatch" if conflict == "original_key" else "customer_identity_conflict"
            )
        with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
            apply_reconciliation(factory, old, old_proof)
        monkeypatch.setattr(client, "get_user", get_user)
        if conflict == "scope_error":
            with pytest.raises(BillingRefused, match="billing_identity_conflict"):
                await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        else:
            # Exact original-key recovery remains available without an extra purchase review.
            await bootstrap_account(sources, config, factory=factory, token=TOKEN)
            request = resolution_request(purchase, inspect_evidence(factory, config, purchase.user_id, purchase.id))
            result = await resolve_review(sources, config, factory=factory, request=request, principal=PRINCIPAL)
            assert result["outcome"] == "resolved"
    if conflict != "scope_error":
        with factory() as db:
            assert db.get(ExternalBillingCustomer, purchase.customer_id).binding_state == Binding.BOUND
            case = db.get(ManualReviewCase, request.case_id)
            assert case.case_state == "resolved" and case.resolved_by_principal == PRINCIPAL
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.accepted == purchase.accepted
    assert tuple((op.id, op.bound_id, op.key) for op in saved.operations) == tuple(
        (op.id, op.bound_id, op.key) for op in purchase.operations
    )
    assert not any(req.method == "POST" for req in transport.requests)
