"""Audited inventory recovery against disposable PostgreSQL and simulated LBX."""

from copy import deepcopy
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import reconcile_purchase, resolve_review
from app.core.errors import AppError
from app.domains.billing import background_recovery as recovery
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase
from app.models import (
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ManualReviewCase,
    BillingWorkItem,
)
from sqlalchemy import select
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    synthetic_prepare,
    original,
    due,
)
from app.core.time import utc_now
from datetime import timedelta
from apps.api.tests.test_billing_recovery_cli_postgres import PRINCIPAL, unchanged_authority
from apps.api.tests.test_billing_worker_postgres import historical_link
from app.jobs.billing import BillingWorker
from app.domains.billing.work_contracts import WorkLane

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


async def inventory_review(
    scenario: tuple, factory: sessionmaker[Session], *, unknown: bool = False, two: bool = False
) -> tuple[Purchase, ...]:
    transport, sources, purchase = scenario
    first = synthetic_prepare(factory, transport, purchase, uncertain=unknown)
    purchases = (
        (first, historical_link(factory, first, transport, "brief_decoder", 1, uncertain_subscription=unknown))
        if two
        else (first,)
    )
    if not unknown:
        for purchase in purchases:
            await reconcile_purchase(
                sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
            )
    if not unknown:
        transport.subscriptions.append({**deepcopy(transport.subscriptions[0]), "subscription_id": 999})
    recovery.repair_batch(factory, step1_settings())
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.NORMAL)
        if unknown and two:
            # The first pass can classify the second purchase as incomplete
            # while waiting for the first UNKNOWN. A later inventory pass sees
            # the now-reviewed first purchase as unexplained competition too.
            with factory() as db:
                for row in db.scalars(select(BillingWorkItem).where(BillingWorkItem.work_kind != recovery.INVENTORY)):
                    row.next_attempt_at = utc_now() + timedelta(days=1)
                db.commit()
            due(factory, recovery.INVENTORY, first.customer_id)
            assert await worker.tick(WorkLane.URGENT)
    finally:
        await worker.aclose()
    if not unknown:
        transport.subscriptions.pop()
    assert all(service.read_purchase(factory, p.user_id, p.id).state == "manual_review" for p in purchases)
    return purchases


@pytest.mark.parametrize("unknown,two", [(False, False), (False, True), (True, False), (True, True)])
async def test_inventory_review_restores_original_or_binds_original_with_audit_and_replay(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], unknown: bool, two: bool
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    purchases = await inventory_review(background_scenario, factory, unknown=unknown, two=two)
    before = {p.id: tuple(original(factory, op.id) for op in p.operations) for p in purchases}
    for purchase in purchases:
        evidence = inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id)
        request = resolution_request(purchase, evidence, bind=unknown)
        calls = len(transport.requests)
        result = await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
        assert result["outcome"] == "resolved"
        assert service.read_purchase(factory, purchase.user_id, purchase.id).state == "linked"
        with factory() as db:
            case = db.get(ManualReviewCase, request.case_id)
            assert case.case_state == "resolved" and case.resolved_by_principal == PRINCIPAL
            proof = case.resolution_document["inventory_proof"]
            assert proof["schema"] == "review-inventory:v1"
            assert proof["candidate_count"] == len(purchases)
            assert proof["membership_digest"].startswith("sha256:")
            assert len(proof["purchases"]) == len(purchases)
        assert tuple(original(factory, op.id) for op in purchase.operations) == before[purchase.id]
        assert all(req.method == "GET" for req in transport.requests[calls:])
        calls = len(transport.requests)
        assert (await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL))[
            "outcome"
        ] == "already_resolved"
        assert len(transport.requests) == calls
        unchanged_authority(factory, purchase, holds=len(purchases))


