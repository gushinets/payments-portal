"""A retained late-object review fences financial claims until audited closure."""

import asyncio
import json
from datetime import UTC, date, datetime, timedelta
import time
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition import purchase_inventory, purchase_recovery
from app.composition.billing_operator import resolve_review
from app.composition.purchase_recovery import recover_financial
from app.composition.purchases import advance_purchase
from app.composition.sources import SourceResources, source_resources
from app.core.settings import Settings
from app.domains.billing import terminal_resolution as terminal
from app.domains.billing.discovery import apply_inventory, persist_discoveries
from app.domains.billing.operator_contracts import LateSubscriptionPoint
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.paid_policy import CandidateConclusion
from app.domains.catalog.link_publication import publish_product_link
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import FinancialOperation, Purchase, PurchaseRefused
from app.domains.purchases.inventory_contracts import InventoryResult
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.financial import NewAgreement, Subscription
from app.models import (
    BillingProductAccessScope,
    CommercialProductHead,
    ExternalCreateOperationKind as Kind,
    ExternalSubscription,
    ManualReviewCase,
    PurchaseIntentState,
)
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.factories.reconciliation import agreement_factory, subscription_factory
from apps.api.tests.test_any709_step3_postgres import accept, TOKEN
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    synthetic_prepare,
)
from apps.api.tests.test_billing_scoped_inventory_postgres import conflict_case, inventory
from apps.api.tests.test_billing_worker_postgres import historical_link
from apps.api.tests.test_paid_access_rebase_postgres import claim_inventory, collect, effective, run_inventory
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario
from apps.api.tests.test_purchase_terminal_resolution_postgres import request, PRINCIPAL

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


async def test_open_late_review_survives_listing_omission(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="review-replacement")
    with pytest.raises(PurchaseRefused):
        await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
    with factory() as db:
        case = db.scalar(select(ManualReviewCase).where(ManualReviewCase.reason_code == terminal.LATE_REASON))
        assert case is not None and case.case_state == "open"
    assert (
        service.read_purchase(factory, replacement.user_id, replacement.id).state != PurchaseIntentState.MANUAL_REVIEW
    )
    # The list omits the known live object; its point endpoint still returns it.
    transport.hide.add("/subscriptions")
    clear = await inventory(sources, factory, replacement)
    assert clear.complete
    clear.require_clear(replacement)
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
    with factory() as db:
        case = db.scalar(select(ManualReviewCase).where(ManualReviewCase.reason_code == terminal.LATE_REASON))
        assert case is not None and case.case_state == "open"
    assert transport.creates("/agreements") == 0
    assert transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("include_inventory", [False, True])
