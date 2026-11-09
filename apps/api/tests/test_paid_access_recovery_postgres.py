"""Step 3: disposable PostgreSQL, synthetic source proof, autonomous local work."""

from dataclasses import replace
from datetime import timedelta
from uuid import UUID

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, null, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import resolve_review
from app.composition.billing_worker import billing_worker_resources
from app.domains.billing import background_recovery, work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import apply_customer_read
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.work_contracts import WorkLane
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import financial, service
from app.infrastructure.queries import billing_reconciliation, paid_access as paid_access_queries
from app.jobs.billing import BillingWorker
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    BillingWorkItem,
    ExternalSubscription,
    ManualReviewCase,
    PurchasedAllowance,
    ExternalCreateOperationKind as Kind,
)
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.factories.paid_runtime import (
    effective,
    reconcile,
    paid_scenario as paid_scenario,
    paid_source as paid_source,
)
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def expiry(factory: sessionmaker[Session]) -> BillingWorkItem:
    with factory() as db:
        return db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY)).one()


@pytest.mark.parametrize(
    "reading,queue",
    [("identity", "normal"), ("commercial", "missing"), ("negative", "old_payload"), ("blocked", "normal")],
)
async def test_paid_trust_expiry_retains_complete_proof_after_revocation(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    reading: str,
    queue: str,
) -> None:
    factory = postgres_session_factory
    transport, _, config, sub_id, _ = paid_scenario
    await reconcile(paid_scenario, factory)
    with factory() as db:
        sub = db.get(ExternalSubscription, sub_id)
        original, trust_end = sub.latest_observation_id, sub.projection_valid_until
        allowance_id = db.scalars(select(PurchasedAllowance.allowance_id)).one()
    if reading == "identity":
        transport.subscriptions[0]["agreement_id"] = 999
    elif reading == "commercial":
        transport.subscriptions[0]["services"][0]["price"] = 15
    elif reading == "blocked":
        transport.subscriptions[0]["current_blocking"] = 1
    else:
        transport.subscriptions[0].update(total_price=None, current_blocking=1)
    await reconcile(paid_scenario, factory)
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    with factory() as db:
        sub = db.get(ExternalSubscription, sub_id)
        assert sub.projection_valid_until == trust_end and sub.latest_observation_id != original
        job = db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY)).one()
        assert UUID(job.payload_document["supporting_observation_id"]) == original
        if queue == "missing":
            db.delete(job)
        elif queue == "old_payload":
            job.payload_document = {**job.payload_document, "supporting_observation_id": str(sub.latest_observation_id)}
        db.commit()
    missing_sources = config.model_copy(
        update={"lbx_base_url": "", "lbx_server_username": SecretStr(""), "lbx_server_password": SecretStr("")}
    )
    if queue == "missing":
        assert work.repair_paid_deadlines(factory, missing_sources) == 1
        assert UUID(expiry(factory).payload_document["supporting_observation_id"]) == original
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: as_utc(trust_end) + timedelta(seconds=1))
    requests = len(transport.requests)
    for _ in range(5):
        claim = work.claim_work(factory, missing_sources, WorkLane.LOCAL)
        assert claim is not None
        if claim.kind == work.EXPIRY:
            break
        background_recovery.apply_deadline(factory, claim)
    assert claim.kind == work.EXPIRY
    work.expire_trust(factory, claim)
    assert len(transport.requests) == requests and effective(factory) == (2, {"grants": [], "allowances": []})
    with factory() as db:
        cause = db.scalars(
            select(BillingStateObservation).where(
                BillingStateObservation.evidence_schema_version == "subscription-trust-expiry:v1"
            )
        ).one()
        assert cause.basis_observation_id == original and cause.effective_at == trust_end
        assert cause.resulting_access_revision is None
        assert UUID(cause.evidence_document["supporting_observation_id"]) == original
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == 2
        assert db.scalars(select(PurchasedAllowance.allowance_id)).one() == allowance_id
    assert expiry(factory).work_state == "completed"


