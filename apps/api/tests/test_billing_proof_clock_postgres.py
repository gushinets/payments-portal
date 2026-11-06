"""DB-clock source intervals with skewed API clocks and real fenced DB writers."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.composition.billing_operator import resolve_review
from app.composition.purchase_recovery import recover_one
from app.composition.purchases import recover_financial
from app.composition.reconciliation import reconcile_subscription
from app.domains.billing.contracts import BillingRefused
from app.domains.billing import work
from app.domains.billing.work_contracts import WorkLane
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.operator_review import prepare_resolution
from app.domains.billing.reconciliation import apply_reconciliation, read_source_time
from app.domains.purchases import financial, service
from app.integrations.lbx import reconciliation as lbx_reconciliation
from app.models import BillingWorkItem, ExternalCreateOperation, ExternalSubscription, ManualReviewCase
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    synthetic_prepare,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
PRINCIPAL = "os-euid:1000"


@pytest.mark.parametrize("skew", [-1, 0, 1])
@pytest.mark.parametrize("path", ["canonical", "original", "restore-original", "bind-original"])
async def test_database_clock_brackets_every_persisted_proof(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    skew: int,
    path: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    transport.pool = factory.kw["bind"].pool

    def clock() -> datetime:
        return datetime.now(UTC) + timedelta(seconds=skew)

    monkeypatch.setattr(financial, "utc_now", clock)
    monkeypatch.setattr(lbx_reconciliation, "utc_now", clock)
    before_claim = read_source_time(factory)
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=path in {"original", "bind-original"})
    after_claim = read_source_time(factory)
    with factory() as db:
        operation = next(op for op in purchase.operations if op.kind == "subscription")
        stored = db.get(ExternalCreateOperation, operation.id)
        assert before_claim <= stored.unknown_since <= after_claim
    transport.subscriptions[0].update(
        state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-11-01"
    )
    request = None
    if path == "restore-original":
        transport.subscriptions[0]["services"][0]["price"] = 150
        with factory() as db:
            identity = db.scalar(select(ExternalSubscription.subscription_id))
        await reconcile_subscription(
            sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=identity
        )
        transport.subscriptions[0]["services"][0]["price"] = 100
    elif path == "bind-original":
        financial.financial_pending(factory, purchase, operation, conflict=True)
    if path in {"restore-original", "bind-original"}:
        request = resolution_request(
            purchase, inspect_evidence(factory, config, purchase.user_id, purchase.id), bind=path == "bind-original"
        )
    start = read_source_time(factory)
    if request is not None:
        result = await resolve_review(sources, config, factory=factory, request=request, principal=PRINCIPAL)
        assert result["outcome"] == "resolved"
    elif path == "original":
        await recover_financial(sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id)
    else:
        with factory() as db:
            identity = db.scalar(select(ExternalSubscription.subscription_id))
        await reconcile_subscription(
            sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=identity
        )
    finish = read_source_time(factory)
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        assert start <= sub.last_authoritative_read_at <= finish
        if path in {"original", "bind-original"}:
            assert sub.projection_valid_until == sub.last_authoritative_read_at
        else:
            assert sub.projection_valid_until - sub.last_authoritative_read_at == timedelta(hours=6)
        if request is not None:
            case = db.get(ManualReviewCase, request.case_id)
            assert case.case_state == "resolved" and case.resolved_by_principal == PRINCIPAL
            assert case.resolution_document["observation_id"] == str(sub.latest_observation_id)
            proof = case.resolution_document["proof"]
            assert (
                start
                <= datetime.fromisoformat(proof["read_started_at"])
                <= datetime.fromisoformat(proof["read_finished_at"])
                <= finish
            )
    assert not any(req.method == "POST" for req in transport.requests)


@pytest.mark.parametrize("invalid", ["owner", "fence", "expired-lease", "previous-proof"])
async def test_canonical_clock_fix_keeps_stale_proof_guards(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    invalid: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    with factory() as db:
        identity = db.scalar(select(ExternalSubscription.subscription_id))
        before = db.get(ExternalSubscription, identity).latest_observation_id

    async def invalidate(function: Any, *args: Any, **kwargs: Any) -> Any:
        if function is apply_reconciliation:
            _, subject, proof = args
            if invalid == "previous-proof":
                proof = replace(proof, read_started_at=subject.claimed_at - timedelta(seconds=1))
                args = (factory, subject, proof)
            else:
                with factory() as db:
                    sub = db.get(ExternalSubscription, identity)
                    if invalid == "owner":
                        sub.reconciliation_lease_owner = "another-owner"
                    elif invalid == "fence":
                        sub.reconciliation_fencing_token += 1
                    else:
                        sub.reconciliation_lease_expires_at = read_source_time(factory) - timedelta(seconds=1)
                    db.commit()
        return await run_in_threadpool(function, *args, **kwargs)

    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        await reconcile_subscription(
            sources.require_lbx(),
            sources.billing,
            config,
            factory=factory,
            subscription_id=identity,
            delegate=invalidate,
        )
    with factory() as db:
        assert db.get(ExternalSubscription, identity).latest_observation_id == before


@pytest.mark.parametrize(
    "operator,invalid",
    [
        (False, "fence"),
        (False, "previous-proof"),
        (False, "expired-lease"),
        (True, "fence"),
        (True, "previous-proof"),
        (True, "expired-resolution"),
        (True, "previous-resolution-proof"),
    ],
)
async def test_original_clock_fix_keeps_binding_and_operator_guards(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    operator: bool,
    invalid: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == "subscription")
    resolution = None
    request = None
    if operator:
        financial.financial_pending(factory, purchase, operation, conflict=True)
        request = resolution_request(
            purchase, inspect_evidence(factory, config, purchase.user_id, purchase.id), bind=True
        )
        resolution = prepare_resolution(factory, config, request, PRINCIPAL, io_timeout_seconds=60)
        purchase = resolution.purchase
        operation = next(op for op in purchase.operations if op.kind == "subscription")
    customer = service.customer_for_purchase(factory, config, purchase)
    claim = work.claim_work(factory, config, WorkLane.URGENT) if invalid == "expired-lease" else None
    if claim is not None:
        assert claim.reference == str(operation.id)

    async def invalidate(function: Any, *args: Any, **kwargs: Any) -> Any:
        if function is financial.bind_financial:
            if invalid == "fence":
                with factory() as db:
                    db.get(ExternalCreateOperation, operation.id).send_fence = uuid4()
                    db.commit()
            elif invalid == "expired-lease":
                with factory() as db:
                    db.get(BillingWorkItem, claim.id).lease_expires_at = read_source_time(factory) - timedelta(
                        seconds=1
                    )
                    db.commit()
            elif invalid == "previous-resolution-proof":
                with factory() as db:
                    since = db.get(ExternalCreateOperation, operation.id).unknown_since
                started = since + (resolution.started_at - since) / 2
                kwargs["proof"] = replace(kwargs["proof"], read_started_at=started)
            elif invalid == "previous-proof":
                with factory() as db:
                    since = db.get(ExternalCreateOperation, operation.id).unknown_since
                kwargs["proof"] = replace(kwargs["proof"], read_started_at=since - timedelta(seconds=1))
            else:
                kwargs["resolution"] = replace(
                    kwargs["resolution"], expires_at=read_source_time(factory) - timedelta(seconds=1)
                )
        return await run_in_threadpool(function, *args, **kwargs)

    with pytest.raises(BillingRefused):
        async with sources.billing.operation(bound_scope=False) as budget:
            await recover_one(
                sources,
                config,
                purchase,
                operation,
                customer,
                factory,
                budget=budget,
                delegate=invalidate,
                resolution=resolution,
                work_claim=claim,
            )
    with factory() as db:
        assert db.get(ExternalCreateOperation, operation.id).bound_external_object_id is None
        assert db.scalar(select(ExternalSubscription)) is None
        if request is not None:
            case = db.get(ManualReviewCase, request.case_id)
            assert case.case_state == "open" and case.resolution_document is None
    assert not any(req.method == "POST" for req in transport.requests)
