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