async def test_paid_access_effective_expiry_without_source_configuration_and_same_cycle_recovery(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    transport, sources, config, sub_id, _ = paid_scenario
    await reconcile(paid_scenario, factory)
    before = effective(factory)
    job = expiry(factory)
    with factory() as db:
        sub = db.get(ExternalSubscription, sub_id)
        raw = sub.projection_valid_until
        assert raw - job.next_attempt_at == timedelta(seconds=10)
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: as_utc(job.next_attempt_at))
    missing = config.model_copy(
        update={
            "lbx_base_url": "",
            "lbx_server_username": SecretStr(""),
            "lbx_server_password": SecretStr(""),
            "lbx_external_billing_account_id": "",
            "paid_access_clock_skew_seconds": None,
        }
    )
    transport.requests.clear()
    worker = BillingWorker(missing, factory, None)
    try:
        for _ in range(5):
            if effective(factory)[0] == 2:
                break
            assert await worker.tick(WorkLane.LOCAL)
        assert not await worker.tick(WorkLane.URGENT)
        assert transport.requests == []
    finally:
        await worker.aclose()
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    with factory() as db:
        assert db.get(ExternalSubscription, sub_id).projection_valid_until == raw
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == 2
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1
    monkeypatch.undo()
    await reconcile(paid_scenario, factory)
    assert effective(factory) == (3, before[1])


@pytest.mark.parametrize("repair", ["missing", "completed"])
async def test_paid_access_restart_repairs_deadline_and_catches_up(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    repair: str,
) -> None:
    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    job = expiry(factory)
    with factory() as db:
        if repair == "missing":
            db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
        else:
            db.get(BillingWorkItem, job.work_item_id).work_state = "completed"
        db.commit()
    config = paid_scenario[2].model_copy(
        update={"lbx_base_url": "", "lbx_server_username": SecretStr(""), "lbx_server_password": SecretStr("")}
    )
    assert work.repair_paid_deadlines(factory, config) == 1
    assert expiry(factory).next_attempt_at == job.next_attempt_at
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: as_utc(job.next_attempt_at))
    # Production lifespan must start a local lane without constructing an LBX client.
    async with billing_worker_resources(
        config.model_copy(update={"billing_worker_enabled": True}), factory=factory
    ) as worker:
        assert worker is not None and worker.client is None
        import asyncio

        async with asyncio.timeout(10):
            while effective(factory)[0] != 2:
                await asyncio.sleep(0.01)
    assert effective(factory)[1] == {"grants": [], "allowances": []}


@pytest.mark.parametrize("storage", ["json_null", "sql_null"])
async def test_paid_access_revoked_scope_does_not_repeat_deadline_repair(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session], storage: str
) -> None:
    factory = postgres_session_factory
    transport, _, config, _, _ = paid_scenario
    await reconcile(paid_scenario, factory)
    transport.subscriptions[0]["current_blocking"] = 1
    await reconcile(paid_scenario, factory)
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    with factory() as db:
        scope = db.scalars(select(BillingProductAccessScope)).one()
        assert scope.effective_access_document is None
        if storage == "sql_null":
            scope.effective_access_document = null()
            db.commit()
        assert (
            paid_access_queries.missing_deadline_users(db, config.instance_tenant_id, config.instance_region, 1) == []
        )
    assert (work.repair_paid_deadlines(factory, config), work.repair_paid_deadlines(factory, config)) == (0, 0)
    assert effective(factory) == (2, {"grants": [], "allowances": []})


