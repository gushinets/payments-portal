"""Recover the original proven customer without clearing unrelated conflicts."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.purchases import advance_purchase
from app.composition.sources import source_resources
from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.customers import (
    apply_customer_read,
    claim_customer_send,
    recheck_widget_session,
    reserve_customer,
)
from app.domains.purchases.service import read_purchase
from app.models import (
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ManualReviewCase,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed
from apps.api.tests.test_any709_step3_postgres import accept, setup_purchase
from apps.api.tests.test_billing_customer_conflicts_postgres import retained_evidence

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
KEY_REVIEW = "customer_original_key_mismatch"


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def record_key_mismatch(factory: sessionmaker[Session], slot: CustomerOpen) -> None:
    with pytest.raises(BillingRefused, match="billing_identity_conflict"):
        apply_customer_read(factory, slot, provider_id="345", outer_key="synthetic-wrong-key")


async def test_original_proven_customer_recovers_after_provider_restores_key(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    original = reserve_customer(factory, config, TOKEN)
    current_key = original.outer_key
    calls: list[tuple[str, str]] = []

    def respond(request: httpx.Request) -> httpx.Response:
        assert migrated_database.pool.checkedout() == 0
        calls.append((request.method, request.url.path))
        assert request.method == "GET"
        path = request.url.path.removeprefix("/api/rest/v1")
        if path == "/auth":
            response = {"token": "synthetic-auth", "expires_in": 600}
        elif path == "/users":
            response = [{"user_id": 345}]
        else:
            assert path in {"/users/345", "/client/user"}
            response = {"user_id": 345, "outer_id": current_key}
        return httpx.Response(200, json={"code": 200, "response": response})

    async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
        assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential
        first_end = len(calls)
        current_key = "synthetic-wrong-key"
        for _ in range(2):
            with pytest.raises(BillingRefused, match="billing_identity_conflict"):
                await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        with factory() as db:
            review = db.scalar(select(ManualReviewCase))
            assert review.reason_code == KEY_REVIEW and review.case_state == "open"
            review_id = review.review_case_id
            assert len(db.scalars(select(ManualReviewCase)).all()) == 1
        current_key = original.outer_key
        for _ in range(2):
            assert (await bootstrap_account(sources, config, factory=factory, token=TOKEN)).credential
    assert all(path.endswith(("/users/345", "/client/user")) for _, path in calls[first_end:])
    with factory() as db:
        customer = db.scalar(select(ExternalBillingCustomer))
        operation = db.scalar(select(ExternalCreateOperation))
        review = db.get(ManualReviewCase, review_id)
        assert customer.customer_id == original.customer_id and customer.billing_customer_key == original.outer_key
        assert customer.provider_customer_id == "345" and customer.binding_state == Binding.BOUND
        assert operation.create_operation_id == original.operation_id and operation.operation_state == State.BOUND
        assert operation.bound_external_object_id == "345" and operation.request_correlation_key == original.outer_key
        assert review.case_state == "resolved" and review.resolved_by_principal == "system:customer-point-read"
        assert review.resolution_document["proof"] == "original_customer_point_read"


@pytest.mark.parametrize("later_cause", ["ambiguity", "different_id", "other_review"])
def test_key_recovery_never_clears_an_additional_blocking_cause(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], later_cause: str
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    original = reserve_customer(factory, config, TOKEN)
    bound = apply_customer_read(factory, original, provider_id="345", outer_key=original.outer_key)
    record_key_mismatch(factory, bound)
    recovering = reserve_customer(factory, config, TOKEN)
    if later_cause == "other_review":
        with factory() as db:
            db.add(
                ManualReviewCase(
                    reason_code="other_review",
                    scope_kind="create_operation",
                    scope_reference=str(original.operation_id),
                    evidence_schema_version="v1",
                    evidence_document={},
                    case_state="open",
                )
            )
            db.commit()
    else:
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            apply_customer_read(
                factory,
                recovering,
                provider_id="346" if later_cause == "different_id" else None,
                outer_key=original.outer_key,
                ambiguous=later_cause != "different_id",
            )
    before = retained_evidence(factory)
    with pytest.raises(BillingRefused, match="billing_identity_conflict"):
        reserve_customer(factory, config, TOKEN)
    with pytest.raises(BillingRefused):
        apply_customer_read(factory, recovering, provider_id="345", outer_key=original.outer_key)
    assert retained_evidence(factory) == before
    with factory() as db:
        reviews = db.scalars(select(ManualReviewCase)).all()
        assert {review.reason_code for review in reviews} == {
            KEY_REVIEW,
            "other_review" if later_cause == "other_review" else "customer_identity_conflict",
        }
        assert all(review.case_state == "open" for review in reviews)


@pytest.mark.parametrize("corruption", ["schema", "operation_id", "provider_id", "bound_id", "legacy_reason"])
def test_read_recovery_requires_retained_proof_of_the_same_original_customer(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], corruption: str
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    slot = reserve_customer(factory, config, TOKEN)
    bound = apply_customer_read(factory, slot, provider_id="345", outer_key=slot.outer_key)
    record_key_mismatch(factory, bound)
    with factory() as db:
        review = db.scalar(select(ManualReviewCase))
        if corruption == "schema":
            review.evidence_schema_version = "v1"
        elif corruption == "operation_id":
            review.evidence_document = {**review.evidence_document, "create_operation_id": "wrong"}
        elif corruption == "provider_id":
            review.evidence_document = {**review.evidence_document, "provider_customer_id": "346"}
        elif corruption == "bound_id":
            db.scalar(select(ExternalCreateOperation)).bound_external_object_id = "346"
        else:
            review.reason_code = "customer_identity_conflict"
        db.commit()
    before = retained_evidence(factory)
    with pytest.raises(BillingRefused, match="billing_identity_conflict"):
        reserve_customer(factory, config, TOKEN)
    assert retained_evidence(factory) == before


def test_recoverable_key_conflict_still_blocks_send_and_widget_recheck(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    slot = reserve_customer(factory, config, TOKEN)
    bound = apply_customer_read(factory, slot, provider_id="345", outer_key=slot.outer_key)
    record_key_mismatch(factory, bound)
    recovering = reserve_customer(factory, config, TOKEN)
    before = retained_evidence(factory)
    with pytest.raises(BillingRefused, match="billing_identity_conflict"):
        claim_customer_send(factory, config, TOKEN, recovering)
    with pytest.raises(BillingRefused):
        recheck_widget_session(factory, config, TOKEN, recovering)
    assert retained_evidence(factory) == before


async def test_inflight_key_recovery_cannot_clear_new_ambiguity(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    slot = reserve_customer(factory, config, TOKEN)
    bound = apply_customer_read(factory, slot, provider_id="345", outer_key=slot.outer_key)
    record_key_mismatch(factory, bound)
    recovering = reserve_customer(factory, config, TOKEN)
    entered, release = asyncio.Event(), asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        assert migrated_database.pool.checkedout() == 0 and request.method == "GET"
        if request.url.path.endswith("/auth"):
            response = {"token": "synthetic-auth", "expires_in": 600}
        else:
            assert request.url.path.endswith("/users/345")
            entered.set()
            await release.wait()
            response = {"user_id": 345, "outer_id": slot.outer_key}
        return httpx.Response(200, json={"code": 200, "response": response})

    async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
        opening = asyncio.create_task(bootstrap_account(sources, config, factory=factory, token=TOKEN))
        try:
            await asyncio.wait_for(entered.wait(), timeout=5)
            with pytest.raises(BillingRefused, match="billing_identity_conflict"):
                await asyncio.to_thread(apply_customer_read, factory, recovering, ambiguous=True)
            before = await asyncio.to_thread(retained_evidence, factory)
        finally:
            release.set()
        with pytest.raises(BillingRefused, match="billing_customer_pending"):
            await opening
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN)
    assert retained_evidence(factory) == before


async def test_client_scope_conflict_after_key_recovery_remains_blocking(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    seed(factory)
    slot = reserve_customer(factory, config, TOKEN)
    bound = apply_customer_read(factory, slot, provider_id="345", outer_key=slot.outer_key)
    record_key_mismatch(factory, bound)

    def respond(request: httpx.Request) -> httpx.Response:
        assert migrated_database.pool.checkedout() == 0 and request.method == "GET"
        if request.url.path.endswith("/auth"):
            response = {"token": "synthetic-auth", "expires_in": 600}
        else:
            assert request.url.path.endswith(("/users/345", "/client/user"))
            response = {
                "user_id": 346 if request.url.path.endswith("/client/user") else 345,
                "outer_id": slot.outer_key,
            }
        return httpx.Response(200, json={"code": 200, "response": response})

    async with source_resources(config, lbx_transport=httpx.MockTransport(respond)) as sources:
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        before = retained_evidence(factory)
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            await bootstrap_account(sources, config, factory=factory, token=TOKEN)
    assert retained_evidence(factory) == before
    with factory() as db:
        reviews = {review.reason_code: review for review in db.scalars(select(ManualReviewCase))}
        assert reviews[KEY_REVIEW].case_state == "resolved"
        assert reviews["customer_identity_conflict"].case_state == "open"


@pytest.mark.parametrize("inventory_read", [1, 2], ids=["before-agreement", "before-subscription"])
async def test_key_conflict_blocks_financial_claim_then_original_pair_recovers(
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
            await asyncio.to_thread(record_key_mismatch, factory, current)
        finally:
            release.set()
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            await preparing
        assert transport.creates("/agreements") == inventory_read - 1
        assert transport.creates("/subscriptions") == 0
        pending = read_purchase(factory, purchase.user_id, purchase.id)
        kind = Kind.AGREEMENT if inventory_read == 1 else Kind.SUBSCRIPTION
        assert next(op for op in pending.operations if op.kind == kind) == next(
            op for op in purchase.operations if op.kind == kind
        )
        # Provider retains the original pair. A new explicit Continue must read
        # that same ID and complete without replacing accepted evidence/hold.
        result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.state.value == "linked" and result.held and result.accepted == purchase.accepted
        assert [transport.creates(path) for path in ("/users", "/agreements", "/subscriptions")] == [1, 1, 1]
