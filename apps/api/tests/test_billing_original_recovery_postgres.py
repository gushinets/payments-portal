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
from app.domains.billing import terminal_resolution as completion
from app.domains.billing.contracts import BillingRefused
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseRefused
from app.models import (
    BillingStateObservation,
    ExternalCreateOperation,
    ExternalSubscription,
    ManualReviewCase,
)
from apps.api.tests.factories.billing_operator import terminal_request
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
            assert recovered.state == uncertain.state
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
    config = step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = next(op for op in purchase.operations if op.kind == "subscription")
    financial.financial_pending(factory, purchase, operation, conflict=True)
    if terminal:
        transport.subscriptions[0].update(state=3, current_blocking=1)
    else:
        transport.subscriptions[0].update(
            state=-2, current_blocking=0, last_tariffication_period_start=None, last_tariffication_period_end=None
        )
    agreement, subscription = purchase.operations
    proofs = (
        completion.OperationEvidence(
            operation_id=agreement.id,
            outcome=completion.TerminalEvidenceKind.EXTERNAL_TERMINAL,
            external_object_id=agreement.bound_id,
        ),
        completion.OperationEvidence(
            operation_id=subscription.id,
            outcome=completion.TerminalEvidenceKind.EXTERNAL_TERMINAL,
            external_object_id="567",
        ),
    )
    early = terminal_request(factory, config, purchase, *proofs, confirmed=True)
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
    if not terminal:
        refreshed = terminal_request(factory, config, purchase, *proofs, confirmed=True)
        observation = inspect_evidence(factory, config, purchase.user_id, purchase.id)
        retained = next(op["original_point_facts"] for op in observation["operations"] if op["kind"] == "subscription")
        point_at = datetime.fromisoformat(retained["primary"]["point_read_finished_at"])
        assert early.evidence.confirmed_at < point_at <= refreshed.evidence.confirmed_at
        old_confirmation = refreshed.model_copy(update={"evidence": early.evidence})
        with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
            completion.resolve_purchase(factory, config, old_confirmation, "os-euid:1000")
        assert service.read_purchase(factory, purchase.user_id, purchase.id).held
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


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


