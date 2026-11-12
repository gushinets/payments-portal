"""SIMULATED source proof; one inventory owner across admission and operator exits."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.composition.billing import bootstrap_account
from app.composition.billing_operator import resolve_review
from app.composition.sources import SourceResources
from app.domains.catalog.publication import SessionFactory
from app.domains.billing.discovery import apply_inventory, persist_discoveries
from app.domains.billing.paid_policy import CandidateConclusion as Conclusion
from app.domains.billing.reconciliation_contracts import RECONCILIATION_SCHEMA
from app.domains.billing.work_contracts import WorkClaim
from app.domains.purchases.contracts import Purchase
from app.domains.purchases.inventory_contracts import InventoryCandidateProof, InventoryResult
from app.integrations.lbx.errors import LbxResponseInvalid, LbxScopeMismatch
from app.integrations.lbx.financial import Agreement, Subscription
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
    BillingProductAccessScope,
    BillingStateObservation,
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


@pytest.fixture
async def bound_point_relationship_scenario(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> tuple[PurchaseTransport, SourceResources, Purchase, Purchase, Purchase, list[tuple[Subscription, ...]]]:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    second = historical_link(factory, first, transport, "brief_decoder", 1, tariff_id=702)
    third = historical_link(factory, first, transport, "acceptance_builder", 2, tariff_id=703)
    for point in transport.subscriptions:
        point.update(state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31")
    transport.subscriptions[0]["tariff_id"] = 702
    discover = sources.require_lbx().discover_subscriptions
    listings: list[tuple[Subscription, ...]] = []

    async def listing(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget)
        rows = tuple(
            row.model_copy(update={"tariff_id": 701}) if row.subscription_id == 567 else row
            for row in rows
            if not request.param or row.subscription_id != 567
        )
        listings.append(rows)
        return rows

    monkeypatch.setattr(sources.require_lbx(), "discover_subscriptions", listing)
    return transport, sources, first, second, third, listings


@pytest.mark.parametrize("bound_point_relationship_scenario", [False, True], indirect=True, ids=["old", "omitted"])
@pytest.mark.parametrize("condition", ["active", "policy-unavailable", "ended", "closed"])
async def test_bound_point_tariff_blocks_implicated_primary_write(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    condition: str,
) -> None:
    transport, sources, first, second, third, listings = bound_point_relationship_scenario
    factory = postgres_session_factory
    if condition == "ended":
        transport.subscriptions[0]["state"] = 3
    if condition == "closed":
        transport.agreements[0]["close_date"] = "2026-11-05"
    if condition == "policy-unavailable":
        read = sources.require_lbx().get_tariff

        async def tariff(*, tariff_id: int, budget: PreflightBudget) -> Any:
            if tariff_id == 701:
                raise LbxResponseInvalid()
            return await read(tariff_id=tariff_id, budget=budget)

        monkeypatch.setattr(sources.require_lbx(), "get_tariff", tariff)
    recovery.repair_batch(factory, step1_settings())
    claim = work.claim_work(factory, step1_settings(), WorkLane.NORMAL)
    assert claim and claim.kind == recovery.INVENTORY
    result = await inventory(sources, factory, first, claim=claim)
    result = persist_discoveries(factory, claim, result)
    apply_inventory(factory, claim, result, "inventory_incomplete", clock_skew_seconds=10)
    with factory() as db:
        selected = {
            row.product_id for row in db.scalars(select(BillingProductAccessScope)) if row.primary_subscription_id
        }
        assert selected == {third.accepted.selection.product_id}
        if condition != "policy-unavailable":
            assert service.read_purchase(factory, first.user_id, first.id).state == "manual_review"
            assert any(
                case.reason_code == "subscription_commercial_mismatch" for case in db.scalars(select(ManualReviewCase))
            )
    canonical = next(source for source in result.sources if source.purchase.id == first.id)
    assert canonical.proof.point_relationship.agreement_id == "456"
    assert canonical.proof.point_relationship.tariff_id == 702
    if condition == "policy-unavailable":
        assert canonical.proof.commercial == "INCOMPLETE"
    assert len(listings) == 2 and listings[0] == listings[1]
    for target in (first, second):
        product = next(item for item in result.products if item.product_id == target.accepted.selection.product_id)
        assert not product.complete
        with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
            result.require_clear(target, primary=True)
    result.require_clear(third, primary=True)
    with pytest.raises(PurchaseRefused):
        result.require_clear(third)  # Financial CREATE keeps its customer-wide boundary.
    assert sum(req.url.path.endswith("/subscriptions/567") for req in transport.requests) == 1
    assert all(req.method == "GET" for req in transport.requests)


@pytest.mark.parametrize("bound_point_relationship_scenario", [False], indirect=True)
async def test_later_terminal_point_preserves_all_bound_relationship_implications(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, first, _, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings()
    client = sources.require_lbx()
    read, discover = client.get_subscription, client.discover_subscriptions
    point_reads = 0

    async def changing_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        nonlocal point_reads
        point = await read(subscription_id=subscription_id, budget=budget)
        if subscription_id == 567:
            point_reads += 1
            point = point.model_copy(
                update={
                    "agreement_id": 457 if point_reads == 1 else 458,
                    "tariff_id": 702 if point_reads == 1 else 703,
                    "state": 2 if point_reads == 1 else 3,
                }
            )
        return point

    async def listing(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget)
        return tuple(
            row.model_copy(update={"agreement_id": 458, "tariff_id": 703, "state": 3})
            if row.subscription_id == 567
            else row
            for row in rows
        )

    monkeypatch.setattr(client, "get_subscription", changing_point)
    monkeypatch.setattr(client, "discover_subscriptions", listing)
    recovery.repair_batch(factory, config)
    claim = work.claim_work(factory, config, WorkLane.NORMAL)
    assert claim and claim.kind == recovery.INVENTORY
    result = await inventory(sources, factory, first, claim=claim)
    result = persist_discoveries(factory, claim, result)
    apply_inventory(factory, claim, result, "inventory_incomplete", clock_skew_seconds=10)
    with factory() as db:
        assert not any(scope.primary_subscription_id for scope in db.scalars(select(BillingProductAccessScope)))
        assert any(
            case.reason_code == "subscription_identity_conflict" for case in db.scalars(select(ManualReviewCase))
        )
    assert all(not product.complete for product in result.products)
    assert point_reads == 2


@pytest.mark.parametrize("bound_point_relationship_scenario", [False, True], indirect=True, ids=["old", "omitted"])
async def test_reused_bound_point_relationship_blocks_implicated_product(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.composition.reconciliation import reconcile_subscription

    transport, sources, first, second, third, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings()
    source = await reconcile_subscription(
        sources.require_lbx(),
        sources.billing,
        config,
        factory=factory,
        subscription_id=service.linked_subscription_id(factory, first),
    )
    with factory() as db:
        observation = db.get(BillingStateObservation, source.observation_id)
        assert observation.evidence_document["point_relationship"] == {"agreement_id": "456", "tariff_id": 702}
    async with sources.billing.operation(bound_scope=False) as budget:
        result = await collect_inventory(
            sources.require_lbx(),
            sources.billing,
            config,
            factory=factory,
            customer=source.subject.customer,
            budget=budget,
            reuse=InventoryCandidateProof(source.purchase, "567", source.proof),
        )
    with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
        result.require_clear(second, primary=True)
    result.require_clear(third, primary=True)
    assert sum(req.url.path.endswith("/subscriptions/567") for req in transport.requests) == 1
    assert service.read_purchase(factory, first.user_id, first.id).state == "manual_review"


async def test_retained_source_without_optional_relationship_can_select_primary(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    transport.subscriptions[0].update(
        state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31"
    )
    recovery.repair_batch(factory, config)
    claim = work.claim_work(factory, config, WorkLane.NORMAL)
    assert claim and claim.kind == recovery.INVENTORY

    def retain_legacy_document(db: Session, flush_context: object, instances: object) -> None:
        for row in db.new:
            if isinstance(row, BillingStateObservation) and row.evidence_schema_version == RECONCILIATION_SCHEMA:
                document = dict(row.evidence_document)
                document.pop("point_relationship", None)
                row.evidence_document = document

    event.listen(Session, "before_flush", retain_legacy_document)
    try:
        result = await inventory(sources, factory, purchase, claim=claim)
    finally:
        event.remove(Session, "before_flush", retain_legacy_document)
    result = replace(
        result,
        sources=tuple(
            replace(source, proof=replace(source.proof, point_relationship=None)) for source in result.sources
        ),
    )
    result = persist_discoveries(factory, claim, result)
    apply_inventory(factory, claim, result, None, clock_skew_seconds=10)
    with factory() as db:
        assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) == service.linked_subscription_id(
            factory, purchase
        )
        for source in result.sources:
            assert "point_relationship" not in db.get(BillingStateObservation, source.observation_id).evidence_document


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
    apply_inventory(factory, claim, result, "inventory_conflict")
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


@pytest.mark.parametrize(
    "case",
    [
        "subscription-failure",
        "agreement-failure",
        "agreement-disagreement",
        "tariff-disagreement",
        "final-list-change",
        "conflict",
        "ended",
        "closed",
    ],
)
async def test_inventory_preserves_every_product_implicated_by_list_and_point(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    extra = {**transport.subscriptions[1], "subscription_id": 9999, "state": 2 if case == "conflict" else 3}
    transport.subscriptions.append(extra)
    for point in transport.subscriptions:
        point.update(last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31")
    if case == "closed":
        extra["state"] = 2
        transport.agreements[1]["close_date"] = "2026-11-05"
    client = sources.require_lbx()
    read, agreement, discover = client.get_subscription, client.get_agreement, client.discover_subscriptions
    reading_extra = False
    listings: list[tuple[Subscription, ...]] = []

    async def read_candidate(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        nonlocal reading_extra
        reading_extra = subscription_id == 9999
        if reading_extra and case == "subscription-failure":
            raise LbxResponseInvalid()
        return await read(subscription_id=subscription_id, budget=budget)

    async def read_agreement(*, agreement_id: int, budget: PreflightBudget) -> Agreement:
        if reading_extra and case == "agreement-failure":
            raise LbxResponseInvalid()
        return await agreement(agreement_id=agreement_id, budget=budget)

    async def listing(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget)
        if case == "agreement-disagreement":
            rows = tuple(
                row.model_copy(update={"agreement_id": 456}) if row.subscription_id == 9999 else row for row in rows
            )
        if case == "tariff-disagreement" or (case == "final-list-change" and listings):
            rows = tuple(
                row.model_copy(update={"tariff_id": 999}) if row.subscription_id == 9999 else row for row in rows
            )
        listings.append(rows)
        return rows

    monkeypatch.setattr(client, "get_subscription", read_candidate)
    monkeypatch.setattr(client, "get_agreement", read_agreement)
    monkeypatch.setattr(client, "discover_subscriptions", listing)
    recovery.repair_batch(factory, step1_settings())
    claim = work.claim_work(factory, step1_settings(), WorkLane.NORMAL)
    assert claim and claim.kind == recovery.INVENTORY
    result = await inventory(sources, factory, purchase, claim=claim)
    clear = case in {"ended", "closed"}
    assert len(listings) == 2
    assert (listings[0] == listings[1]) is (case != "final-list-change")
    for target in (purchase, sibling):
        product = next(item for item in result.products if item.product_id == target.accepted.selection.product_id)
        assert product.complete is clear
        candidate = next(item for item in product.candidates if item.identity == "9999")
        assert candidate.conclusion == (
            Conclusion.INELIGIBLE if clear or case == "final-list-change" else Conclusion.INCOMPLETE
        )
        if clear:
            result.require_clear(target, primary=True)
        else:
            with pytest.raises(PurchaseRefused):
                result.require_clear(target, primary=True)
    assert result.complete is (clear or case == "conflict")
    assert set(result.conflicts) == ({purchase.id, sibling.id} if case == "conflict" else set())
    if not clear:
        with pytest.raises(PurchaseRefused):
            result.require_clear(purchase)  # Financial CREATE remains customer-wide.
    result = persist_discoveries(factory, claim, result)
    apply_inventory(factory, claim, result, None if clear else "inventory_incomplete", clock_skew_seconds=10)
    with factory() as db:
        selected = {
            scope.product_id
            for scope in db.scalars(select(BillingProductAccessScope))
            if scope.primary_subscription_id is not None
        }
        assert selected == (
            {"proposal_ai", "brief_decoder"} if case == "ended" else {"proposal_ai"} if clear else set()
        )
    assert not any(req.method == "POST" for req in transport.requests)


@pytest.mark.parametrize(
    "case,omitted",
    [
        ("subscription-failure", False),
        ("agreement-failure", False),
        ("agreement-disagreement", False),
        ("tariff-disagreement", False),
        ("subscription-failure", True),
        ("agreement-failure", True),
    ],
)
async def test_bound_candidate_keeps_both_sides_of_incomplete_or_contradictory_evidence(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    omitted: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    client = sources.require_lbx()
    read, agreement, discover = client.get_subscription, client.get_agreement, client.discover_subscriptions

    async def read_candidate(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 568 and case == "subscription-failure":
            raise LbxResponseInvalid()
        return await read(subscription_id=subscription_id, budget=budget)

    async def read_agreement(*, agreement_id: int, budget: PreflightBudget) -> Agreement:
        if agreement_id == 457 and case == "agreement-failure":
            raise LbxResponseInvalid()
        return await agreement(agreement_id=agreement_id, budget=budget)

    async def listing(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget)
        changes = {"agreement_id": 456} if case == "agreement-disagreement" else {"tariff_id": 999}
        return tuple(
            row.model_copy(update=changes) if row.subscription_id == 568 and case.endswith("disagreement") else row
            for row in rows
            if not omitted or row.subscription_id != 568
        )

    monkeypatch.setattr(client, "get_subscription", read_candidate)
    monkeypatch.setattr(client, "get_agreement", read_agreement)
    monkeypatch.setattr(client, "discover_subscriptions", listing)
    result = await inventory(sources, factory, purchase)
    assert not result.complete
    assert all(not product.complete for product in result.products)
    for target in (purchase, sibling):
        with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
            result.require_clear(target, primary=True)


@pytest.mark.parametrize("case", ["unchanged", "matching-original", "foreign-point"])
async def test_original_recovery_proof_cannot_discard_point_product_implications(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1, uncertain_subscription=True)
    immutable = tuple(original(factory, op.id) for op in sibling.operations)
    if case == "foreign-point":
        transport.subscriptions[1]["agreement_id"] = 456
    discover = sources.require_lbx().discover_subscriptions

    async def listing(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget)
        return tuple(
            row.model_copy(update={"agreement_id": 457, "tariff_id": 999})
            if row.subscription_id == 568 and case != "unchanged"
            else row
            for row in rows
        )

    monkeypatch.setattr(sources.require_lbx(), "discover_subscriptions", listing)
    result = await inventory(sources, factory, purchase)
    assert result.complete is (case == "unchanged")
    assert result.pending == (() if case == "foreign-point" else (sibling.id,))
    assert result.conflicts == ((sibling.id,) if case == "foreign-point" else ())
    for target in (purchase, sibling):
        product = next(item for item in result.products if item.product_id == target.accepted.selection.product_id)
        assert not product.complete
        assert any(item.identity == "568" and item.conclusion == Conclusion.INCOMPLETE for item in product.candidates)
        with pytest.raises(PurchaseRefused):
            result.require_clear(target, primary=True)
    saved = service.read_purchase(factory, sibling.user_id, sibling.id)
    assert next(op for op in saved.operations if op.kind == Kind.SUBSCRIPTION).bound_id is None
    assert tuple(original(factory, op.id) for op in saved.operations) == immutable
    assert not any(req.method == "POST" for req in transport.requests)


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
    apply_inventory(factory, claim, result, "inventory_conflict" if conflict else None)
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
    apply_inventory(factory, claim, result, reason)
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