@pytest.mark.parametrize("race", ["refresh", "stale_owner"])
async def test_paid_access_expiry_rechecks_refreshed_authority_and_queue_owner(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    race: str,
) -> None:
    factory, config = postgres_session_factory, paid_scenario[2]
    await reconcile(paid_scenario, factory)
    job = expiry(factory)
    clock = billing_reconciliation.database_now
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: as_utc(job.next_attempt_at))
    claim = work.claim_work(factory, config, WorkLane.LOCAL)
    from app.domains.billing import background_recovery

    while claim and claim.kind != work.EXPIRY:
        background_recovery.apply_deadline(factory, claim)
        claim = work.claim_work(factory, config, WorkLane.LOCAL)
    assert claim is not None and claim.kind == work.EXPIRY
    if race == "refresh":
        monkeypatch.setattr(billing_reconciliation, "database_now", clock)
        await reconcile(paid_scenario, factory)
        saved = expiry(factory)
        work.expire_trust(factory, claim)
        assert expiry(factory).next_attempt_at == saved.next_attempt_at
    else:
        with factory() as db:
            db.get(BillingWorkItem, job.work_item_id).lease_owner = "new-local-owner"
            db.commit()
        with pytest.raises(BillingRefused, match="billing_work_stale"):
            work.expire_trust(factory, claim)
    assert effective(factory)[0] == 1
    with factory() as db:
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == 1
        assert (
            db.scalar(
                select(func.count())
                .select_from(BillingStateObservation)
                .where(BillingStateObservation.evidence_schema_version == "subscription-trust-expiry:v1")
            )
            == 0
        )


@pytest.mark.parametrize("failure", ["customer", "financial", "rollback", "expiry"])
async def test_paid_access_customer_vs_product_review_blast_radius_and_rollback(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    factory = postgres_session_factory
    transport, sources, config, sub_id, user_id = paid_scenario
    await reconcile(paid_scenario, factory)
    with factory() as db:
        purchase_id = db.get(ExternalSubscription, sub_id).purchase_intent_id
    purchase = service.read_purchase(factory, user_id, purchase_id)
    template = replace(
        purchase,
        accepted=purchase.accepted.model_copy(
            update={
                "meaning": purchase.accepted.meaning.model_copy(update={"expected_technical_terms_digest": None}),
            }
        ),
    )
    second = historical_link(factory, template, transport, "brief_decoder", 1)
    from app.composition.billing_operator import reconcile_purchase

    await reconcile_purchase(sources, config, factory=factory, user_id=user_id, purchase_id=second.id)
    from apps.api.tests.test_paid_access_rebase_postgres import run_inventory
    from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario

    await run_inventory(Scenario(factory, config, transport, sources, sub_id))
    if failure == "expiry":
        # Give the independent product a later authoritative trust deadline.
        with factory() as db:
            refreshed_at = billing_reconciliation.database_now(db) + timedelta(minutes=5)
        monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: refreshed_at)
        await reconcile_purchase(sources, config, factory=factory, user_id=user_id, purchase_id=second.id)
    before = effective(factory)
    assert len(before[1]["grants"]) == 2
    if failure == "customer":
        current = service.customer_for_purchase(factory, config, purchase)
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            apply_customer_read(factory, current, provider_id=current.provider_id, outer_key="foreign-paired-key")
        assert effective(factory) == (before[0] + 1, {"grants": [], "allowances": []})
    elif failure == "expiry":
        with factory() as db:
            boundary = db.scalar(
                select(BillingProductAccessScope.effective_access_until).where(
                    BillingProductAccessScope.product_id == "proposal_ai"
                )
            )
            assert (
                db.scalar(
                    select(BillingProductAccessScope.effective_access_until).where(
                        BillingProductAccessScope.product_id == "brief_decoder"
                    )
                )
                > boundary
            )
        monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: as_utc(boundary))
        worker = BillingWorker(config, factory, None)
        try:
            for _ in range(10):
                if effective(factory)[0] > before[0]:
                    break
                assert await worker.tick(WorkLane.LOCAL)
        finally:
            await worker.aclose()
        assert effective(factory) == (
            before[0] + 1,
            {"grants": [{"product_id": "brief_decoder", "valid_until": None}], "allowances": []},
        )
    else:
        if failure == "rollback":

            def fail(db: Session) -> None:
                raise RuntimeError("synthetic final commit failure")

            monkeypatch.setattr(Session, "commit", fail)
        operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
        if failure == "rollback":
            with pytest.raises(RuntimeError):
                financial.financial_pending(factory, purchase, operation, conflict=True)
            assert effective(factory) == before
            with factory() as db:
                assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
        else:
            financial.financial_pending(factory, purchase, operation, conflict=True)
            revision, state = effective(factory)
            assert revision == before[0] + 1 and [g["product_id"] for g in state["grants"]] == ["brief_decoder"]


