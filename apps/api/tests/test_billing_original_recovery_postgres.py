"""Stage 3 original-operation recovery with PostgreSQL and SIMULATED LBX."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.purchases import advance_purchase, recover_financial
from app.composition.sources import source_resources
from app.domains.billing.contracts import BillingRefused
from app.models import (
    BillingStateObservation,
    ExternalCreateOperation,
    ExternalSubscription,
    ManualReviewCase,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import background_scenario as background_scenario
from apps.api.tests.test_any709_step3_postgres import TOKEN, accept, setup_purchase

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("negative", ["ended", "closed_subscription", "closed_agreement"])
async def test_original_terminal_recovery_binds_history_without_another_financial_post(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    negative: str,
) -> None:
    factory, configuration = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    path = "/agreements" if negative == "closed_agreement" else "/subscriptions"
    transport.fail_create = path
    transport.hide.add(path)
    async with source_resources(
        configuration,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        uncertain = await advance_purchase(
            sources, configuration, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        operation = next(
            op
            for op in uncertain.operations
            if op.kind == ("agreement" if negative == "closed_agreement" else "subscription")
        )
        assert operation.state == "unknown"
        with factory() as db:
            row = db.get(ExternalCreateOperation, operation.id)
            history = (row.unknown_since, row.unknown_recovery_deadline_at, copy.deepcopy(row.recovery_hint_document))
        transport.hide.clear()
        if negative == "ended":
            transport.subscriptions[0].update(state=3, current_blocking=3)
        else:
            transport.agreements[0]["close_date"] = "2026-11-05"
        creates = (transport.creates("/agreements"), transport.creates("/subscriptions"))
        recovered = await recover_financial(
            sources, configuration, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
        bound = next(op for op in recovered.operations if op.id == operation.id)
        assert bound.state == "bound" and bound.bound_id is not None
        assert (bound.id, bound.key) == (operation.id, operation.key) and bound.fence != operation.fence
        assert recovered.held and recovered.accepted == purchase.accepted
        if negative == "closed_agreement":
            assert bound.agreement_closed
            transport.agreements[0]["close_date"] = None
            await advance_purchase(sources, configuration, factory=factory, token=TOKEN, purchase_id=purchase.id)
            assert not transport.subscriptions
        else:
            with factory() as db:
                sub = db.scalar(select(ExternalSubscription))
                assert (sub.lifecycle_status, sub.financial_access_status) == ("ended", "blocked")
                assert sub.projection_valid_until - sub.last_authoritative_read_at == timedelta(0)
                evidence = db.get(BillingStateObservation, sub.latest_observation_id)
                assert evidence.result_classification == "source_negative"
            with pytest.raises(BillingRefused, match="purchase_not_prepared"):
                await bootstrap_account(sources, configuration, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert (transport.creates("/agreements"), transport.creates("/subscriptions")) == creates
        with factory() as db:
            row = db.get(ExternalCreateOperation, operation.id)
            assert (row.unknown_since, row.unknown_recovery_deadline_at, row.recovery_hint_document) == history
            assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0


@pytest.mark.parametrize("terminal", [False, True])
async def test_operator_collects_original_point_evidence_once_and_keeps_zero_positive_trust(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], terminal: bool
) -> None:
    from collections import Counter
    from app.composition.billing_operator import resolve_review
    from app.domains.billing.operator_diagnostics import inspect_evidence
    from app.domains.purchases import financial
    from apps.api.tests.factories.billing_operator import resolution_request
    from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == "subscription")
    financial.financial_pending(factory, purchase, operation, conflict=True)
    if terminal:
        transport.subscriptions[0].update(state=3, current_blocking=1)
    else:
        transport.subscriptions[0].update(
            state=-2, current_blocking=0, last_tariffication_period_start=None, last_tariffication_period_end=None
        )
    request = resolution_request(
        purchase, inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id), bind=True
    )
    before = len(transport.requests)
    await resolve_review(sources, step1_settings(), factory=factory, request=request, principal="os-euid:1000")
    counts = Counter(req.url.path for req in transport.requests[before:])
    for path in ("/users/345", "/agreements/456", "/subscriptions/567", "/tariffs/701"):
        assert counts["/api/rest/v1" + path] == 1
    assert all(req.method == "GET" for req in transport.requests[before:])
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        assert (sub.lifecycle_status, sub.financial_access_status) == ("ended" if terminal else "inactive", "blocked")
        assert sub.projection_valid_until == sub.last_authoritative_read_at
        case = db.get(ManualReviewCase, request.case_id)
        assert case.case_state == "resolved" and case.resolved_by_principal == "os-euid:1000"
        assert case.resolution_document["proof"]["subscription"]["lifecycle"] == sub.lifecycle_status
        assert case.resolution_document["observation_id"] == str(sub.latest_observation_id)


async def test_concurrent_first_bind_discards_candidate_and_uses_claimed_known_subscription_path(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    from typing import Any
    from starlette.concurrency import run_in_threadpool
    from app.composition.reconciliation import reconcile_subscription
    from app.domains.purchases import financial
    from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    raced = False

    async def interleaved(function: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal raced
        if function is financial.bind_financial and not raced:
            raced = True
            assert await run_in_threadpool(function, *args, **kwargs)
            transport.subscriptions[0].update(state=3, current_blocking=3)
            with factory() as db:
                identity = db.scalar(select(ExternalSubscription.subscription_id))
            await reconcile_subscription(
                sources.require_lbx(), sources.billing, step1_settings(), factory=factory, subscription_id=identity
            )
        return await run_in_threadpool(function, *args, **kwargs)

    before = len(transport.requests)
    result = await recover_financial(
        sources,
        step1_settings(),
        factory=factory,
        user_id=purchase.user_id,
        purchase_id=purchase.id,
        delegate=interleaved,
    )
    assert raced and result.state == "linked" and result.held and result.accepted == purchase.accepted
    assert all(req.method == "GET" for req in transport.requests[before:])
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
        assert (sub.lifecycle_status, sub.financial_access_status) == ("ended", "blocked")
        assert sub.reconciliation_fencing_token == 2
        assert (
            db.get(BillingStateObservation, sub.latest_observation_id).evidence_schema_version
            == "subscription-reconciliation:v2"
        )
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillingStateObservation)
                .where(BillingStateObservation.evidence_schema_version == "prepared-subscription:v1")
            )
            == 1
        )
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0


async def test_automatic_recovery_requires_the_saved_original_command(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from typing import Any
    from app.domains.purchases import financial
    from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    claim = financial.claim_financial

    def legacy_command(*args: Any, **kwargs: Any) -> Any:
        values = list(args)
        if values[2].kind == "subscription":
            values[3] = {"agreement_id": 456}
        return claim(*values, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(financial, "claim_financial", legacy_command)
        purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == "subscription")
    before = len(transport.requests)
    with pytest.raises(BillingRefused, match="purchase_history_unproven"):
        await recover_financial(
            sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
    assert len(transport.requests) == before
    with factory() as db:
        assert db.get(ExternalCreateOperation, operation.id).bound_external_object_id is None
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 0


async def test_negative_first_bind_and_observation_roll_back_together(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == "subscription")
    transport.subscriptions[0].update(state=3, current_blocking=0)

    def fail(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated first-bind enrollment failure")

    with monkeypatch.context() as scoped:
        scoped.setattr("app.domains.purchases.preparation.enroll_subscription", fail)
        with pytest.raises(RuntimeError, match="enrollment failure"):
            await recover_financial(
                sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
            )
    with factory() as db:
        saved = db.get(ExternalCreateOperation, operation.id)
        assert saved.bound_external_object_id is None and saved.send_fence == operation.fence
        assert db.scalar(select(func.count()).select_from(ExternalSubscription)) == 0
        assert db.scalar(select(func.count()).select_from(BillingStateObservation)) == 0
    recovered = await recover_financial(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    assert next(op for op in recovered.operations if op.id == operation.id).state == "bound"
    assert not any(req.method == "POST" for req in transport.requests)


async def test_reviewed_bound_financial_operation_is_completed_recovery_without_source_reads(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    from app.domains.purchases import financial, service
    from app.domains.billing import background_recovery, work
    from app.domains.billing.work_contracts import WorkLane
    from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    operation = next(op for op in purchase.operations if op.kind == "subscription")
    financial.financial_pending(factory, purchase, operation, conflict=True)
    current = service.read_purchase(factory, purchase.user_id, purchase.id)
    before = len(transport.requests)
    result = await recover_financial(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    assert result == current and len(transport.requests) == before
    from app.models import BillingWorkItem

    with factory() as db:
        leftover = db.scalar(select(BillingWorkItem).where(BillingWorkItem.coalescing_key == str(operation.id)))
        leftover.work_state = "pending"
        leftover.priority = 1
        leftover.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        reconciliation = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.RECONCILIATION))
        reconciliation.next_attempt_at = datetime.now(UTC) + timedelta(hours=1)
        db.commit()
    claim = work.claim_work(factory, step1_settings(), WorkLane.URGENT)
    assert claim is not None and claim.reference == str(operation.id)
    background_recovery.finish_recovery(factory, claim)
    background_recovery.repair_batch(factory, step1_settings())
    with factory() as db:
        assert db.get(BillingWorkItem, claim.id).work_state == "completed"
        assert db.scalar(select(func.count()).select_from(BillingStateObservation)) == 1
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 1
