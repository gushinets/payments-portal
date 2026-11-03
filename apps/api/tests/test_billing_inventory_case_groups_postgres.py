"""Related inventory conflicts: real Application writers, simulated GET-only LBX."""

from copy import deepcopy

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing_operator import reconcile_purchase, resolve_review
from app.composition.purchases import recover_financial
from app.core.errors import AppError
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State, ManualReviewCase
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    anyio_backend as anyio_backend,
    original,
)
from apps.api.tests.test_billing_inventory_resolution_postgres import inventory_review
from apps.api.tests.test_billing_recovery_cli_postgres import PRINCIPAL, unchanged_authority

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


async def combined_reviews(
    scenario: tuple, factory: sessionmaker[Session], *, unknown: bool, two: bool = False
) -> tuple[Purchase, ...]:
    transport, sources, _ = scenario
    purchases = await inventory_review(scenario, factory, unknown=unknown, two=two)
    if unknown:
        original_rows = list(transport.subscriptions)
        transport.subscriptions.extend(
            {**deepcopy(row), "subscription_id": 999 + index} for index, row in enumerate(original_rows)
        )
        for purchase in purchases:
            await recover_financial(
                sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
            )
        transport.subscriptions = original_rows
    else:
        for row in transport.subscriptions:
            row["services"][0]["price"] = 15
        for purchase in purchases:
            await reconcile_purchase(
                sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
            )
        for row in transport.subscriptions:
            row["services"][0]["price"] = 100
    return purchases


def expectations(factory: sessionmaker[Session], purchase: Purchase, *, unknown: bool, inventory: bool = False) -> dict:
    evidence = inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id)
    reason = (
        "customer_inventory_conflict"
        if inventory
        else "financial_binding_conflict"
        if unknown
        else "subscription_commercial_mismatch"
    )
    evidence["reviews"] = [c for c in evidence["reviews"] if c["reason"] == reason]
    return evidence


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("inventory", [False, True])
@pytest.mark.parametrize("two", [False, True])
async def test_related_inventory_cases_resolve_together_with_proof_audit_and_replay(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    unknown: bool,
    inventory: bool,
    two: bool,
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    purchases = await combined_reviews(background_scenario, factory, unknown=unknown, two=two)
    for purchase in purchases:
        before = tuple(original(factory, op.id) for op in purchase.operations)
        request = resolution_request(
            purchase, expectations(factory, purchase, unknown=unknown, inventory=inventory), bind=unknown
        )
        calls = len(transport.requests)
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
        evidence = inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id)
        assert evidence["state"] == "linked"
        assert evidence["subscription"]["financial"] == ("unverified" if unknown else "allowed")
        assert tuple(original(factory, op.id) for op in purchase.operations) == before
        with factory() as db:
            primary = db.get(ManualReviewCase, request.case_id)
            assert primary.case_state == "resolved"
            audit = primary.resolution_document
            assert audit["inventory_proof"]["candidate_count"] == len(purchases)
            assert len(audit["related_cases"]) == 1
            for case in db.scalars(select(ManualReviewCase)):
                if str(case.review_case_id) in {str(request.case_id), audit["related_cases"][0]["id"]}:
                    assert case.case_state == "resolved" and case.resolved_by_principal == PRINCIPAL
                    assert case.resolution_document["after"] == audit["after"]
                    assert case.resolution_document["inventory_proof"] == audit["inventory_proof"]
        assert all(req.method == "GET" for req in transport.requests[calls:])
        calls = len(transport.requests)
        result = await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
        assert result["outcome"] == "already_resolved" and len(transport.requests) == calls
        unchanged_authority(factory, purchase, holds=len(purchases))
    with factory() as db:
        assert all(case.case_state == "resolved" for case in db.scalars(select(ManualReviewCase)))


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("failure", ["duplicate", "incomplete", "other_operation", "stale_related", "rollback"])
async def test_related_inventory_resolution_refuses_unsafe_proof_or_rolls_back_all_cases(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    unknown: bool,
    failure: str,
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    (purchase,) = await combined_reviews(background_scenario, factory, unknown=unknown)
    # Select the non-inventory case: it must still require the inventory proof.
    request = resolution_request(purchase, expectations(factory, purchase, unknown=unknown), bind=unknown)
    before = tuple(original(factory, op.id) for op in purchase.operations)
    if failure == "duplicate":
        transport.subscriptions.append({**deepcopy(transport.subscriptions[0]), "subscription_id": 999})
    elif failure == "incomplete":
        transport.subscriptions[0]["total_price"] = None
    elif failure == "other_operation":
        current = service.read_purchase(factory, purchase.user_id, purchase.id)
        agreement = next(op for op in current.operations if op.kind == Kind.AGREEMENT)
        financial.financial_pending(factory, current, agreement, conflict=True)
    elif failure == "stale_related":
        client = sources.require_lbx()
        discover = client.discover_subscriptions
        calls = 0

        async def change_after_read(**kwargs: object) -> tuple:
            nonlocal calls
            rows = await discover(**kwargs)
            if kwargs.get("agreement_id") is None:
                calls += 1
                if calls == 2:
                    with factory() as db:
                        related = db.scalar(
                            select(ManualReviewCase).where(ManualReviewCase.review_case_id != request.case_id)
                        )
                        related.evidence_document = {**related.evidence_document, "changed_after_prepare": True}
                        db.commit()
            return rows

        monkeypatch.setattr(client, "discover_subscriptions", change_after_read)
    else:
        commit = Session.commit

        def fail_commit(db: Session) -> None:
            if any(
                isinstance(row, ManualReviewCase) and row.case_state == "resolved" for row in db.identity_map.values()
            ):
                raise RuntimeError("group resolution commit failure")
            commit(db)

        monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError if failure == "rollback" else AppError):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    assert tuple(original(factory, op.id) for op in purchase.operations) == before
    with factory() as db:
        assert all(
            case.case_state == "open" and case.resolution_document is None
            for case in db.scalars(select(ManualReviewCase))
        )
    assert service.read_purchase(factory, purchase.user_id, purchase.id).state == "manual_review"
    unchanged_authority(factory, purchase)


async def test_inventory_group_does_not_invent_possible_send_from_later_reviews(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    _, sources, _ = background_scenario
    factory = postgres_session_factory
    (purchase,) = await combined_reviews(background_scenario, factory, unknown=True)
    with factory() as db:
        case = db.scalar(select(ManualReviewCase).where(ManualReviewCase.reason_code == "customer_inventory_conflict"))
        case.evidence_document = {**case.evidence_document, "operation_state_at_conflict": State.PROVEN_NOT_SENT.value}
        db.commit()
    request = resolution_request(purchase, expectations(factory, purchase, unknown=True), bind=True)
    with pytest.raises(AppError, match="purchase_history_unproven"):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    unchanged_authority(factory, purchase)


async def test_inventory_group_never_clears_terminal_revival_conflict(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, _ = background_scenario
    factory = postgres_session_factory
    (purchase,) = await combined_reviews(background_scenario, factory, unknown=False)
    for state in (3, 2):
        transport.subscriptions[0]["state"] = state
        await reconcile_purchase(
            sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
    request = resolution_request(purchase, expectations(factory, purchase, unknown=False))
    with pytest.raises(AppError, match="billing_review_unrelated_cases"):
        await resolve_review(sources, step1_settings(), factory=factory, request=request, principal=PRINCIPAL)
    with factory() as db:
        assert all(case.case_state == "open" for case in db.scalars(select(ManualReviewCase)))
    unchanged_authority(factory, purchase)