@pytest.mark.parametrize(
    ("kind", "conflict"),
    [("agreement", False), ("subscription", False), ("subscription", True)],
    ids=["agreement", "subscription", "conflicting-subscriptions"],
)
async def test_unbound_original_point_fences_terminal_resolution(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    conflict: bool,
) -> None:
    from app.composition import purchase_recovery
    from app.domains.billing.reconciliation import read_source_time
    from app.infrastructure.queries.billing_customers import recovery_work
    from app.integrations.lbx.errors import LbxTimeout
    from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    if kind == "agreement":
        transport.fail_create = "/agreements"
        transport.hide.add("/agreements")
        purchase = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        transport.hide.clear()
        transport.agreements[0]["close_date"] = None

        def refuse_binding(*args: object, **kwargs: object) -> bool:
            raise PurchaseRefused("purchase_history_unproven", 409)

        monkeypatch.setattr(purchase_recovery.financial, "bind_financial", refuse_binding)
    else:
        purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)

        async def fail_tariff(**kwargs: object) -> None:
            raise LbxTimeout()

        monkeypatch.setattr(sources.require_lbx(), "get_tariff", fail_tariff)

    agreement, subscription = purchase.operations
    operation = agreement if kind == "agreement" else subscription
    provider_id = "456" if kind == "agreement" else "567"
    assert operation.bound_id is None and operation.candidate_id is None
    early = read_source_time(factory)
    if kind == "agreement":
        with pytest.raises(PurchaseRefused, match="purchase_history_unproven"):
            await recover_financial(
                sources,
                config,
                factory=factory,
                user_id=purchase.user_id,
                purchase_id=purchase.id,
                operation_id=operation.id,
            )
    else:
        await recover_financial(
            sources,
            config,
            factory=factory,
            user_id=purchase.user_id,
            purchase_id=purchase.id,
            operation_id=operation.id,
        )
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.held and next(op for op in saved.operations if op.id == operation.id).bound_id is None

    kind_of = completion.TerminalEvidenceKind
    other = completion.OperationEvidence(
        operation_id=(subscription if kind == "agreement" else agreement).id,
        outcome=kind_of.NOT_SENT if kind == "agreement" else kind_of.EXTERNAL_TERMINAL,
        external_object_id=None if kind == "agreement" else "456",
    )

    def request(external_id: str) -> completion.TerminalRequest:
        evidence = completion.OperationEvidence(
            operation_id=operation.id, outcome=kind_of.EXTERNAL_TERMINAL, external_object_id=external_id
        )
        return terminal_request(factory, config, saved, evidence, other, confirmed=True)

    with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
        completion.resolve_purchase(factory, config, request("999"), "os-euid:1000")
    with factory() as db:
        data = recovery_work(db, operation.id).payload_document["original_point_facts"]
        point = data["primary"]
        assert point["operation_id"] == str(operation.id)
        assert point["operation_kind"] == kind and point["external_object_id"] == provider_id
        assert early <= datetime.fromisoformat(point["point_read_finished_at"]) <= read_source_time(factory)

    exact = request(provider_id)
    stale = exact.model_copy(
        update={"evidence": exact.evidence.model_copy(update={"senders_stopped_at": early, "confirmed_at": early})}
    )
    with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
        completion.resolve_purchase(factory, config, stale, "os-euid:1000")
    assert service.read_purchase(factory, purchase.user_id, purchase.id) == saved

    if conflict:
        transport.subscriptions[0]["subscription_id"] = 568
        saved = await recover_financial(
            sources,
            config,
            factory=factory,
            user_id=purchase.user_id,
            purchase_id=purchase.id,
            operation_id=operation.id,
        )
        with factory() as db:
            data = recovery_work(db, operation.id).payload_document["original_point_facts"]
            first, second = data["primary"], data["conflict"]
            assert first["external_object_id"] == "567"
            assert second["external_object_id"] == "568" and second["operation_id"] == first["operation_id"]
            assert datetime.fromisoformat(second["point_read_finished_at"]) > datetime.fromisoformat(
                first["point_read_finished_at"]
            )
        for external_id in ("567", "568"):
            with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
                completion.resolve_purchase(factory, config, request(external_id), "os-euid:1000")
        assert saved.held and service.read_purchase(factory, purchase.user_id, purchase.id) == saved
        return

    transport.agreements[0]["close_date"] = "2026-11-05"
    if kind == "subscription":
        transport.subscriptions[0]["state"] = 3
    assert completion.resolve_purchase(factory, config, request(provider_id), "os-euid:1000").state.resolved


