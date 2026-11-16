"""A retained late-object review fences financial claims until audited closure."""

import asyncio
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchase_recovery import recover_financial
from app.composition.purchases import advance_purchase
from app.domains.billing import terminal_resolution as terminal
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import PurchaseRefused
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.financial import NewAgreement
from app.models import ExternalCreateOperationKind as Kind, ManualReviewCase, PurchaseIntentState
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import accept, TOKEN
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    synthetic_prepare,
)
from apps.api.tests.test_billing_scoped_inventory_postgres import inventory
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


async def test_visible_late_object_blocks_public_advance(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="review-visible")
    with pytest.raises(PurchaseRefused):
        await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == 0
    assert transport.creates("/subscriptions") == 0
    with factory() as db:
        case = db.scalar(select(ManualReviewCase).where(ManualReviewCase.reason_code == terminal.LATE_REASON))
        assert case is not None and case.case_state == "open"


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
    command = request(factory, saved, confirmed=True)
    sub_id = next(op.id for op in saved.operations if op.kind == Kind.SUBSCRIPTION)
    operations = tuple(
        item.model_copy(
            update={"outcome": terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, "external_object_id": "567"}
        )
        if item.operation_id == sub_id
        else item
        for item in command.evidence.operations
    )
    command = command.model_copy(
        update={"case_id": case_id, "evidence": command.evidence.model_copy(update={"operations": operations})}
    )
    terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    transport.hide.add("/subscriptions")
    linked = await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert linked.state == PurchaseIntentState.LINKED
    assert transport.creates("/agreements") == 1
    assert transport.creates("/subscriptions") == 1
    assert service.read_purchase(factory, original.user_id, original.id).operations == saved.operations