async def test_fresh_late_review_invalidates_an_already_collected_inventory(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    include_inventory: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="review-race-replacement")
    old_agreements, old_subscriptions = transport.agreements[:], transport.subscriptions[:]
    transport.agreements.clear()
    transport.subscriptions.clear()
    clear = await inventory(sources, factory, replacement)
    assert clear.complete
    # The objects appear after the complete inventory read and before the claim.
    transport.agreements.extend(old_agreements)
    transport.subscriptions.extend(old_subscriptions)
    await recover_financial(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    with factory() as db:
        case = db.scalar(select(ManualReviewCase).where(ManualReviewCase.reason_code == terminal.LATE_REASON))
        assert case is not None and case.case_state == "open"
    op = next(item for item in replacement.operations if item.kind == Kind.AGREEMENT)
    command = NewAgreement(
        user_id=345, organization_id=21, agreement_number=op.key, create_date=datetime.now(UTC).date()
    )
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        financial.claim_financial(
            factory,
            replacement,
            op,
            command.request_document(),
            configuration=step1_settings(),
            token=TOKEN,
            inventory=clear if include_inventory else None,
        )
    assert service.read_purchase(factory, replacement.user_id, replacement.id).operations == replacement.operations


async def test_public_advance_checks_fresh_review_before_subscription_send(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="review-public-race")
    transport.hide.add("/subscriptions")
    entered, release = asyncio.Event(), asyncio.Event()
    prepare = sources.require_lbx().prepare_customer_create
    calls = 0

    async def pause_before_second_claim(*, budget: PreflightBudget) -> None:
        nonlocal calls
        await prepare(budget=budget)
        calls += 1
        if calls == 2:
            entered.set()
            await release.wait()

    monkeypatch.setattr(sources.require_lbx(), "prepare_customer_create", pause_before_second_claim)
    pending = asyncio.create_task(
        advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        # The new agreement is bound; the next side effect would be subscription CREATE.
        saved = service.read_purchase(factory, replacement.user_id, replacement.id)
        assert next(op for op in saved.operations if op.kind == Kind.AGREEMENT).bound_id == "457"
        transport.hide.clear()
        await recover_financial(
            sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
        )
        with factory() as db:
            cases = list(
                db.scalars(
                    select(ManualReviewCase).where(
                        ManualReviewCase.reason_code == terminal.LATE_REASON, ManualReviewCase.case_state == "open"
                    )
                )
            )
            assert cases
            proof = terminal.LateObjectEvidence.model_validate(cases[-1].evidence_document)
            assert proof.external_object_id in {"456", "567"}
        assert transport.creates("/subscriptions") == 0
        release.set()
        with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
            await pending
        assert transport.creates("/subscriptions") == 0
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


def _list_old_subscription_as_ended(sources: SourceResources, monkeypatch: pytest.MonkeyPatch) -> None:
    client = sources.require_lbx()
    discover = client.discover_subscriptions

    async def stale_list(
        *, user_id: int, budget: PreflightBudget, agreement_id: int | None = None
    ) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget, agreement_id=agreement_id)
        return tuple(row.model_copy(update={"state": 3}) if row.subscription_id == 567 else row for row in rows)

    monkeypatch.setattr(client, "discover_subscriptions", stale_list)


@pytest.mark.parametrize("stale_list", [False, True], ids=["live-list", "stale-ended-list"])
async def test_visible_late_object_blocks_public_advance(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    stale_list: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=not stale_list)
    if stale_list:
        transport.agreements[0]["close_date"] = datetime.now(UTC).date().isoformat()
        transport.subscriptions[0]["state"] = 3
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="review-visible")
    if stale_list:
        transport.agreements[0]["close_date"] = None
        transport.subscriptions[0]["state"] = 2
        _list_old_subscription_as_ended(sources, monkeypatch)
    with pytest.raises(PurchaseRefused):
        await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == 0
    assert transport.creates("/subscriptions") == 0
    assert any(req.url.path.endswith("/subscriptions/567") for req in transport.requests)
    with factory() as db:
        case = db.scalar(select(ManualReviewCase).where(ManualReviewCase.reason_code == terminal.LATE_REASON))
        assert case is not None and case.case_state == "open"


def _confirm_late_subscription(
    factory: sessionmaker[Session], purchase: Purchase, case_id: UUID, external_id: str
) -> None:
    command = request(factory, purchase, confirmed=True)
    operation_id = next(op.id for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    proofs = tuple(
        item.model_copy(
            update={"outcome": terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, "external_object_id": external_id}
        )
        if item.operation_id == operation_id
        else item
        for item in command.evidence.operations
    )
    command = command.model_copy(
        update={"case_id": case_id, "evidence": command.evidence.model_copy(update={"operations": proofs})}
    )
    terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)


async def test_last_review_closed_allows_original_replacement_to_continue(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, original = background_scenario
    factory = postgres_session_factory
    original = synthetic_prepare(factory, transport, original, uncertain=True)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, original, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="review-after-closure")
    await inventory(sources, factory, replacement)
    with factory() as db:
        cases = list(
            db.scalars(
                select(ManualReviewCase).where(
                    ManualReviewCase.reason_code == terminal.LATE_REASON, ManualReviewCase.case_state == "open"
                )
            )
        )
        assert len(cases) == 1
        case_id = cases[0].review_case_id
    transport.agreements[0]["close_date"] = datetime.now(UTC).date().isoformat()
    transport.subscriptions[0]["state"] = 3
    saved = service.read_purchase(factory, original.user_id, original.id)
    _confirm_late_subscription(factory, saved, case_id, "567")
    transport.hide.add("/subscriptions")
    linked = await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert linked.state == PurchaseIntentState.LINKED
    assert transport.creates("/agreements") == 1
    assert transport.creates("/subscriptions") == 1
    assert service.read_purchase(factory, original.user_id, original.id).operations == saved.operations


