"""Canonical negative-proof fencing and timely operator rejection; SIMULATED LBX."""

import asyncio
from dataclasses import replace
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition import reconciliation as composition
from app.composition.billing_operator import resolve_review
from app.composition.sources import SourceResources
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.operator_contracts import ResolutionRequest
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.reconciliation import read_source_time
from app.domains.billing.reconciliation_contracts import SubscriptionProof
from app.domains.purchases.contracts import Purchase, PurchaseRefused
from app.infrastructure.preflight import PreflightAdmission, PreflightBudget, PreflightPolicy
from app.integrations.lbx.errors import LbxScopeMismatch
from app.models import (
    BillingStateObservation,
    ExternalBillingCustomer,
    ExternalSubscription,
    ManualReviewCase,
)
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    synthetic_prepare,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
RestoreScenario = tuple[PurchaseTransport, SourceResources, Purchase, UUID, ResolutionRequest]


@pytest.fixture
async def customer_restore_scenario(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> RestoreScenario:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    transport.pool = factory.kw["bind"].pool
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    transport.subscriptions[0].update(
        state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-11-01"
    )
    with factory() as db:
        identity = db.scalar(select(ExternalSubscription.subscription_id))
    transport.subscriptions[0]["services"][0]["price"] = 150
    await composition.reconcile_subscription(
        sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=identity
    )
    transport.subscriptions[0]["services"][0]["price"] = 100
    request = resolution_request(purchase, inspect_evidence(factory, config, purchase.user_id, purchase.id))
    transport.customer["outer_id"] = "changed-original-key"
    return transport, sources, purchase, identity, request


@pytest.mark.parametrize("invalid", ["owner", "fence", "expired-lease", "previous-proof", "newer-success"])
async def test_restore_customer_negative_keeps_canonical_proof_guards(
    customer_restore_scenario: RestoreScenario,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    invalid: str,
) -> None:
    transport, sources, purchase, identity, request = customer_restore_scenario
    factory, config = postgres_session_factory, step1_settings()
    original_read = composition.read_subscription_proof
    superseded = False
    expected_observation = request.expected_observation_id

    async def read_then_supersede(*args: Any, **kwargs: Any) -> SubscriptionProof:
        nonlocal superseded, expected_observation
        proof = await original_read(*args, **kwargs)
        if superseded:
            return proof
        superseded = True
        subject = args[1]
        assert "customer_original_key_mismatch" in proof.reasons
        if invalid == "previous-proof":
            return replace(proof, read_started_at=subject.claimed_at - timedelta(seconds=1))
        with factory() as db:
            sub = db.get(ExternalSubscription, identity)
            if invalid == "owner":
                sub.reconciliation_lease_owner = "another-owner"
            elif invalid == "fence":
                sub.reconciliation_fencing_token += 1
            else:
                sub.reconciliation_lease_expires_at = read_source_time(factory) - timedelta(seconds=1)
            db.commit()
        if invalid == "newer-success":
            transport.customer["outer_id"] = subject.customer.outer_key
            newer = await composition.reconcile_subscription(
                sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=identity
            )
            expected_observation = newer.observation_id
        return proof

    monkeypatch.setattr(composition, "read_subscription_proof", read_then_supersede)
    with pytest.raises(BillingRefused, match="subscription_reconciliation_stale"):
        await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    with factory() as db:
        assert db.get(ExternalBillingCustomer, purchase.customer_id).binding_state == "bound"
        assert db.get(ExternalSubscription, identity).latest_observation_id == expected_observation
        case = db.get(ManualReviewCase, request.case_id)
        assert case.case_state == "open" and case.resolution_document is None
        assert not list(db.scalars(select(ManualReviewCase).where(ManualReviewCase.scope_kind == "create_operation")))
    assert not any(request.method == "POST" for request in transport.requests)


@pytest.mark.parametrize("conflict", ["original_key", "scope_error"])
async def test_restore_timely_customer_negative_survives_policy_deadline(
    customer_restore_scenario: RestoreScenario,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    conflict: str,
) -> None:
    transport, sources, purchase, identity, request = customer_restore_scenario
    factory, config = postgres_session_factory, step1_settings()
    admission = PreflightAdmission(PreflightPolicy(0.5, 0.025, 1, 0))
    operator_sources = replace(sources, billing=admission)
    reached_policy, never_release = asyncio.Event(), asyncio.Event()
    with factory() as db:
        sub = db.get(ExternalSubscription, identity)
        trust = (sub.last_authoritative_read_at, sub.projection_valid_until)

    async def scope_error(**kwargs: Any) -> Any:
        raise LbxScopeMismatch()

    async def blocked_policy(*, tariff_id: int, budget: PreflightBudget) -> None:
        async def source() -> None:
            reached_policy.set()
            await never_release.wait()

        await budget.run(source)

    monkeypatch.setattr(sources.require_lbx(), "get_tariff", blocked_policy)
    if conflict == "scope_error":
        monkeypatch.setattr(sources.require_lbx(), "get_user", scope_error)
    try:
        with pytest.raises(PurchaseRefused, match="billing_review_stale"):
            await resolve_review(operator_sources, config, factory=factory, request=request, principal="os-euid:1000")
    finally:
        await admission.aclose()
    assert reached_policy.is_set()
    with factory() as db:
        assert db.get(ExternalBillingCustomer, purchase.customer_id).binding_state == "identity_conflict"
        sub = db.get(ExternalSubscription, identity)
        assert (sub.financial_access_status, sub.commercial_access_status) == ("blocked", "ineligible")
        assert (sub.last_authoritative_read_at, sub.projection_valid_until) == trust
        observation = db.get(BillingStateObservation, sub.latest_observation_id)
        assert observation.result_classification == "customer_identity_conflict"
        assert "read_budget_exhausted" in observation.evidence_document["reasons"]
        case = db.get(ManualReviewCase, request.case_id)
        assert case.case_state == "open" and case.resolution_document is None
        customer_cases = list(
            db.scalars(select(ManualReviewCase).where(ManualReviewCase.scope_kind == "create_operation"))
        )
        assert len(customer_cases) == 1
        assert customer_cases[0].reason_code == (
            "customer_original_key_mismatch" if conflict == "original_key" else "customer_identity_conflict"
        )
    assert not any(request.method == "POST" for request in transport.requests)