@pytest.mark.parametrize(
    "refusal",
    [
        None,
        "stale",
        "blocked",
        "ended",
        "wrong_scope",
        "audit_failure",
        "superseded",
        "financial_review",
        "unrelated_review",
    ],
)
async def test_paid_access_audited_primary_resolution_uses_fresh_original_proof(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    refusal: str | None,
) -> None:
    from app.core.errors import AppError
    from app.domains.billing import operator_review

    factory = postgres_session_factory
    transport, sources, config, sub_id, user_id = paid_scenario
    # A candidate predating a retired primary needs the audited primary action.
    with factory() as db:
        db.scalar(select(BillingProductAccessScope)).primary_subscription_id = None
        db.commit()
    await reconcile(paid_scenario, factory, config.model_copy(update={"paid_access_clock_skew_seconds": None}))
    with factory() as db:
        db.scalar(select(BillingProductAccessScope)).primary_retired_at = billing_reconciliation.database_now(db)
        db.commit()
    from apps.api.tests.test_paid_access_rebase_postgres import run_inventory
    from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario

    await run_inventory(Scenario(factory, config, transport, sources, sub_id))
    assert effective(factory)[0] == 0
    with factory() as db:
        purchase_id = db.get(ExternalSubscription, sub_id).purchase_intent_id
    purchase = service.read_purchase(factory, user_id, purchase_id)
    evidence = inspect_evidence(factory, config, user_id, purchase_id)
    request = resolution_request(purchase, evidence).model_copy(update={"resolution": "select-primary"})
    if refusal in {"financial_review", "unrelated_review"}:
        with factory() as db:
            if refusal == "financial_review":
                operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
                db.add(
                    ManualReviewCase(
                        reason_code="financial_binding_conflict",
                        scope_kind="create_operation",
                        scope_reference=str(operation.id),
                        evidence_schema_version="financial-review:v1",
                        evidence_document={},
                        case_state="open",
                    )
                )
            else:
                db.add(
                    ManualReviewCase(
                        reason_code="unrelated-open-review",
                        scope_kind="subscription",
                        scope_reference=str(sub_id),
                        evidence_schema_version="v1",
                        evidence_document={},
                        case_state="open",
                    )
                )
            db.commit()
    elif refusal == "stale":
        request = request.model_copy(
            update={"expected_reconciliation_fence": request.expected_reconciliation_fence + 1}
        )
    elif refusal == "wrong_scope":
        request = request.model_copy(update={"user_id": UUID(int=55)})
    elif refusal == "blocked":
        transport.subscriptions[0]["current_blocking"] = 1
    elif refusal == "ended":
        transport.subscriptions[0]["state"] = 3
    elif refusal == "superseded":
        from app.domains.billing.customers import lock_user
        from app.infrastructure.preflight import PreflightBudget
        from app.integrations.lbx.financial import Subscription

        original_read = sources.require_lbx().get_subscription

        async def superseded(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
            point = await original_read(subscription_id=subscription_id, budget=budget)
            with factory() as db:
                lock_user(db, user_id)
                db.get(ExternalSubscription, sub_id).reconciliation_fencing_token += 1
                db.commit()
            return point

        monkeypatch.setattr(sources.require_lbx(), "get_subscription", superseded)
    elif refusal == "audit_failure":

        def fail(*args: object, **kwargs: object) -> None:
            raise RuntimeError("synthetic audit write failure")

        monkeypatch.setattr(operator_review, "audit_resolution", fail)
    count = len(transport.requests)
    if refusal:
        with pytest.raises(RuntimeError if refusal == "audit_failure" else AppError):
            await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
        assert effective(factory)[0] == 0
        with factory() as db:
            assert db.get(ManualReviewCase, request.case_id).case_state == "open"
            assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 0
    else:
        await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
        assert effective(factory)[0] == 1
        with factory() as db:
            case = db.get(ManualReviewCase, request.case_id)
            assert case.case_state == "resolved" and case.resolved_by_principal == "os-euid:1000"
            assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) == sub_id
        count = len(transport.requests)
        assert (await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000"))[
            "outcome"
        ] == "already_resolved"
        assert len(transport.requests) == count
    assert all(req.method == "GET" for req in transport.requests[count:])