@pytest.mark.parametrize(
    "failure",
    [
        "duplicate",
        "incomplete",
        "unstable",
        "foreign",
        "other_terms",
        "other_fence",
        "other_review",
        "cap",
        "missing_original",
    ],
)
async def test_inventory_review_rejects_incomplete_competing_or_changed_witnesses(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    first, second = await inventory_review(background_scenario, factory, two=True)
    evidence = inspect_evidence(factory, step1_settings(), first.user_id, first.id)
    request = resolution_request(first, evidence)
    if failure == "duplicate":
        transport.subscriptions.append({**deepcopy(transport.subscriptions[0]), "subscription_id": 999})
    elif failure == "cap":
        transport.subscriptions.extend(
            {**deepcopy(transport.subscriptions[0]), "subscription_id": 1000 + n} for n in range(21)
        )
    elif failure == "missing_original":
        transport.hide.add("/subscriptions")
    elif failure == "incomplete":
        transport.subscriptions[1]["state"] = None
    elif failure == "foreign":
        transport.agreements[1]["user_id"] = 999
    elif failure == "other_terms":
        transport.subscriptions[1]["total_price"] = 101
    else:
        client = sources.require_lbx()
        discover = client.discover_subscriptions
        calls = 0

        async def changed(**kwargs: object) -> tuple:
            nonlocal calls
            rows = await discover(**kwargs)
            calls += 1
            if calls == 2:
                if failure == "unstable":
                    return rows[:1]
                with factory() as db:
                    operation = next(op for op in second.operations if op.kind == Kind.SUBSCRIPTION)
                    if failure == "other_fence":
                        db.get(ExternalCreateOperation, operation.id).send_fence = uuid4()
                    else:
                        db.add(
                            ManualReviewCase(
                                scope_kind="create_operation",
                                scope_reference=str(operation.id),
                                reason_code="financial_binding_conflict",
                                case_state="open",
                                evidence_schema_version="test:v1",
                                evidence_document={},
                            )
                        )
                    db.commit()
            return rows

        monkeypatch.setattr(client, "discover_subscriptions", changed)
    with pytest.raises(AppError):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    with factory() as db:
        case = db.get(ManualReviewCase, request.case_id)
        assert case.case_state == "open" and case.resolution_document is None
    assert service.read_purchase(factory, first.user_id, first.id).state == "manual_review"
    unchanged_authority(factory, first, holds=2)


async def test_inventory_resolution_commit_failure_keeps_review_and_original_bindings(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, sources, _ = background_scenario
    factory = postgres_session_factory
    (purchase,) = await inventory_review(background_scenario, factory)
    request = resolution_request(purchase, inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id))
    commit = Session.commit

    def fail_resolution(db: Session) -> None:
        if any(isinstance(row, ManualReviewCase) and row.case_state == "resolved" for row in db.identity_map.values()):
            raise RuntimeError("simulated resolution commit failure")
        commit(db)

    monkeypatch.setattr(Session, "commit", fail_resolution)
    with pytest.raises(RuntimeError, match="resolution commit failure"):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    with factory() as db:
        assert db.get(ManualReviewCase, request.case_id).case_state == "open"
    assert service.read_purchase(factory, purchase.user_id, purchase.id).state == "manual_review"
    unchanged_authority(factory, purchase)


@pytest.mark.parametrize("failure", ["not_sent", "ambiguous_other"])
async def test_inventory_review_cannot_exclude_an_unproven_other_unknown(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    failure: str,
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    first, second = await inventory_review(background_scenario, factory, unknown=True, two=True)
    other = next(op for op in second.operations if op.kind == Kind.SUBSCRIPTION)
    if failure == "ambiguous_other":
        transport.subscriptions.append({**deepcopy(transport.subscriptions[1]), "subscription_id": 999})
    else:
        with factory() as db:
            case = db.scalars(select(ManualReviewCase).where(ManualReviewCase.scope_reference == str(other.id))).one()
            case.evidence_document = {
                **case.evidence_document,
                "operation_state_at_conflict": State.PROVEN_NOT_SENT.value,
            }
            db.commit()
    request = resolution_request(first, inspect_evidence(factory, step1_settings(), first.user_id, first.id), bind=True)
    with pytest.raises(AppError):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert service.read_purchase(factory, first.user_id, first.id).state == "manual_review"
    assert service.read_purchase(factory, second.user_id, second.id).state == "manual_review"
    unchanged_authority(factory, first, holds=2)