@pytest.mark.parametrize("expired", [False, True], ids=["owned-claim", "expired-claim"])
async def test_inventory_retains_original_subscription_point_before_tariff_failure(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    expired: bool,
) -> None:
    from app.composition.purchase_inventory import collect_inventory
    from app.domains.billing import background_recovery as recovery, work
    from app.domains.billing.reconciliation import read_source_time
    from app.domains.billing.work_contracts import WorkLane
    from app.domains.purchases.recovery_evidence import RetainedOriginalPointFacts, retained_points
    from app.infrastructure.preflight import PreflightBudget
    from app.integrations.lbx.errors import LbxTimeout
    from app.integrations.lbx.financial import Subscription
    from app.models import BillingWorkItem, ExternalCreateOperationKind as Kind
    from apps.api.tests.factories.billing_operator import terminal_object_request
    from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    operation = purchase.operations[1]
    assert operation.bound_id is None and operation.candidate_id is None
    stale = terminal_object_request(factory, config, purchase, subscription_id="567")
    transport.subscriptions[0].update(state=2, current_blocking=0)
    recovery.repair_batch(factory, config)
    claim = work.claim_work(factory, config, WorkLane.NORMAL)
    assert claim is not None and claim.kind == recovery.INVENTORY
    customer = service.customer_for_purchase(factory, config, purchase)
    client = sources.require_lbx()
    get_subscription = client.get_subscription
    points_read: list[datetime] = []
    tariff_reads: list[tuple[datetime, RetainedOriginalPointFacts | None]] = []

    async def read_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        assert subscription_id == 567
        point = await get_subscription(subscription_id=subscription_id, budget=budget)
        points_read.append(read_source_time(factory))
        if expired:
            with factory.begin() as db:
                db.get(BillingWorkItem, claim.id).lease_expires_at = points_read[-1] - timedelta(seconds=1)
        return point

    async def fail_tariff(*, tariff_id: int, budget: PreflightBudget) -> None:
        tariff_started = read_source_time(factory)
        with factory() as db:
            tariff_reads.append((tariff_started, retained_points(db, db.get(ExternalCreateOperation, operation.id))))
        raise LbxTimeout()

    with monkeypatch.context() as fault:
        fault.setattr(client, "get_subscription", read_point)
        fault.setattr(client, "get_tariff", fail_tariff)
        async with sources.billing.operation(bound_scope=False) as budget:
            result = await collect_inventory(
                client, sources.billing, config, factory=factory, customer=customer, budget=budget, work_claim=claim
            )
    [point_read] = points_read
    assert not result.complete
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.held and saved.operations[1].bound_id is None
    with factory.begin() as db:
        facts = retained_points(db, db.get(ExternalCreateOperation, operation.id))
        if not expired:
            work.finish(db, work.verify_claim(db, claim), claim, due=None)
    if expired:
        assert facts is None
        return

    [(tariff_started, facts_at_tariff)] = tariff_reads
    assert facts is not None and facts.conflict is None
    assert facts_at_tariff == facts
    fact = facts.primary
    assert (fact.operation_id, fact.operation_kind, fact.external_object_id, fact.fact) == (
        operation.id,
        Kind.SUBSCRIPTION,
        "567",
        "live",
    )
    assert stale.evidence.confirmed_at < point_read <= fact.point_read_finished_at <= tariff_started
    current = terminal_object_request(factory, config, saved, subscription_id="567")
    assert current.expected_digest != stale.expected_digest
    with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
        completion.resolve_purchase(
            factory, config, current.model_copy(update={"evidence": stale.evidence}), "os-euid:1000"
        )
    assert service.read_purchase(factory, purchase.user_id, purchase.id) == saved
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    transport.agreements[0]["close_date"], transport.subscriptions[0]["state"] = "2026-10-27", 3
    fresh = terminal_object_request(factory, config, saved, subscription_id="567")
    assert completion.resolve_purchase(factory, config, fresh, "os-euid:1000").state.resolved