async def test_paid_access_restore_original_reuses_allowance_and_cycle_review_requires_original_meaning(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    factory = postgres_session_factory
    transport, sources, config, sub_id, user_id = paid_scenario
    await reconcile(paid_scenario, factory)
    before = effective(factory)[1]
    with factory() as db:
        purchase_id = db.get(ExternalSubscription, sub_id).purchase_intent_id
    purchase = service.read_purchase(factory, user_id, purchase_id)
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    financial.financial_pending(factory, purchase, operation, conflict=True)
    assert effective(factory)[1] == {"grants": [], "allowances": []}
    request = resolution_request(purchase, inspect_evidence(factory, config, user_id, purchase_id))
    await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    assert effective(factory) == (3, before)
    transport.subscriptions[0]["subscription_instance_start_date"] = "2026-10-31"
    await reconcile(paid_scenario, factory)
    assert effective(factory)[1]["allowances"] == []
    transport.subscriptions[0]["subscription_instance_start_date"] = "2026-01-31"
    await reconcile(paid_scenario, factory)
    assert effective(factory)[1] == before
    with factory() as db:
        review = db.scalar(select(ManualReviewCase).where(ManualReviewCase.reason_code == "allowance_cycle_conflict"))
        assert review.case_state == "resolved" and review.resolved_by_principal == "system:original-cycle-proof"
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1


@pytest.mark.parametrize("entry", ["interactive_integrity_error", "background_identity_conflict"])
async def test_paid_access_identity_conflict_other_entrypoints_are_atomic(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    entry: str,
) -> None:
    from sqlalchemy.exc import IntegrityError
    from app.domains.billing.customer_conflicts import record_customer_conflict

    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    _, _, config, sub_id, user_id = paid_scenario
    with factory() as db:
        purchase_id = db.get(ExternalSubscription, sub_id).purchase_intent_id
    purchase = service.read_purchase(factory, user_id, purchase_id)
    current = service.customer_for_purchase(factory, config, purchase)
    if entry == "interactive_integrity_error":
        commit = Session.commit
        calls = 0

        def conflict_once(db: Session) -> None:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise IntegrityError("synthetic unique binding conflict", None, Exception())
            commit(db)

        monkeypatch.setattr(Session, "commit", conflict_once)
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            apply_customer_read(factory, current, provider_id=current.provider_id, outer_key=current.outer_key)
        assert calls == 2
    else:
        record_customer_conflict(factory, current, None)
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    # An ID collision or an unclassified identity conflict cannot use the
    # narrow original-key recovery path introduced by Step 8 review fixes.
    from app.infrastructure.queries.billing_customers import customer_operation, lock_customer
    from app.domains.billing.customers import _snapshot

    with factory() as db:
        customer = lock_customer(db, current.customer_id)
        restored = _snapshot(customer, customer_operation(db, current.customer_id))
    with pytest.raises(BillingRefused, match="billing_identity_conflict"):
        apply_customer_read(factory, restored, provider_id=current.provider_id, outer_key=current.outer_key)
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    with pytest.raises(BillingRefused, match="billing_identity_unproven"):
        await reconcile(paid_scenario, factory)
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1
        assert db.scalars(select(ManualReviewCase)).one().case_state == "open"


async def test_paid_access_production_sweep_reduces_simulated_metering_without_http(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.core.settings import AppEnv

    factory = postgres_session_factory
    await reconcile(paid_scenario, factory)
    config = paid_scenario[2].model_copy(update={"app_env": AppEnv.PRODUCTION, "purchase_test_terms_enabled": False})
    before = effective(factory)[1]
    paid_scenario[0].requests.clear()
    assert work.repair_paid_deadlines(factory, config) == 1
    revision, state = effective(factory)
    assert revision == 2 and state == {"grants": before["grants"], "allowances": []}
    assert work.repair_paid_deadlines(factory, config) == 0
    assert paid_scenario[0].requests == []
    await reconcile(paid_scenario, factory, config)
    assert effective(factory) == (2, state)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1


@pytest.mark.parametrize("paid_scenario", ["timestamp"], indirect=True)
async def test_paid_access_allowance_deadline_omits_only_metering_and_schedules_next_boundary(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from datetime import UTC, datetime
    from app.integrations.lbx import reconciliation as integration
    from unittest.mock import AsyncMock

    factory = postgres_session_factory
    transport, sources, config, _, _ = paid_scenario
    # Stay later than fixture preparation even when CI runs after November 2026.
    year = datetime.now(UTC).year + 1
    transport.subscriptions[0].update(
        subscription_instance_start_date=f"{year}-01-31T12:34:56.123456+03:00",
        last_tariffication_period_start=f"{year}-10-31T12:34:56.123456+03:00",
        last_tariffication_period_end=f"{year}-11-30T12:34:56.123456+03:00",
    )
    instant = datetime(year, 11, 30, 8, tzinfo=UTC)
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: instant)
    monkeypatch.setattr(integration, "utc_now", lambda: instant)
    await reconcile(paid_scenario, factory)
    before = effective(factory)[1]
    deadline = as_utc(expiry(factory).next_attempt_at)
    assert deadline == datetime.fromisoformat(before["allowances"][0]["period_end"])
    instant = deadline
    # Even an entirely failed configured client cannot affect local processing.
    fail = AsyncMock(side_effect=RuntimeError("synthetic source outage"))
    for method in ("get_user", "get_agreement", "get_subscription", "get_tariff"):
        monkeypatch.setattr(sources.require_lbx(), method, fail)
    transport.requests.clear()
    worker = BillingWorker(config, factory, sources.require_lbx())
    try:
        for _ in range(5):
            if effective(factory)[0] == 2:
                break
            assert await worker.tick(WorkLane.LOCAL)
    finally:
        await worker.aclose()
    assert effective(factory) == (2, {"grants": before["grants"], "allowances": []})
    fail.assert_not_awaited()
    assert transport.requests == []
    assert as_utc(expiry(factory).next_attempt_at) > deadline
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1
        assert (
            db.scalar(
                select(BillingStateObservation.result_classification).where(
                    BillingStateObservation.evidence_schema_version == "subscription-trust-expiry:v1"
                )
            )
            == "effective_access_deadline"
        )


@pytest.mark.parametrize("restriction", ["customer", "product"])
async def test_stale_active_cannot_cross_restriction_and_audited_recovery(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    restriction: str,
) -> None:
    from app.composition.billing import bootstrap_account
    from app.domains.billing.reconciliation import claim_reconciliation, apply_reconciliation
    from app.integrations.lbx.reconciliation import read_subscription_proof
    from apps.api.tests.test_any709_step3_postgres import TOKEN

    factory = postgres_session_factory
    transport, sources, config, sub_id, user_id = paid_scenario
    await reconcile(paid_scenario, factory)
    original = effective(factory)[1]
    subject = claim_reconciliation(factory, config, sub_id, io_timeout_seconds=60)
    async with sources.billing.operation() as budget:
        stale = await read_subscription_proof(sources.require_lbx(), subject, config, budget=budget)
    purchase = subject.purchase
    if restriction == "customer":
        current = service.customer_for_purchase(factory, config, purchase)
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            apply_customer_read(factory, current, provider_id=current.provider_id, outer_key="wrong-original-key")
    else:
        op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
        financial.financial_pending(factory, purchase, op, conflict=True)
    assert effective(factory) == (2, {"grants": [], "allowances": []})
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        apply_reconciliation(factory, subject, stale, clock_skew_seconds=10)
    if restriction == "customer":
        await bootstrap_account(sources, config, factory=factory, token=TOKEN)
        assert effective(factory)[0] == 2
        await reconcile(paid_scenario, factory)
    else:
        request = resolution_request(purchase, inspect_evidence(factory, config, user_id, purchase.id))
        await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    assert effective(factory) == (3, original)
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        apply_reconciliation(factory, subject, stale, clock_skew_seconds=10)
    with factory() as db:
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == 3
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1
