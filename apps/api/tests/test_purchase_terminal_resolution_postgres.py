"""Real transactions, synthetic external requests and documented operator proof."""

from datetime import UTC, date, datetime, timedelta
import asyncio
from threading import Event
from uuid import UUID, uuid4

import pytest
from alembic import command as alembic_command
from alembic.util.exc import CommandError
from sqlalchemy import select, func, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import Session, sessionmaker

from app.domains.billing import background_recovery, terminal_resolution as terminal
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase, PurchaseRefused
from app.composition.backend_consumers import initialize_backend_consumers
from app.models import (
    ExternalCreateOperationKind as Kind,
    ManualReviewCase,
    PurchaseIntentState,
    ExternalSubscription,
    PaidAccessState,
    PurchasedAllowance,
    BillingProductAccessScope,
    AccessInvalidationOutbox,
)
from app.composition.purchase_recovery import recover_financial
from app.integrations.lbx.financial import NewAgreement
from apps.api.tests.factories.reconciliation import agreement_factory
from apps.api.tests.support.postgres import alembic_test_config
from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer
from apps.api.tests.test_billing_scoped_inventory_postgres import inventory
from apps.api.tests.test_paid_access_reconciliation_postgres import paid_source as paid_source, reconcile, Scenario
from apps.api.tests.test_paid_access_rebase_postgres import run_inventory
from apps.api.tests.factories.purchase_terms import reviewed_meaning
from app.composition.purchases import review_purchase, confirm_purchase, advance_purchase
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import accept, TOKEN
from apps.api.tests.test_billing_worker_postgres import historical_link
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    original,
    synthetic_prepare,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
PRINCIPAL = "os-euid:1000"


def request(factory: sessionmaker[Session], purchase: Purchase, *, confirmed: bool = False) -> terminal.TerminalRequest:
    now = datetime.now(UTC)
    return terminal.TerminalRequest(
        user_id=purchase.user_id,
        purchase_id=purchase.id,
        expected_digest=inspect_evidence(factory, step1_settings(), purchase.user_id, purchase.id)[
            "expected_resolution_digest"
        ],
        reason="Customer requests a new attempt",
        reference="LBX support confirmation 821",
        evidence=terminal.TerminalEvidence(
            senders_stopped_at=now if confirmed else None,
            confirmed_at=now if confirmed else None,
            operations=tuple(
                terminal.OperationEvidence(
                    operation_id=op.id,
                    outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL
                    if op.bound_id
                    else (
                        terminal.TerminalEvidenceKind.NO_EXTERNAL_EFFECT
                        if op.deadline
                        else terminal.TerminalEvidenceKind.NOT_SENT
                    ),
                    external_object_id=op.bound_id,
                )
                for op in purchase.operations
            ),
        ),
    )