async def test_terminal_confirmation_uses_point_clocks_before_tariff(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.composition.reconciliation import reconcile_subscription
    from app.domains.billing.reconciliation import read_source_time
    from app.infrastructure.queries.billing_operator import has_newer_live_financial_point
    from app.domains.billing.reconciliation_contracts import PREPARED_SUBSCRIPTION_SCHEMA, RECONCILIATION_READ_SCHEMAS
    from app.infrastructure.preflight import PreflightBudget
    from app.integrations.lbx.dto import LbxRead, LbxTariff
    from app.models import ExternalCreateOperationKind as Kind
    from apps.api.tests.factories.billing_operator import terminal_object_request
    from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sub_id = service.linked_subscription_id(factory, purchase)
    client = sources.require_lbx()
    read_tariff = client.get_tariff
    confirmations: list[datetime] = []
    before = read_source_time(factory)

    async def timed_tariff(*, tariff_id: int, budget: PreflightBudget) -> LbxRead[LbxTariff]:
        confirmations.append(read_source_time(factory))
        return await read_tariff(tariff_id=tariff_id, budget=budget)

    monkeypatch.setattr(client, "get_tariff", timed_tariff)
    result = await reconcile_subscription(client, sources.billing, config, factory=factory, subscription_id=sub_id)
    [confirmed] = confirmations
    with factory() as db:
        observation = db.get(BillingStateObservation, result.observation_id)
        assert confirmed < observation.observed_at
        for kind, external_id in ((Kind.AGREEMENT, "456"), (Kind.SUBSCRIPTION, "567")):
            point = datetime.fromisoformat(observation.evidence_document[f"{kind.value}_read_finished_at"])
            assert before <= point <= confirmed
            for evidence_at, expected in ((before, True), (confirmed, False)):
                assert (
                    has_newer_live_financial_point(
                        db,
                        sub_id,
                        kind,
                        external_id,
                        evidence_at,
                        schemas=RECONCILIATION_READ_SCHEMAS,
                        preparation_schema=PREPARED_SUBSCRIPTION_SCHEMA,
                        matched_identity="match",
                    )
                    is expected
                )
        # A retained pre-upgrade observation has only its enclosing timestamp.
        document = {**observation.evidence_document}
        document.pop("subscription_read_finished_at")
        db.add(
            BillingStateObservation(
                observation_kind=observation.observation_kind,
                external_billing_account_id=observation.external_billing_account_id,
                user_id=observation.user_id,
                product_id=observation.product_id,
                subscription_id=sub_id,
                observed_at=observation.observed_at,
                evidence_schema_version=observation.evidence_schema_version,
                evidence_document=document,
                completeness_classification=observation.completeness_classification,
                result_classification=observation.result_classification,
            )
        )
        db.flush()
        assert has_newer_live_financial_point(
            db,
            sub_id,
            Kind.SUBSCRIPTION,
            "567",
            confirmed,
            schemas=RECONCILIATION_READ_SCHEMAS,
            preparation_schema=PREPARED_SUBSCRIPTION_SCHEMA,
            matched_identity="match",
        )

    transport.agreements[0]["close_date"] = "2026-11-05"
    transport.subscriptions[0]["state"] = 3
    request = terminal_object_request(factory, config, result.purchase, subscription_id="567")
    timed = request.model_copy(
        update={
            "evidence": request.evidence.model_copy(update={"senders_stopped_at": before, "confirmed_at": confirmed})
        }
    )
    assert completion.resolve_purchase(factory, config, timed, "os-euid:1000").state.resolved


@pytest.mark.parametrize("unavailable", [False, True], ids=["ended", "unavailable"])
async def test_pending_inventory_retains_open_agreement_independently(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    unavailable: bool,
) -> None:
    from app.composition.purchase_inventory import collect_inventory
    from app.domains.billing.operator_diagnostics import inspect_evidence
    from app.domains.billing.reconciliation import read_source_time
    from app.infrastructure.preflight import PreflightBudget
    from app.integrations.lbx.errors import LbxTimeout
    from apps.api.tests.factories.billing_operator import terminal_object_request
    from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare

    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    transport.agreements[0]["close_date"] = None
    transport.subscriptions[0]["state"] = 3
    before = read_source_time(factory)
    client = sources.require_lbx()
    if unavailable:

        async def unavailable_point(*, subscription_id: int, budget: PreflightBudget) -> None:
            raise LbxTimeout()

        monkeypatch.setattr(client, "get_subscription", unavailable_point)
    customer = service.customer_for_purchase(factory, config, purchase)
    async with sources.billing.operation(bound_scope=False) as budget:
        await collect_inventory(client, sources.billing, config, factory=factory, customer=customer, budget=budget)
    inspected = inspect_evidence(factory, config, purchase.user_id, purchase.id)
    agreement, subscription = inspected["operations"]
    assert agreement["original_point_facts"] is not None
    fact = agreement["original_point_facts"]["primary"]
    assert (fact["operation_id"], fact["external_object_id"], fact["fact"]) == (
        str(purchase.operations[0].id),
        "456",
        "open",
    )
    assert before < datetime.fromisoformat(fact["point_read_finished_at"]) <= read_source_time(factory)
    assert subscription["original_point_facts"] is None
    request = terminal_object_request(factory, config, purchase, subscription_id="567")
    stale = request.evidence.model_copy(update={"senders_stopped_at": before, "confirmed_at": before})
    with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
        completion.resolve_purchase(factory, config, request.model_copy(update={"evidence": stale}), "os-euid:1000")
    assert service.read_purchase(factory, purchase.user_id, purchase.id).held
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