@pytest.mark.parametrize("mode", ["visible", "automatic_race", "operator_race", "existing_primary", "stale_ended_list"])
async def test_late_case_fences_first_primary_without_invalidating_linked_purchase(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    transport, sources, old = background_scenario
    factory = postgres_session_factory
    config = step1_settings(paid_access_clock_skew_seconds=10)
    old = synthetic_prepare(factory, transport, old, uncertain=mode != "stale_ended_list")
    if mode == "stale_ended_list":
        transport.agreements[0]["close_date"] = datetime.now(UTC).date().isoformat()
        transport.subscriptions[0]["state"] = 3
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="linked-before-late-case")
    transport.hide.add("/subscriptions")
    linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    transport.hide.clear()
    assert linked.state == PurchaseIntentState.LINKED
    old_point, new_point = transport.subscriptions
    if mode == "stale_ended_list":
        transport.agreements[0]["close_date"] = None
        old_point["state"] = 2
        _list_old_subscription_as_ended(sources, monkeypatch)
    new_point.update(
        state=2,
        subscription_start_date="2026-10-01",
        subscription_instance_start_date="2026-10-01",
        last_tariffication_period_start="2026-10-01",
        last_tariffication_period_end="2026-10-31",
    )
    with factory() as db:
        subscription_id = db.scalar(
            select(ExternalSubscription.subscription_id).where(
                ExternalSubscription.purchase_intent_id == replacement.id
            )
        )
    scenario = Scenario(factory, config, transport, sources, subscription_id)
    operation = next(item for item in old.operations if item.kind == Kind.SUBSCRIPTION)
    client = sources.require_lbx()
    discover = client.discover_subscriptions

    async def omitted(
        *, user_id: int, budget: PreflightBudget, agreement_id: int | None = None
    ) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget, agreement_id=agreement_id)
        return tuple(row for row in rows if row.subscription_id != 567)

    async def recover_old() -> None:
        await recover_financial(
            sources,
            config,
            factory=factory,
            user_id=old.user_id,
            purchase_id=old.id,
            operation_id=operation.id,
        )

    if mode == "automatic_race":
        with monkeypatch.context() as patch:
            patch.setattr(client, "discover_subscriptions", omitted)
            claim = claim_inventory(scenario)
            collected = await collect(scenario, claim)
            assert all(product.complete for product in collected.products)
            result = persist_discoveries(factory, claim, collected)
        await recover_old()
        apply_inventory(factory, claim, result, None, clock_skew_seconds=10)
    elif mode == "operator_race":
        with factory() as db:
            db.add(
                BillingProductAccessScope(
                    user_id=linked.user_id,
                    product_id=linked.accepted.selection.product_id,
                    primary_retired_at=datetime.now(UTC),
                )
            )
            db.commit()
        with monkeypatch.context() as patch:
            patch.setattr(client, "discover_subscriptions", omitted)
            await run_inventory(scenario)
        inspection = inspect_evidence(factory, config, linked.user_id, linked.id)
        operator_request = resolution_request(linked, inspection).model_copy(update={"resolution": "select-primary"})
        read_inventory = purchase_inventory.collect_inventory

        async def collect_then_recover(*args: Any, **kwargs: Any) -> InventoryResult:
            with monkeypatch.context() as patch:
                patch.setattr(client, "discover_subscriptions", omitted)
                collected = await read_inventory(*args, **kwargs)
            assert all(product.complete for product in collected.products)
            await recover_old()
            return collected

        with monkeypatch.context() as patch:
            patch.setattr(purchase_inventory, "collect_inventory", collect_then_recover)
            with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
                await resolve_review(sources, config, factory=factory, request=operator_request, principal=PRINCIPAL)
        with factory() as db:
            assert db.get(ManualReviewCase, operator_request.case_id).case_state == "open"
    else:
        if mode == "existing_primary":
            with monkeypatch.context() as patch:
                patch.setattr(client, "discover_subscriptions", omitted)
                await run_inventory(scenario)
            assert effective(factory)[1]["grants"]
        await run_inventory(scenario)
    assert service.read_purchase(factory, linked.user_id, linked.id).state == PurchaseIntentState.LINKED
    with factory() as db:
        case_id = db.scalar(
            select(ManualReviewCase.review_case_id).where(
                ManualReviewCase.reason_code == terminal.LATE_REASON,
                ManualReviewCase.case_state == "open",
            )
        )
        assert case_id is not None
        expected = subscription_id if mode == "existing_primary" else None
        assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) == expected
    assert bool(effective(factory)[1]["grants"]) is (mode == "existing_primary")

    old_point["state"] = 3
    command = request(factory, old, confirmed=True)
    proofs = tuple(
        terminal.OperationEvidence(
            operation_id=operation.id,
            outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
            external_object_id="567",
        )
        if item.operation_id == operation.id
        else item
        for item in command.evidence.operations
    )
    terminal.resolve_purchase(
        factory,
        config,
        command.model_copy(
            update={"case_id": case_id, "evidence": command.evidence.model_copy(update={"operations": proofs})}
        ),
        PRINCIPAL,
    )
    if mode == "operator_race":
        # A failed reconciliation leaves its finite claim for normal expiry.
        with factory() as db:
            db.get(ExternalSubscription, subscription_id).reconciliation_lease_expires_at = datetime.now(
                UTC
            ) - timedelta(seconds=1)
            db.commit()
        inspection = inspect_evidence(factory, config, linked.user_id, linked.id)
        operator_request = resolution_request(linked, inspection).model_copy(update={"resolution": "select-primary"})
        result = await resolve_review(sources, config, factory=factory, request=operator_request, principal=PRINCIPAL)
        assert result["outcome"] == "resolved"
    else:
        await run_inventory(scenario)
    with factory() as db:
        assert db.scalar(select(BillingProductAccessScope.primary_subscription_id)) == subscription_id
    assert effective(factory)[1]["grants"][0]["product_id"] == linked.accepted.selection.product_id


