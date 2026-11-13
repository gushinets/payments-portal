"""Durable restrictions and strict admission across read/apply failures (REV-6/7)."""

from collections.abc import Callable
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
import time
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.composition import purchase_inventory
from app.composition.billing_operator import resolve_review
from app.composition.purchase_offer import live_original
from app.composition.reconciliation import reconcile_subscription
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.discovery import apply_inventory, persist_discoveries
from app.domains.billing.inventory_history import (
    INVENTORY_RELATIONSHIP_SCHEMA,
    retained_subscription_relationships,
)
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation
from app.domains.billing.reconciliation_contracts import SubscriptionRelationship
from app.domains.catalog.link_publication import publish_product_link
from app.domains.catalog.product_link import current_offer_fingerprint
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import PurchaseRefused
from app.domains.purchases.inventory_contracts import InventoryResult, InventoryStale
from app.infrastructure.preflight import PreflightBudget
from app.infrastructure.queries import billing_reconciliation
from app.integrations.lbx.errors import LbxScopeForbidden, LbxUnavailable
from app.integrations.lbx.financial import NewAgreement, Subscription
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    ManualReviewCase,
)
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN
from apps.api.tests.test_billing_background_recovery_postgres import synthetic_prepare
from apps.api.tests.test_billing_scoped_inventory_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    bound_point_relationship_scenario as bound_point_relationship_scenario,
    inventory,
)
from apps.api.tests.test_paid_access_rebase_postgres import claim_inventory
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("late_change", ["none", "scope-refusal", "source-claim"])
async def test_strict_create_rejects_changed_source_receipt(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    late_change: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    transport.subscriptions[0].update(
        state=2, last_tariffication_period_start="2026-10-01", last_tariffication_period_end="2026-10-31"
    )
    linked = publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(product_id="brief_decoder", tariff_id=702)),
        expected_previous_revision=0,
        deadline=time.monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    ).stored
    offer = replace(first.accepted.offer, tariff_id=702)
    offer = replace(offer, fingerprint=current_offer_fingerprint(first.account_id, linked.document.selection, offer))
    recording = deepcopy(transport.offer)
    recording.tariff_id = 702
    for name in recording.bodies:
        recording.bodies[name] = recording.bodies[name].replace(b'"tariff_id":701', b'"tariff_id":702')
    transport.offers[702] = recording
    meaning = first.accepted.meaning.model_copy(
        update={
            "product_id": "brief_decoder",
            "revision_id": linked.mapping_revision_id,
            "expected_fingerprint": offer.fingerprint,
        }
    )
    second = service.pin_purchase(
        factory, config, TOKEN, "strict-review", meaning, linked, offer, first.accepted.documents
    )
    async with sources.billing.operation(bound_scope=False) as budget:
        assert await live_original(sources, config, second, factory, budget=budget)
    result = await inventory(sources, factory, first)
    result.require_clear(second)
    assert result.complete and len(result.sources) == 1 and result.sources[0].proof.complete
    source = result.sources[0]

    async def denied(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        raise LbxScopeForbidden()

    if late_change == "scope-refusal":
        monkeypatch.setattr(sources.require_lbx(), "get_subscription", denied)
        late = await reconcile_subscription(
            sources.require_lbx(),
            sources.billing,
            config,
            factory=factory,
            subscription_id=source.subject.subscription_id,
        )
        assert not late.proof.complete
        assert any(reason.endswith("lbx_scope_forbidden") for reason in late.proof.reasons)
    elif late_change == "source-claim":
        claim_reconciliation(factory, config, source.subject.subscription_id, io_timeout_seconds=60)
    with factory() as db:
        sub = db.get(ExternalSubscription, source.subject.subscription_id)
        assert sub.latest_observation_id == source.observation_id
        assert (sub.reconciliation_fencing_token != source.subject.fence) == (late_change != "none")
    operation = next(op for op in second.operations if op.kind == Kind.AGREEMENT)
    command = NewAgreement(
        user_id=345,
        organization_id=21,
        agreement_number=operation.key,
        create_date=operation.agreement_create_date or date(2026, 10, 27),
    )

    def claim() -> None:
        claimed = financial.claim_financial(
            factory, second, operation, command.request_document(), configuration=config, token=TOKEN, inventory=result
        )
        assert claimed.may_send

    if late_change == "none":
        claim()
    else:
        with pytest.raises(InventoryStale):
            claim()
    with factory() as db:
        op = db.get(ExternalCreateOperation, operation.id)
        assert op.operation_state == (State.POSSIBLE_SEND if late_change == "none" else State.PENDING)
        assert (op.unknown_since is not None) == (late_change == "none")


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
@pytest.mark.parametrize("contradictory", [False, True])
@pytest.mark.parametrize("expired", ["work", "source"])
async def test_canonical_relationship_survives_refused_apply(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    contradictory: bool,
    expired: str,
) -> None:
    transport, sources, first, _, third, _ = bound_point_relationship_scenario
    factory = postgres_session_factory
    # Use the actual admission budget for this worker scenario: its earlier
    # work claim must expire before the later source claim. Do not inherit a
    # different worker budget from the local .env or a peer checkout's defaults.
    config = step1_settings(
        paid_access_clock_skew_seconds=10,
        billing_worker_io_timeout_seconds=sources.billing.policy.total_timeout_seconds,
    )
    transport.subscriptions[0]["tariff_id"] = 703 if contradictory else 701
    first_id = service.linked_subscription_id(factory, first)
    third_id = service.linked_subscription_id(factory, third)
    scenario = Scenario(factory, config, transport, sources, third_id)
    claim = claim_inventory(scenario)
    seen = []
    original_now = billing_reconciliation.database_now
    clock = {"offset": timedelta()}
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: original_now(db) + clock["offset"])

    class StopAfterRefusedApply(Exception):
        pass

    async def delegate(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        if fn is apply_reconciliation and args[1].subscription_id == first_id:
            subject, proof = args[1:3]
            assert proof.point_relationship == SubscriptionRelationship("456", 703 if contradictory else 701)
            seen.append(proof)
            assert proof.read_finished_at < claim.expires_at < subject.lease_expires_at
            resume_at = (claim.expires_at if expired == "work" else subject.lease_expires_at) + timedelta(
                microseconds=1
            )
            with factory() as db:
                clock["offset"] = resume_at - original_now(db)
            with pytest.raises(BillingRefused) as refused:
                await run_in_threadpool(fn, *args, **kwargs)
            assert refused.value.code == (
                "billing_work_stale" if expired == "work" else "subscription_reconciliation_stale"
            )
            raise StopAfterRefusedApply()
        return await run_in_threadpool(fn, *args, **kwargs)

    with pytest.raises(StopAfterRefusedApply):
        await inventory(sources, factory, first, claim=claim, delegate=delegate)
    assert len(seen) == 1
    assert seen[0].point_relationship in retained_subscription_relationships(factory, first).relationships
    with factory() as db:
        retained = db.scalar(
            select(BillingStateObservation).where(
                BillingStateObservation.subscription_id == first_id,
                BillingStateObservation.evidence_schema_version == INVENTORY_RELATIONSHIP_SCHEMA,
            )
        )
        if contradictory:
            assert retained is not None and retained.evidence_document["complete"] is False
            assert retained.observed_at == seen[0].read_finished_at
            assert retained.evidence_document["read_started_at"] == seen[0].read_started_at.isoformat().replace(
                "+00:00", "Z"
            )
            assert retained.evidence_document["provenance"]["purchase_intent_id"] == str(first.id)
        deadlines = [
            sub.reconciliation_lease_expires_at
            for sub in db.scalars(select(ExternalSubscription))
            if sub.reconciliation_lease_expires_at is not None
        ]
        clock["offset"] = max([claim.expires_at, *deadlines]) + timedelta(seconds=1) - original_now(db)
    read = sources.require_lbx().get_subscription

    async def unavailable(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxUnavailable()
        return await read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", unavailable)
    next_claim = claim_inventory(scenario)
    result = persist_discoveries(factory, next_claim, await inventory(sources, factory, first, claim=next_claim))
    product = next(item for item in result.products if item.product_id == "acceptance_builder")
    assert product.complete is not contradictory
    apply_inventory(factory, next_claim, result, "inventory_incomplete", clock_skew_seconds=10)
    with factory() as db:
        primary = db.scalar(
            select(BillingProductAccessScope.primary_subscription_id).where(
                BillingProductAccessScope.product_id == "acceptance_builder"
            )
        )
        assert primary == (None if contradictory else third_id)


@pytest.mark.parametrize("bound_point_relationship_scenario", [True], indirect=True)
@pytest.mark.parametrize("late_refusal", [False, True])
async def test_restore_original_rejects_changed_sibling_receipt(
    bound_point_relationship_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    late_refusal: bool,
) -> None:
    transport, sources, first, second, _, _ = bound_point_relationship_scenario
    factory, config = postgres_session_factory, step1_settings()
    transport.subscriptions[0]["tariff_id"] = 701
    first_id = service.linked_subscription_id(factory, first)
    second_id = service.linked_subscription_id(factory, second)
    transport.subscriptions[1]["services"][0]["price"] = 15
    await reconcile_subscription(
        sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=second_id
    )
    transport.subscriptions[1]["services"][0]["price"] = 100
    request = resolution_request(second, inspect_evidence(factory, config, second.user_id, second.id))
    collect = purchase_inventory.collect_inventory
    read = sources.require_lbx().get_subscription

    async def denied(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxScopeForbidden()
        return await read(subscription_id=subscription_id, budget=budget)

    async def concurrent_poll(*args: Any, **kwargs: Any) -> InventoryResult:
        result = await collect(*args, **kwargs)
        assert result.complete
        if late_refusal:
            monkeypatch.setattr(sources.require_lbx(), "get_subscription", denied)
            late = await reconcile_subscription(
                sources.require_lbx(), sources.billing, config, factory=factory, subscription_id=first_id
            )
            assert not late.proof.complete
            assert any(reason.endswith("lbx_scope_forbidden") for reason in late.proof.reasons)
        return result

    monkeypatch.setattr(purchase_inventory, "collect_inventory", concurrent_poll)
    if late_refusal:
        with pytest.raises(PurchaseRefused, match="billing_review_stale"):
            await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    else:
        result = await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
        assert result["outcome"] == "resolved"
    with factory() as db:
        case = db.get(ManualReviewCase, request.case_id)
        assert case.case_state == ("open" if late_refusal else "resolved")
        assert (case.resolution_document is None) == late_refusal
