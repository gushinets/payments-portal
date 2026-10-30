"""Known customer conflicts cannot be cleared by ordinary discovery/readback."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.purchases import advance_purchase
from app.composition.sources import source_resources
from app.core.time import utc_now
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import (
    apply_customer_read,
    claim_customer_send,
    escalate_overdue_customers,
    recheck_widget_session,
    reserve_customer,
)
from app.domains.purchases.service import read_purchase
from app.models import (
    BillingPurchaseScopeHold,
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    LegalAcceptanceEvent,
    ManualReviewCase,
    PurchaseIntent,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed
from apps.api.tests.test_any709_step3_postgres import accept, setup_purchase

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
UNKNOWN_REVIEW = "external_create_outcome_unknown:customer"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def retained_evidence(factory: sessionmaker[Session]) -> tuple[object, ...]:
    with factory() as db:
        customer = db.scalar(select(ExternalBillingCustomer))
        operation = db.scalar(
            select(ExternalCreateOperation).where(ExternalCreateOperation.operation_kind == Kind.CUSTOMER)
        )
        reviews = db.scalars(select(ManualReviewCase).order_by(ManualReviewCase.reason_code)).all()
        return (
            customer.customer_id,
            customer.billing_customer_key,
            customer.provider_customer_id,
            customer.binding_state,
            operation.create_operation_id,
            operation.operation_state,
            operation.send_fence,
            operation.bound_external_object_id,
            tuple(
                (review.review_case_id, review.reason_code, review.case_state, review.resolution_document)
                for review in reviews
            ),
        )


def expired_unknown(factory: sessionmaker[Session]) -> None:
    slot = reserve_customer(factory, step1_settings(), TOKEN)
    claim_customer_send(factory, step1_settings(), TOKEN, slot)
    with factory() as db:
        operation = db.scalar(select(ExternalCreateOperation))
        operation.unknown_since = utc_now() - timedelta(hours=3)
        operation.unknown_recovery_deadline_at = operation.unknown_since + timedelta(hours=2)
        db.scalar(select(BillingWorkItem)).lease_expires_at = utc_now() - timedelta(seconds=1)
        db.commit()
    assert escalate_overdue_customers(factory) == 1


@pytest.mark.parametrize("initial", ["key_ambiguity", "email_ambiguity", "point_mismatch", "unknown_then_ambiguity"])
async def test_known_conflict_stays_blocked_across_explicit_openings(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], initial: str
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    slot = reserve_customer(factory, config, TOKEN)
    if initial == "unknown_then_ambiguity":
        expired_unknown(factory)
    first_opening = True
    calls: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert migrated_database.pool.checkedout() == 0
        calls.append((request.method, request.url.path))
        assert request.method == "GET"
        if request.url.path.endswith("/auth"):
            response = {"token": "synthetic-auth", "expires_in": 600}
        elif request.url.path.endswith("/users"):
            body = json.loads(request.content)
            ids = [345]
            if first_opening and initial != "point_mismatch":
                ids = [] if initial == "email_ambiguity" and "outer_id" in body else [345, 346]
            response = [{"user_id": candidate} for candidate in ids]
        else:
            response = {
                "user_id": 345,
                "outer_id": "different-original-key"
                if first_opening and initial == "point_mismatch"
                else slot.outer_key,
            }
        return httpx.Response(200, json={"code": 200, "response": response})

    async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        before = retained_evidence(factory)
        with factory() as db:
            assert db.scalar(select(ExternalBillingCustomer)).binding_state == Binding.IDENTITY_CONFLICT
            reviews = db.scalars(select(ManualReviewCase)).all()
            assert {review.reason_code for review in reviews} == (
                {UNKNOWN_REVIEW, "customer_identity_conflict"}
                if initial == "unknown_then_ambiguity"
                else {"customer_identity_conflict"}
            )
            assert all(review.case_state == "open" for review in reviews)
        first_opening = False  # Provider listing is now single and point proof matches.
        attempted = len(calls)
        for _ in range(2):
            with pytest.raises(BillingRefused, match="billing_identity_conflict"):
                await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        assert len(calls) == attempted
        assert retained_evidence(factory) == before


@pytest.mark.parametrize("reason", ["customer_identity_conflict", "customer_provider_id_already_bound", "other_review"])
@pytest.mark.parametrize("entrypoint", ["reservation", "send", "point_read", "widget_recheck"])
def test_non_unknown_review_blocks_each_customer_boundary(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], reason: str, entrypoint: str
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    slot = reserve_customer(factory, config, TOKEN)
    if entrypoint == "widget_recheck":
        slot = apply_customer_read(factory, slot, provider_id="345", outer_key=slot.outer_key)
    with factory() as db:
        operation = db.scalar(select(ExternalCreateOperation))
        if entrypoint != "widget_recheck":
            operation.operation_state = State.MANUAL_REVIEW
        for review_reason in (UNKNOWN_REVIEW, reason):
            db.add(
                ManualReviewCase(
                    reason_code=review_reason,
                    scope_kind="create_operation",
                    scope_reference=str(slot.operation_id),
                    evidence_schema_version="v1",
                    evidence_document={"create_operation_id": str(slot.operation_id)},
                    case_state="open",
                )
            )
        db.commit()
    before = retained_evidence(factory)
    with pytest.raises(BillingRefused, match="billing_customer_review"):
        if entrypoint == "reservation":
            reserve_customer(factory, config, TOKEN)
        elif entrypoint == "send":
            claim_customer_send(factory, config, TOKEN, slot)
        elif entrypoint == "point_read":
            apply_customer_read(factory, slot, provider_id="345", outer_key=slot.outer_key)
        else:
            recheck_widget_session(factory, config, TOKEN, slot)
    assert retained_evidence(factory) == before


async def test_customer_unknown_review_still_recovers_with_paired_proof(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    expired_unknown(factory)
    slot = reserve_customer(factory, config, TOKEN)

    def respond(request: httpx.Request) -> httpx.Response:
        assert migrated_database.pool.checkedout() == 0
        assert request.method == "GET"
        if request.url.path.endswith("/auth"):
            response = {"token": "synthetic-auth", "expires_in": 600}
        elif request.url.path.endswith("/users"):
            response = [{"user_id": 345}]
        else:
            response = {"user_id": 345, "outer_id": slot.outer_key}
        return httpx.Response(200, json={"code": 200, "response": response})

    async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
        for _ in range(2):
            assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential
    with factory() as db:
        customer = db.scalar(select(ExternalBillingCustomer))
        operation = db.scalar(select(ExternalCreateOperation))
        assert customer.binding_state == Binding.BOUND and customer.provider_customer_id == "345"
        assert operation.operation_state == State.BOUND and operation.create_operation_id == slot.operation_id
        review = db.scalar(select(ManualReviewCase))
        assert review.reason_code == UNKNOWN_REVIEW and review.case_state == "resolved"
        assert review.resolved_by_principal == "system:customer-point-read"
        assert db.scalar(select(BillingWorkItem)).work_state == "done"


@pytest.mark.parametrize("reconciled", [False, True])
def test_closed_review_requires_reconciled_binding_but_preserves_history(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], reconciled: bool
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    slot = reserve_customer(factory, config, TOKEN)
    with factory() as db:
        customer = db.scalar(select(ExternalBillingCustomer))
        customer.binding_state = Binding.UNBOUND if reconciled else Binding.IDENTITY_CONFLICT
        db.scalar(select(ExternalCreateOperation)).operation_state = State.MANUAL_REVIEW
        review = ManualReviewCase(
            reason_code="customer_identity_conflict",
            scope_kind="create_operation",
            scope_reference=str(slot.operation_id),
            evidence_schema_version="v1",
            evidence_document={"create_operation_id": str(slot.operation_id)},
            case_state="resolved",
            resolved_at=utc_now(),
            resolved_by_principal="synthetic:validated-reconciliation",
            resolution_schema_version="v1",
            resolution_document={"proof": "synthetic-reviewed-original-identity"},
        )
        db.add(review)
        db.commit()
        review_id, resolution = review.review_case_id, dict(review.resolution_document)
    if not reconciled:
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            reserve_customer(factory, config, TOKEN)
    else:
        current = reserve_customer(factory, config, TOKEN)
        bound = apply_customer_read(factory, current, provider_id="345", outer_key=current.outer_key)
        recheck_widget_session(factory, config, TOKEN, bound)
    with factory() as db:
        review = db.get(ManualReviewCase, review_id)
        assert review.case_state == "resolved" and review.resolution_document == resolution
        assert review.resolved_by_principal == "synthetic:validated-reconciliation"


@pytest.mark.parametrize("already_bound", [False, True])
async def test_inflight_point_proof_cannot_clear_concurrent_ambiguity(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], already_bound: bool
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    slot = reserve_customer(factory, config, TOKEN)
    if already_bound:
        slot = apply_customer_read(factory, slot, provider_id="345", outer_key=slot.outer_key)
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        assert migrated_database.pool.checkedout() == 0
        assert request.method == "GET" and not request.url.path.endswith("/client/user")
        if request.url.path.endswith("/auth"):
            response = {"token": "synthetic-auth", "expires_in": 600}
        elif request.url.path.endswith("/users"):
            response = [{"user_id": 345}]
        else:
            entered.set()
            await release.wait()
            response = {"user_id": 345, "outer_id": slot.outer_key}
        return httpx.Response(200, json={"code": 200, "response": response})

    async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
        opening = asyncio.create_task(bootstrap_account(sources, config, factory=factory, token=TOKEN))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            with pytest.raises(BillingRefused, match="billing_identity_conflict"):
                await asyncio.to_thread(apply_customer_read, factory, slot, ambiguous=True)
            before = await asyncio.to_thread(retained_evidence, factory)
        finally:
            release.set()
        with pytest.raises(BillingRefused, match="billing_customer_pending"):
            await opening
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        assert await asyncio.to_thread(retained_evidence, factory) == before


@pytest.mark.parametrize("entrypoint", ["confirmation", "advance"])
async def test_customer_conflict_blocks_purchase_without_changing_accepted_evidence(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    transport = setup_purchase(factory)
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory) if entrypoint == "advance" else None
        slot = reserve_customer(factory, config, TOKEN)
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            apply_customer_read(factory, slot, ambiguous=True)
        transport.customer = {"user_id": 345, "outer_id": slot.outer_key}
        before = retained_evidence(factory)
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            if purchase is None:
                await accept(sources, factory)
            else:
                await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert retained_evidence(factory) == before
        assert not any(transport.creates(path) for path in ("/users", "/agreements", "/subscriptions"))
        if purchase is not None:
            current = read_purchase(factory, purchase.user_id, purchase.id)
            assert current.held and current.accepted == purchase.accepted
            assert current.state == purchase.state and current.operations == purchase.operations
    with factory() as db:
        for model in (PurchaseIntent, BillingPurchaseScopeHold, LegalAcceptanceEvent):
            assert db.scalar(select(func.count()).select_from(model)) == (1 if purchase else 0)


@pytest.mark.parametrize("inventory_read", [1, 2], ids=["before-agreement", "before-subscription"])
async def test_conflict_during_inventory_read_prevents_new_financial_send(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    inventory_read: int,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    transport = setup_purchase(factory)
    entered, release = asyncio.Event(), asyncio.Event()
    reads = 0

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal reads
        if request.method == "GET" and request.url.path.endswith("/subscriptions"):
            if "agreement_id" not in json.loads(request.content):
                reads += 1
                if reads == inventory_read:
                    entered.set()
                    await release.wait()
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        preparing = asyncio.create_task(
            advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        )
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            current = await asyncio.to_thread(reserve_customer, factory, config, TOKEN)
            with pytest.raises(BillingRefused, match="billing_identity_conflict"):
                await asyncio.to_thread(apply_customer_read, factory, current, ambiguous=True)
        finally:
            release.set()
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            await preparing
    assert transport.creates("/users") == 1
    assert transport.creates("/agreements") == inventory_read - 1
    assert transport.creates("/subscriptions") == 0
    current_purchase = read_purchase(factory, purchase.user_id, purchase.id)
    assert current_purchase.held and current_purchase.accepted == purchase.accepted
    pending_kind = Kind.AGREEMENT if inventory_read == 1 else Kind.SUBSCRIPTION
    pending = next(operation for operation in current_purchase.operations if operation.kind == pending_kind)
    assert pending == next(operation for operation in purchase.operations if operation.kind == pending_kind)