def _restore_proposal_offer(factory: sessionmaker[Session], config: Settings) -> None:
    # Restore the current offer while keeping both historical purchases' pins.
    for product, tariff_id in (("brief_decoder", 703), ("proposal_ai", 701)):
        with factory() as db:
            revision = db.scalar(
                select(CommercialProductHead.revision_number).where(CommercialProductHead.product_id == product)
            )
        publish_product_link(
            factory,
            evaluation=link_document(selection=link_selection(product_id=product, tariff_id=tariff_id)),
            expected_previous_revision=revision,
            deadline=time.monotonic() + 5,
            lock_timeout_seconds=1,
            provider_origin=config.lbx_provider_origin,
        )


def _activate_replacement(transport: PurchaseTransport, today: date) -> None:
    transport.subscriptions[-1].update(
        state=2,
        subscription_start_date=today.isoformat(),
        subscription_instance_start_date=today.isoformat(),
        last_tariffication_period_start=today.isoformat(),
        last_tariffication_period_end=(today + timedelta(days=30)).isoformat(),
    )


async def test_conflict_fences_first_primary_for_agreement_known_only_by_terminal_audit(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, old = background_scenario
    factory = postgres_session_factory
    config = step1_settings(paid_access_clock_skew_seconds=10)
    today = datetime.now(UTC).date()
    agreement_op = next(item for item in old.operations if item.kind == Kind.AGREEMENT)
    agreement = NewAgreement(user_id=345, organization_id=21, agreement_number=agreement_op.key, create_date=today)
    financial.claim_financial(
        factory, old, agreement_op, agreement.request_document(), configuration=config, token=TOKEN
    )
    agreement_point = {
        **agreement_factory().model_dump(),
        **agreement.request_document(),
        "close_date": today.isoformat(),
    }
    transport.agreements.append(agreement_point)
    old = service.read_purchase(factory, old.user_id, old.id)
    assert next(item for item in old.operations if item.id == agreement_op.id).bound_id is None
    command = request(factory, old, confirmed=True)
    operations = tuple(
        terminal.OperationEvidence(
            operation_id=agreement_op.id,
            outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
            external_object_id=str(agreement_point["agreement_id"]),
        )
        if item.operation_id == agreement_op.id
        else item
        for item in command.evidence.operations
    )
    terminal.resolve_purchase(
        factory,
        config,
        command.model_copy(update={"evidence": command.evidence.model_copy(update={"operations": operations})}),
        PRINCIPAL,
    )

    # The historical helper clones these source terms. Keep the seed terminal so
    # it cannot be a competitor during preparation of the replacement.
    seed = subscription_factory().model_dump()
    seed.update(state=3, total_price=100)
    seed["services"][0].update(multiplicator=1, price=100)
    transport.subscriptions.append(seed)
    sibling = historical_link(factory, old, transport, "brief_decoder", 1)
    sibling_point = transport.subscriptions[-1]
    terminal.resolve_purchase(factory, config, request(factory, sibling, confirmed=True), PRINCIPAL)
    transport.agreements[-1]["close_date"] = today.isoformat()

    _restore_proposal_offer(factory, config)
    replacement = await accept(sources, factory, key="after-agreement-attestation")
    replacement = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert replacement.state == PurchaseIntentState.LINKED
    _activate_replacement(transport, today)

    # Recover the sibling by its bound ID. Its fresh relationship points at the
    # attested agreement, while its tariff differs from the replacement's.
    agreement_point["close_date"] = None
    sibling_point.update(agreement_id=agreement_point["agreement_id"], tariff_id=702, state=2)
    sibling_op = next(item for item in sibling.operations if item.kind == Kind.SUBSCRIPTION)
    await recover_financial(
        sources, config, factory=factory, user_id=sibling.user_id, purchase_id=sibling.id, operation_id=sibling_op.id
    )
    [conflict] = [
        item
        for item in inspect_evidence(factory, config, sibling.user_id, sibling.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert conflict["late_object"]["observed_agreement_id"] == str(agreement_point["agreement_id"])
    assert conflict["late_object"]["observed_tariff_id"] != replacement.accepted.selection.tariff_id

    client = sources.require_lbx()
    discover = client.discover_subscriptions

    async def omit_historical(
        *, user_id: int, budget: PreflightBudget, agreement_id: int | None = None
    ) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget, agreement_id=agreement_id)
        return tuple(row for row in rows if row.subscription_id == transport.subscriptions[-1]["subscription_id"])

    monkeypatch.setattr(client, "discover_subscriptions", omit_historical)
    with factory() as db:
        subscription_id = db.scalar(
            select(ExternalSubscription.subscription_id).where(
                ExternalSubscription.purchase_intent_id == replacement.id
            )
        )
        assert subscription_id is not None
    scenario = Scenario(factory, config, transport, sources, subscription_id)
    claim = claim_inventory(scenario)
    result = await collect(scenario, claim)
    [product] = [item for item in result.products if item.product_id == replacement.accepted.selection.product_id]
    assert product.complete
    assert any(
        item.subscription_id == subscription_id and item.conclusion == CandidateConclusion.ELIGIBLE
        for item in product.candidates
    )
    result = persist_discoveries(factory, claim, result)
    apply_inventory(factory, claim, result, None, clock_skew_seconds=10)
    with factory() as db:
        scope = db.scalar(
            select(BillingProductAccessScope).where(BillingProductAccessScope.product_id == "proposal_ai")
        )
        assert scope is not None and scope.primary_subscription_id is None
    assert not any(grant["product_id"] == "proposal_ai" for grant in effective(factory)[1]["grants"])


@pytest.mark.parametrize("observation", ["completed-before", "same-relationship-after", "different-relationship-after"])
async def test_late_observation_order_relative_to_operator_confirmation(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    observation: str,
) -> None:
    transport, sources, original = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    old = synthetic_prepare(factory, transport, original, uncertain=False)
    agreement = transport.agreements[0]
    point = transport.subscriptions[0]
    agreement["close_date"] = datetime.now(UTC).date().isoformat()
    point["state"] = 3
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="after-overlapping-audit")
    operation = next(item for item in old.operations if item.kind == Kind.SUBSCRIPTION)
    transport.agreements.extend(
        dict(agreement, agreement_id=identity, agreement_number=f"foreign-{identity}", close_date=None)
        for identity in (998, 999)
    )
    point.update(agreement_id=998, tariff_id=701, state=2)

    async def recover() -> None:
        await recover_financial(
            sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id, operation_id=operation.id
        )

    await recover()
    [first] = [
        item
        for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert first["late_object"]["observed_agreement_id"] == "998"
    client = sources.require_lbx()
    get_subscription = client.get_subscription
    observe = purchase_recovery.observe_released_subscription
    entered, release = asyncio.Event(), asyncio.Event()

    async def hold_point_read(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        entered.set()
        await release.wait()
        return await get_subscription(subscription_id=subscription_id, budget=budget)

    async def hold_record(*args: Any, **kwargs: Any) -> terminal.LateObjectDisposition:
        entered.set()
        await release.wait()
        return await observe(*args, **kwargs)

    with monkeypatch.context() as patch:
        if observation == "completed-before":
            patch.setattr(purchase_recovery, "observe_released_subscription", hold_record)
        else:
            patch.setattr(client, "get_subscription", hold_point_read)
        pending = asyncio.create_task(recover())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            # Only GET-only recovery overlaps the confirmation. Financial
            # senders resume after the operator closes the exact case.
            point["state"] = 3
            command = request(factory, old, confirmed=True).model_copy(
                update={"case_id": UUID(first["review_case_id"])}
            )
            terminal.resolve_purchase(factory, config, command, PRINCIPAL)
            if observation == "different-relationship-after":
                point.update(agreement_id=999, tariff_id=702, state=2)
            elif observation == "same-relationship-after":
                point["state"] = 2
            release.set()
            await pending
        finally:
            release.set()
            await asyncio.gather(pending, return_exceptions=True)

    transport.hide.add("/subscriptions")
    if observation == "completed-before":
        resumed = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
        assert resumed.state == PurchaseIntentState.LINKED
        return

    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    [second] = [
        item
        for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert second["review_case_id"] != first["review_case_id"]
    assert second["late_object"]["observed_agreement_id"] == str(point["agreement_id"])
    assert second["late_object"]["observed_tariff_id"] == point["tariff_id"]


async def test_stale_discovery_owner_cannot_displace_the_point_owner_at_first_primary(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, original = background_scenario
    factory = postgres_session_factory
    config = step1_settings(paid_access_clock_skew_seconds=10)
    point_owner = synthetic_prepare(factory, transport, original, uncertain=True)
    listing_owner = historical_link(factory, point_owner, transport, "brief_decoder", 1)
    point, listed_point = transport.subscriptions
    point_agreement, listing_agreement = transport.agreements
    today = datetime.now(UTC).date()
    for agreement, subscription in zip(transport.agreements, transport.subscriptions, strict=True):
        agreement["close_date"] = today.isoformat()
        subscription["state"] = 3
    for old in (point_owner, listing_owner):
        terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    assert next(item for item in point_owner.operations if item.kind == Kind.SUBSCRIPTION).bound_id is None
    _restore_proposal_offer(factory, config)
    replacement = await accept(sources, factory, key="after-stale-owner-disproof")
    transport.hide.add("/subscriptions")
    replacement = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    transport.hide.clear()
    _activate_replacement(transport, today)

    point_agreement["close_date"] = None
    point.update(state=2, tariff_id=702)
    assert point["tariff_id"] != replacement.accepted.selection.tariff_id
    point_id = str(point["subscription_id"])
    list_op = next(item for item in listing_owner.operations if item.kind == Kind.SUBSCRIPTION)
    assert list_op.bound_id == str(listed_point["subscription_id"])
    # Retain a case attributable to an earlier stale list. The operator
    # correctly disproved this object for that purchase only.
    observed = datetime.now(UTC)
    terminal.record_late_object(
        factory,
        listing_owner,
        list_op.id,
        point_id,
        observed,
        read_finished_at=observed,
        subscription_point=LateSubscriptionPoint(
            str(point_agreement["agreement_id"]),
            point["tariff_id"],
        ),
    )
    [case] = [
        item
        for item in inspect_evidence(factory, config, listing_owner.user_id, listing_owner.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    command = request(factory, listing_owner, confirmed=True)
    proofs = tuple(
        item.model_copy(update={"unrelated_object_ids": (point_id,)}) if item.operation_id == list_op.id else item
        for item in command.evidence.operations
    )
    terminal.resolve_purchase(
        factory,
        config,
        command.model_copy(
            update={
                "case_id": UUID(case["review_case_id"]),
                "evidence": command.evidence.model_copy(update={"operations": proofs}),
            }
        ),
        PRINCIPAL,
    )

    client = sources.require_lbx()
    discover = client.discover_subscriptions

    async def stale_discovery(
        *, user_id: int, budget: PreflightBudget, agreement_id: int | None = None
    ) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget, agreement_id=agreement_id)
        return tuple(
            item.model_copy(update={"agreement_id": listing_agreement["agreement_id"]})
            if item.subscription_id == point["subscription_id"]
            else item
            for item in rows
        )

    monkeypatch.setattr(client, "discover_subscriptions", stale_discovery)
    with factory() as db:
        subscription_id = db.scalar(
            select(ExternalSubscription.subscription_id).where(
                ExternalSubscription.purchase_intent_id == replacement.id
            )
        )
        assert subscription_id is not None
    await run_inventory(Scenario(factory, config, transport, sources, subscription_id))
    assert not any(grant["product_id"] == "proposal_ai" for grant in effective(factory)[1]["grants"])
    [late] = [
        item
        for item in inspect_evidence(factory, config, point_owner.user_id, point_owner.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert late["late_object"]["external_object_id"] == point_id
    assert late["late_object"]["observed_agreement_id"] == str(point_agreement["agreement_id"])
    assert late["late_object"]["relationship_conflict"] is False


@pytest.mark.parametrize("receipt", [568, None], ids=["different-receipt", "two-point-confirmed-ids"])
async def test_confirmed_held_agreement_conflict_requires_review(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], receipt: int | None
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True, subscription_receipt=receipt)
    if receipt is None:
        transport.subscriptions.append({**transport.subscriptions[0], "subscription_id": 568})
    operation = next(item for item in purchase.operations if item.kind == Kind.SUBSCRIPTION)
    assert transport.subscriptions[0]["subscription_id"] == 567
    evidence = await conflict_case(sources, factory, transport, purchase)
    assert evidence["state"] == PurchaseIntentState.MANUAL_REVIEW
    assert [(item["reason"], item["scope_reference"]) for item in evidence["reviews"] if item["state"] == "open"] == [
        ("customer_inventory_conflict", str(operation.id))
    ]
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    saved_operation = next(item for item in saved.operations if item.id == operation.id)
    assert saved_operation.bound_id is None and saved_operation.candidate_id == (str(receipt) if receipt else None)
    assert all(call.method == "GET" for call in transport.requests)


@pytest.mark.parametrize(
    ("mode", "include_own", "entry"),
    [
        ("held-agreement-in-list", False, "inventory"),
        ("correct-agreement-in-list", False, "inventory"),
        ("different-create-receipt", False, "inventory"),
        ("existing-binding-review", False, "inventory"),
        ("same-create-receipt", False, "inventory"),
        ("wrong-held-seller", False, "inventory"),
        ("held-agreement-in-list", True, "inventory"),
        ("different-create-receipt", True, "inventory"),
        ("held-agreement-in-list", False, "advance"),
        ("different-create-receipt", False, "recover"),
        ("held-agreement-in-list", True, "recover"),
        ("different-create-receipt", True, "advance"),
        ("different-create-receipt", True, "recover-partial"),
    ],
)
async def test_late_original_is_reviewed_when_list_points_to_a_held_purchase(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    include_own: bool,
    entry: str,
) -> None:
    transport, sources, original = background_scenario
    factory = postgres_session_factory
    config = step1_settings(paid_access_clock_skew_seconds=10)
    old = synthetic_prepare(factory, transport, original, uncertain=True)
    claim_financial = financial.claim_financial
    subscription_claims: list[FinancialOperation] = []

    def capture_subscription_claim(*args: Any, **kwargs: Any) -> FinancialOperation:
        claim = claim_financial(*args, **kwargs)
        if claim.kind == Kind.SUBSCRIPTION:
            subscription_claims.append(claim)
        return claim

    with monkeypatch.context() as patch:
        patch.setattr(financial, "claim_financial", capture_subscription_claim)
        other = historical_link(factory, old, transport, "brief_decoder", 1, uncertain_subscription=True)
    [claim] = subscription_claims
    point, other_point = transport.subscriptions
    old_agreement, other_agreement = transport.agreements
    today = datetime.now(UTC).date()
    old_agreement["close_date"] = today.isoformat()
    point["state"] = 3
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)

    _restore_proposal_offer(factory, config)
    replacement = await accept(sources, factory, key="after-held-listing-owner")
    transport.hide.add("/subscriptions")
    replacement = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    transport.hide.clear()
    assert replacement.state == PurchaseIntentState.LINKED
    _activate_replacement(transport, today)
    old_agreement["close_date"] = None
    point.update(state=2, tariff_id=702)
    if mode == "different-create-receipt":
        financial.record_receipt(factory, other, claim, other_point["subscription_id"])
    elif mode == "same-create-receipt":
        financial.record_receipt(factory, other, claim, point["subscription_id"])
    elif mode == "wrong-held-seller":
        other_agreement["organization_id"] = 999
    elif mode == "existing-binding-review":
        financial.financial_pending(factory, other, claim, conflict=True)

    # The list places the late original under a held purchase's agreement.
    # Only the point read shows the original agreement and its actual owner.
    fail_own_point = False

    def stale_listing(req: httpx.Request) -> httpx.Response:
        if fail_own_point and req.url.path.endswith(f"/subscriptions/{other_point['subscription_id']}"):
            transport.requests.append(req)
            return transport.response({}, status=404)
        if req.method != "GET" or not req.url.path.endswith("/subscriptions"):
            return transport.respond(req)
        transport.requests.append(req)
        listed = [
            dict(row, agreement_id=other_agreement["agreement_id"])
            if row is point and mode != "correct-agreement-in-list"
            else row
            for row in transport.subscriptions
            if include_own or row is not other_point
        ]
        agreement_id = json.loads(req.content).get("agreement_id")
        return transport.response(
            [row for row in listed if agreement_id is None or row["agreement_id"] == agreement_id]
        )

    before_other = service.read_purchase(factory, other.user_id, other.id)
    before_reviews = inspect_evidence(factory, config, other.user_id, other.id)["reviews"]
    with factory() as db:
        subscription_id = db.scalar(
            select(ExternalSubscription.subscription_id).where(
                ExternalSubscription.purchase_intent_id == replacement.id
            )
        )
        assert subscription_id is not None
    first_read = len(transport.requests)
    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(stale_listing)
    ) as disputed:
        await run_inventory(Scenario(factory, config, transport, disputed, subscription_id))
        worker_calls = transport.requests[first_read:]
        if entry == "advance":
            await advance_purchase(disputed, config, factory=factory, token=TOKEN, purchase_id=other.id)
        elif entry.startswith("recover"):
            fail_own_point = entry == "recover-partial"
            await recover_financial(disputed, config, factory=factory, user_id=other.user_id, purchase_id=other.id)
    assert not any(grant["product_id"] == "proposal_ai" for grant in effective(factory)[1]["grants"])
    [late] = [
        item
        for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert late["late_object"]["external_object_id"] == str(point["subscription_id"])
    assert late["late_object"]["observed_agreement_id"] == str(old_agreement["agreement_id"])
    assert late["late_object"]["relationship_conflict"] is False
    assert sum(call.url.path.endswith(f"/subscriptions/{point['subscription_id']}") for call in worker_calls) == 1
    saved_other = service.read_purchase(factory, other.user_id, other.id)
    operation = next(item for item in saved_other.operations if item.id == claim.id)
    assert saved_other.held and operation.bound_id is None
    reviews = inspect_evidence(factory, config, other.user_id, other.id)["reviews"]
    if mode in {"same-create-receipt", "wrong-held-seller"}:
        assert saved_other.state == PurchaseIntentState.MANUAL_REVIEW
        assert [(item["reason"], item["scope_reference"]) for item in reviews if item["state"] == "open"] == [
            ("customer_inventory_conflict", str(claim.id))
        ]
    else:
        assert saved_other == before_other
        assert reviews == before_reviews

    if mode in {"held-agreement-in-list", "different-create-receipt"}:
        # Once the original case is resolved, the held purchase can recover its own object.
        old_agreement["close_date"] = today.isoformat()
        point["state"] = 3
        _confirm_late_subscription(factory, old, UUID(late["review_case_id"]), str(point["subscription_id"]))
        linked = await recover_financial(sources, config, factory=factory, user_id=other.user_id, purchase_id=other.id)
        assert linked.state == PurchaseIntentState.LINKED
        assert next(op.bound_id for op in linked.operations if op.id == claim.id) == str(other_point["subscription_id"])
    assert all(call.method == "GET" for call in transport.requests[first_read:])