async def test_unsent_completion_audit_repeat_and_replacement(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    command = request(factory, purchase)
    before = tuple(original(factory, op.id) for op in purchase.operations)
    count = len(transport.requests)
    result = terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    assert result.state == PurchaseIntentState.RESOLVED_NO_EXTERNAL_EFFECT
    assert len(transport.requests) == count
    assert not service.read_purchase(factory, purchase.user_id, purchase.id).held
    replacement = await accept(sources, factory, key="replacement")
    repeated = terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    assert repeated.already_resolved and repeated.review_case_id == result.review_case_id
    assert service.read_purchase(factory, purchase.user_id, replacement.id).held
    with factory() as db:
        case = db.get(ManualReviewCase, result.review_case_id)
        assert case.resolved_by_principal == PRINCIPAL and case.case_state == "resolved"
        assert case.resolution_document["request"]["reference"] == command.reference
    assert tuple(original(factory, op.id) for op in purchase.operations) == before


async def test_unknown_requires_confirmation_after_stopping_senders(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    # Retained case timestamps need not reflect the order of locked writes.
    # Replay must return the command's own audit, not a related closed case.
    with factory() as db:
        db.add(
            ManualReviewCase(
                reason_code="external_create_outcome_unknown:subscription",
                scope_kind="create_operation",
                scope_reference=str(next(op.id for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)),
                evidence_schema_version="financial-review:v1",
                evidence_document={},
                case_state="open",
                created_at=datetime.now(UTC) + timedelta(minutes=1),
            )
        )
        db.commit()
    command = request(factory, purchase)
    with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
        terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    assert service.read_purchase(factory, purchase.user_id, purchase.id).held
    command = request(factory, purchase, confirmed=True)
    evidence = command.evidence.model_copy(
        update={"confirmed_at": command.evidence.senders_stopped_at - timedelta(seconds=1)}
    )
    with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
        terminal.resolve_purchase(
            factory, step1_settings(), command.model_copy(update={"evidence": evidence}), PRINCIPAL
        )
    result = terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    assert result.state == PurchaseIntentState.RESOLVED_EXTERNAL_TERMINAL
    assert (
        terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL).review_case_id == result.review_case_id
    )
    assert not service.read_purchase(factory, purchase.user_id, purchase.id).held
    assert (
        background_recovery._repair_operation(
            factory, step1_settings(), next(op.id for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
        )
        is False
    )
    with pytest.raises(PurchaseRefused, match="purchase_scope_released"):
        financial.financial_pending(
            factory, purchase, next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
        )


@pytest.mark.parametrize("change", ["stale", "foreign", "not_sent", "partial", "principal", "future"])
async def test_resolution_refuses_unsafe_or_unrelated_evidence(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], change: str
) -> None:
    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    command = request(factory, purchase, confirmed=True)
    principal = PRINCIPAL
    if change == "stale":
        command = command.model_copy(update={"expected_digest": "sha256:" + "0" * 64})
    elif change == "foreign":
        command = command.model_copy(update={"user_id": uuid4()})
    elif change in {"not_sent", "partial"}:
        kind = Kind.SUBSCRIPTION if change == "not_sent" else Kind.AGREEMENT
        op_id = next(op.id for op in purchase.operations if op.kind == kind)
        proofs = tuple(
            item.model_copy(update={"outcome": terminal.TerminalEvidenceKind.NOT_SENT, "external_object_id": None})
            if item.operation_id == op_id
            else item
            for item in command.evidence.operations
        )
        command = command.model_copy(update={"evidence": command.evidence.model_copy(update={"operations": proofs})})
    elif change == "future":
        command = command.model_copy(
            update={
                "evidence": command.evidence.model_copy(update={"confirmed_at": datetime.now(UTC) + timedelta(days=1)})
            }
        )
    else:
        principal = "not-an-operator"
    with pytest.raises(PurchaseRefused):
        terminal.resolve_purchase(factory, step1_settings(), command, principal)
    assert service.read_purchase(factory, purchase.user_id, purchase.id).held


async def test_resolution_rollback_keeps_hold_and_original_fences(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, purchase = background_scenario
    factory = postgres_session_factory

    def failed_writer(*args: object) -> int:
        raise RuntimeError("writer failed")

    monkeypatch.setattr(terminal, "reduce_paid_access", failed_writer)
    with pytest.raises(RuntimeError, match="writer failed"):
        terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase), PRINCIPAL)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.held and saved.operations == purchase.operations


async def test_inventory_recognizes_late_original_and_operator_closes_case_without_old_hold(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="replacement")
    count = len(transport.requests)
    result = await inventory(sources, factory, replacement)
    assert not result.complete
    assert all(req.method == "GET" for req in transport.requests[count:])
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert not saved.held and saved.state == PurchaseIntentState.RESOLVED_EXTERNAL_TERMINAL
    assert next(op for op in saved.operations if op.kind == Kind.SUBSCRIPTION).bound_id is None
    with factory() as db:
        case = db.scalar(select(ManualReviewCase).where(ManualReviewCase.reason_code == terminal.LATE_REASON))
        case_id, old_read = case.review_case_id, terminal.LateObjectEvidence.model_validate(case.evidence_document)
    command = request(factory, saved, confirmed=True)
    proofs = tuple(
        item.model_copy(
            update={"outcome": terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, "external_object_id": "567"}
        )
        if item.operation_id == old_read.operation_id
        else item
        for item in command.evidence.operations
    )
    command = command.model_copy(
        update={"case_id": case_id, "evidence": command.evidence.model_copy(update={"operations": proofs})}
    )
    # A newer contradictory read must invalidate an already prepared operator
    # decision, even when it reports the same object on the same open case.
    terminal.record_late_object(factory, saved, old_read.operation_id, "567", datetime.now(UTC))
    with pytest.raises(PurchaseRefused, match="purchase_resolution_stale"):
        terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    command = request(factory, saved, confirmed=True)
    command = command.model_copy(
        update={"case_id": case_id, "evidence": command.evidence.model_copy(update={"operations": proofs})}
    )
    terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    assert terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL).already_resolved
    terminal.record_late_object(factory, saved, old_read.operation_id, "567", old_read.read_started_at)
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ManualReviewCase)
                .where(ManualReviewCase.reason_code == terminal.LATE_REASON)
            )
            == 1
        )
        assert db.get(ManualReviewCase, case_id).case_state == "resolved"
    assert service.read_purchase(factory, replacement.user_id, replacement.id).held
    assert service.read_purchase(factory, replacement.user_id, replacement.id).operations == replacement.operations


async def test_late_unbound_agreement_has_read_only_supported_review_path(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    op = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    sent = NewAgreement(user_id=345, organization_id=21, agreement_number=op.key, create_date=date(2026, 10, 27))
    financial.claim_financial(
        factory, purchase, op, sent.request_document(), configuration=step1_settings(), token=TOKEN
    )
    purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    transport.agreements.append({**agreement_factory().model_dump(), **sent.request_document()})
    count = len(transport.requests)
    saved = await recover_financial(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    assert not saved.held and saved.state == PurchaseIntentState.RESOLVED_NO_EXTERNAL_EFFECT
    assert next(op for op in saved.operations if op.kind == Kind.AGREEMENT).bound_id is None
    with factory() as db:
        assert (
            db.scalar(select(ManualReviewCase).where(ManualReviewCase.reason_code == terminal.LATE_REASON)).case_state
            == "open"
        )
    assert all(req.method == "GET" for req in transport.requests[count:])


async def test_terminal_dependency_reduces_paid_access_and_retains_allowance_history(paid_source: Scenario) -> None:
    scenario = paid_source
    config = scenario.config.model_copy(update={"backend_consumers": (backend_consumer(), second_consumer())})
    initialize_backend_consumers(config, scenario.factory)
    await reconcile(scenario)
    with scenario.factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        purchase = service.read_purchase(scenario.factory, sub.user_id, sub.purchase_intent_id)
        state = db.scalar(select(PaidAccessState).where(PaidAccessState.user_id == sub.user_id))
        before_revision = state.access_revision
        assert state.effective_state_document["grants"]
        allowance_ids = tuple(db.scalars(select(PurchasedAllowance.allowance_id)))
        activations = db.scalars(
            text("""SELECT to_jsonb(o) FROM billing_state_observations o
            WHERE observation_kind = 'allowance_activation' ORDER BY observation_id""")
        ).all()
        assert activations
    terminal.resolve_purchase(scenario.factory, config, request(scenario.factory, purchase, confirmed=True), PRINCIPAL)
    with scenario.factory() as db:
        state = db.scalar(select(PaidAccessState).where(PaidAccessState.user_id == purchase.user_id))
        assert state.access_revision == before_revision + 1
        assert state.effective_state_document == {"grants": [], "allowances": []}
        assert tuple(db.scalars(select(PurchasedAllowance.allowance_id))) == allowance_ids
        assert (
            db.scalars(
                text("""SELECT to_jsonb(o) FROM billing_state_observations o
            WHERE observation_kind = 'allowance_activation' ORDER BY observation_id""")
            ).all()
            == activations
        )
        outboxes = db.scalars(select(AccessInvalidationOutbox)).all()
        assert {row.recipient_id for row in outboxes} == {"platform-kernel", "synthetic-summary"}
        assert all(row.pending_revision == state.access_revision for row in outboxes)
        scope = db.scalar(
            select(BillingProductAccessScope).where(BillingProductAccessScope.user_id == purchase.user_id)
        )
        assert scope.primary_subscription_id is None
    with pytest.raises(BillingRefused, match="purchase_scope_released"):
        await reconcile(scenario)

    # A new purchase must be able to become primary; the retained old source
    # must not remain an incomplete competitor or keep its old primary slot.
    scenario.transport.agreements[0]["close_date"] = "2026-10-28"
    link, offer, documents, terms = await review_purchase(
        scenario.sources,
        scenario.config,
        factory=scenario.factory,
        token=TOKEN,
        product_id=purchase.accepted.selection.product_id,
    )
    replacement = await confirm_purchase(
        scenario.sources,
        scenario.config,
        factory=scenario.factory,
        token=TOKEN,
        key="replacement-paid",
        meaning=reviewed_meaning(
            purchase.accepted.selection.product_id, link.mapping_revision_id, offer.fingerprint, documents, terms
        ),
    )
    await advance_purchase(
        scenario.sources, scenario.config, factory=scenario.factory, token=TOKEN, purchase_id=replacement.id
    )
    fields = {
        key: value
        for key, value in scenario.transport.subscriptions[0].items()
        if key not in {"subscription_id", "agreement_id", "outer_id"}
    }
    scenario.transport.subscriptions[-1].update(fields)
    await run_inventory(scenario)
    with scenario.factory() as db:
        state = db.scalar(select(PaidAccessState).where(PaidAccessState.user_id == purchase.user_id))
        assert state.effective_state_document["grants"]
        scope = db.scalar(
            select(BillingProductAccessScope).where(BillingProductAccessScope.user_id == purchase.user_id)
        )
        assert db.get(ExternalSubscription, scope.primary_subscription_id).purchase_intent_id == replacement.id


async def test_late_recovery_get_cannot_bind_after_completion_and_replacement(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    entered, release = asyncio.Event(), asyncio.Event()
    point = sources.require_lbx().get_subscription

    async def delayed_point(**kwargs: object) -> object:
        result = await point(**kwargs)
        entered.set()
        await release.wait()
        return result

    monkeypatch.setattr(sources.require_lbx(), "get_subscription", delayed_point)
    pending = asyncio.create_task(
        recover_financial(sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id)
    )
    try:
        await asyncio.wait_for(entered.wait(), 5)
        terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
        replacement = await accept(sources, factory, key="replacement-after-get")
        release.set()
        with pytest.raises(PurchaseRefused, match="purchase_scope_released"):
            await pending
        assert service.read_purchase(factory, replacement.user_id, replacement.id).held
        saved = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert not saved.held and next(op for op in saved.operations if op.kind == Kind.SUBSCRIPTION).bound_id is None
    finally:
        release.set()
        await asyncio.gather(pending, return_exceptions=True)


async def test_concurrent_identical_completion_has_one_audit(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, purchase = background_scenario
    factory = postgres_session_factory
    command = request(factory, purchase)
    entered, release = Event(), Event()
    reducer = terminal.reduce_paid_access

    def paused_reducer(db: Session, user_id: UUID) -> int:
        entered.set()
        assert release.wait(5)
        return reducer(db, user_id)

    monkeypatch.setattr(terminal, "reduce_paid_access", paused_reducer)
    pending = asyncio.create_task(
        asyncio.to_thread(terminal.resolve_purchase, factory, step1_settings(), command, PRINCIPAL)
    )
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        with pytest.raises(BillingRefused, match="billing_busy"):
            await asyncio.to_thread(terminal.resolve_purchase, factory, step1_settings(), command, PRINCIPAL)
    finally:
        release.set()
        results = await asyncio.gather(pending, return_exceptions=True)
    assert isinstance(results[0], terminal.TerminalResult)
    repeated = terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    assert repeated.already_resolved and repeated.review_case_id == results[0].review_case_id
    assert not service.read_purchase(factory, purchase.user_id, purchase.id).held
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 1


async def test_resolution_and_late_inventory_preserve_an_unrelated_product(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    result = await inventory(sources, factory, sibling)
    assert not result.complete  # New financial CREATE remains customer-wide strict.
    assert next(item for item in result.products if item.product_id == "brief_decoder").complete
    saved = service.read_purchase(factory, sibling.user_id, sibling.id)
    assert saved.held and saved.operations == sibling.operations


async def test_terminal_migration_refuses_downgrade_with_retained_external_history(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    postgres_engine: Engine,
    database_test_url: URL,
) -> None:
    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    with alembic_test_config(database_test_url) as config, pytest.raises(CommandError, match="downgrade refused"):
        alembic_command.downgrade(config, "20261031_0006")
    with postgres_engine.connect() as db:
        assert db.scalar(text("SELECT version_num FROM alembic_version")) == "20261117_821_merge"
    assert not service.read_purchase(factory, purchase.user_id, purchase.id).held
