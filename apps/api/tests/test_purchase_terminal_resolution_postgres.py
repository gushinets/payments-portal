"""Real transactions, synthetic external requests and documented operator proof."""

import asyncio
import json
from contextlib import AbstractAsyncContextManager
from datetime import UTC, date, datetime, timedelta
from threading import Event, get_ident
from uuid import UUID, uuid4

import httpx
import pytest
from alembic import command as alembic_command
from alembic.util.exc import CommandError
from sqlalchemy import event, select, func, text
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from app.cli import billing_purchases
from app.composition.sources import SourceResources, source_resources
from app.core import database
from app.core.settings import Settings
from app.domains.billing import background_recovery, terminal_resolution as terminal
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.operator_contracts import LateSubscriptionPoint
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.operator_review import has_late_purchase_review_for_product
from app.domains.billing.reconciliation_contracts import IdentityProof
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase, PurchaseRefused, PurchaseInventoryIncomplete
from app.infrastructure.queries.billing_operator import has_open_purchase_review
from app.composition.backend_consumers import initialize_backend_consumers
from app.composition.billing_operator import resolve_review
from app.models import (
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as OperationState,
    ManualReviewCase,
    PurchaseIntentState,
    ExternalSubscription,
    PaidAccessState,
    PurchasedAllowance,
    BillingProductAccessScope,
    BillingStateObservation,
    BillingWorkItem,
    AccessInvalidationOutbox,
)
from app.composition.purchase_recovery import recover_financial
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.financial import Agreement, NewAgreement, Subscription
from app.integrations.lbx.errors import LbxResponseInvalid
from apps.api.tests.factories.billing_operator import resolution_request
from apps.api.tests.factories.reconciliation import agreement_factory
from apps.api.tests.support.postgres import alembic_test_config
from apps.api.tests.support.backend_consumers import backend_consumer, second_consumer
from apps.api.tests.test_billing_scoped_inventory_postgres import inventory
from apps.api.tests.test_paid_access_reconciliation_postgres import paid_source as paid_source, reconcile, Scenario
from apps.api.tests.test_paid_access_rebase_postgres import effective, run_inventory
from apps.api.tests.factories.purchase_terms import reviewed_meaning
from app.composition.purchases import review_purchase, confirm_purchase, advance_purchase
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_step3_postgres import accept, setup_purchase, TOKEN
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


async def _recover_from_cli(
    factory: sessionmaker[Session],
    purchase: Purchase,
    transport: PurchaseTransport,
    monkeypatch: pytest.MonkeyPatch,
    *,
    configuration: Settings | None = None,
) -> int:
    def synthetic_sources(configuration: Settings) -> AbstractAsyncContextManager[SourceResources]:
        return source_resources(
            configuration,
            kernel_transport=httpx.MockTransport(transport.kernel),
            lbx_transport=httpx.MockTransport(transport.respond),
        )

    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(billing_purchases, "source_resources", synthetic_sources)
    monkeypatch.setattr(billing_purchases, "resolve_operator_principal", lambda: PRINCIPAL)
    monkeypatch.setattr(billing_purchases, "Settings", lambda: configuration or step1_settings())
    return await run_in_threadpool(
        billing_purchases.main,
        ["recover", "--user-id", str(purchase.user_id), "--purchase-id", str(purchase.id)],
    )


@pytest.mark.parametrize(
    "http_status, attempts, failure_code, agreement_reads",
    [
        (None, 2, "lbx_response_invalid", 1),
        (401, 2, "lbx_attempts_exhausted", 1),
        (401, 3, "lbx_authentication_failed", 2),
        (403, 3, "lbx_scope_forbidden", 1),
    ],
)
async def test_public_recover_records_bound_subscription_conflict_when_agreement_read_fails(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    http_status: int | None,
    attempts: int,
    failure_code: str,
    agreement_reads: int,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    today = datetime.now(UTC).date()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    transport.agreements[0]["close_date"] = today.isoformat()
    transport.subscriptions[0]["state"] = 3
    terminal.resolve_purchase(factory, config, request(factory, purchase, confirmed=True), PRINCIPAL)

    transport.agreements.append(
        {**transport.agreements[0], "agreement_id": 999, "agreement_number": "another", "close_date": None}
    )
    transport.subscriptions[0].update(agreement_id=999, state=2)
    transport.hide.add("/subscriptions")
    respond = transport.respond

    def unavailable_original(http_request: httpx.Request) -> httpx.Response:
        if http_request.url.path.endswith("/agreements/456"):
            transport.requests.append(http_request)
            if http_status is not None:
                return httpx.Response(http_status, json={})
            return transport.response({})
        return respond(http_request)

    monkeypatch.setattr(transport, "respond", unavailable_original)
    start = len(transport.requests)
    assert (
        await _recover_from_cli(
            factory, purchase, transport, monkeypatch, configuration=step1_settings(lbx_max_get_attempts=attempts)
        )
        == 1
    )
    assert json.loads(capsys.readouterr().err) == {"detail": {"code": failure_code}}
    reads = [(item.method, item.url.path.removeprefix("/api/rest/v1")) for item in transport.requests[start:]]
    assert reads.count(("GET", "/agreements/456")) == agreement_reads
    assert reads.count(("GET", "/subscriptions/567")) == 1
    assert all(method == "GET" for method, _ in reads)
    [case] = [
        item
        for item in inspect_evidence(factory, config, purchase.user_id, purchase.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert case["late_object"]["external_object_id"] == "567"
    assert case["late_object"]["observed_agreement_id"] == "999"
    assert case["late_object"]["relationship_conflict"] is True

    replacement = await accept(sources, factory, key="replacement-after-recover-conflict")
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("live", [True, False], ids=["reopened", "still-terminal"])
async def test_public_recover_point_reads_agreement_known_only_by_terminal_audit(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    live: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    today = datetime.now(UTC).date()
    operation = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    agreement = NewAgreement(user_id=345, organization_id=21, agreement_number=operation.key, create_date=today)
    financial.claim_financial(
        factory, purchase, operation, agreement.request_document(), configuration=config, token=TOKEN
    )
    point = {**agreement_factory().model_dump(), **agreement.request_document(), "close_date": today.isoformat()}
    transport.agreements.append(point)
    purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    saved = next(op for op in purchase.operations if op.id == operation.id)
    assert saved.candidate_id is None and saved.bound_id is None
    command = request(factory, purchase, confirmed=True)
    operations = tuple(
        terminal.OperationEvidence(
            operation_id=operation.id,
            outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
            external_object_id="456",
        )
        if item.operation_id == operation.id
        else item
        for item in command.evidence.operations
    )
    command = command.model_copy(update={"evidence": command.evidence.model_copy(update={"operations": operations})})
    terminal.resolve_purchase(factory, config, command, PRINCIPAL)
    completed = service.read_purchase(factory, purchase.user_id, purchase.id)
    if live:
        point["close_date"] = None
    transport.hide.add("/agreements")

    start = len(transport.requests)
    assert await _recover_from_cli(factory, purchase, transport, monkeypatch) == 0
    reads = [(item.method, item.url.path.removeprefix("/api/rest/v1")) for item in transport.requests[start:]]
    assert reads.count(("GET", "/agreements/456")) == 1
    assert ("GET", "/agreements") not in reads
    assert all(method == "GET" for method, _ in reads)
    result = json.loads(capsys.readouterr().out)
    cases = [item for item in result["reviews"] if item["reason"] == terminal.LATE_REASON and item["state"] == "open"]
    assert service.read_purchase(factory, purchase.user_id, purchase.id) == completed
    replacement = await accept(sources, factory, key="replacement-after-audit-recover")
    if live:
        [case] = cases
        assert case["late_object"]["operation_id"] == str(operation.id)
        assert case["late_object"]["external_object_id"] == "456"
        with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    else:
        assert cases == []
        linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
        assert linked.state == PurchaseIntentState.LINKED
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


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


@pytest.mark.parametrize("entrypoint", ["by_id", "current"])
async def test_purchase_status_reads_state_and_hold_from_the_same_snapshot(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    migrated_database: Engine,
    entrypoint: str,
) -> None:
    _, _, purchase = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    command = request(factory, purchase)
    row_read, release_read = Event(), Event()
    reader_thread: int | None = None

    def after_purchase_select(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        if (
            get_ident() == reader_thread
            and statement.startswith("SELECT")
            and ("FROM purchase_intents" in statement or "FROM billing_purchase_scope_holds" in statement)
        ):
            row_read.set()
            assert release_read.wait(5)

    def read_status() -> Purchase | None:
        nonlocal reader_thread
        reader_thread = get_ident()
        if entrypoint == "current":
            return service.current_purchase(factory, config, TOKEN, purchase.accepted.selection.product_id)
        return service.read_purchase(factory, purchase.user_id, purchase.id)

    event.listen(migrated_database, "after_cursor_execute", after_purchase_select)
    reading = asyncio.create_task(run_in_threadpool(read_status))
    try:
        assert await run_in_threadpool(row_read.wait, 5)
        resolved = await run_in_threadpool(terminal.resolve_purchase, factory, config, command, PRINCIPAL)
        assert resolved.state == PurchaseIntentState.RESOLVED_NO_EXTERNAL_EFFECT
    finally:
        release_read.set()
        try:
            snapshot = await reading
        finally:
            event.remove(migrated_database, "after_cursor_execute", after_purchase_select)

    assert snapshot is not None and snapshot.state == PurchaseIntentState.CREATED and snapshot.held
    latest = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert latest.state == resolved.state and not latest.held
    assert service.current_purchase(factory, config, TOKEN, purchase.accepted.selection.product_id) is None


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


async def test_unrelated_receipt_requires_confirmation_and_preserves_history(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    op = next(item for item in purchase.operations if item.kind == Kind.AGREEMENT)
    sent = NewAgreement(user_id=345, organization_id=21, agreement_number=op.key, create_date=date(2026, 10, 27))
    claimed = financial.claim_financial(
        factory, purchase, op, sent.request_document(), configuration=step1_settings(), token=TOKEN
    )
    financial.record_receipt(factory, purchase, claimed, 456)
    transport.agreements.append({**agreement_factory().model_dump(), "user_id": 346, "agreement_number": "other"})
    purchase = await recover_financial(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    command = request(factory, purchase, confirmed=True)
    with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
        terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    document = command.model_dump(mode="json")
    next(item for item in document["evidence"]["operations"] if item["operation_id"] == str(op.id))[
        "unrelated_object_ids"
    ] = ["456"]
    command = terminal.TerminalRequest.model_validate(document)
    result = terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    assert result.state == PurchaseIntentState.RESOLVED_NO_EXTERNAL_EFFECT
    assert terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL).already_resolved
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert not saved.held
    assert next(item for item in saved.operations if item.id == op.id).candidate_id == "456"

    start = len(transport.requests)
    assert await _recover_from_cli(factory, saved, transport, monkeypatch) == 0
    reads = [(item.method, item.url.path.removeprefix("/api/rest/v1")) for item in transport.requests[start:]]
    assert ("GET", "/agreements") in reads and ("GET", "/agreements/456") not in reads
    assert all(method == "GET" for method, _ in reads)


@pytest.mark.parametrize("legacy_open_case", [False, True])
async def test_inventory_recognizes_late_original_and_operator_closes_case_without_old_hold(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], legacy_open_case: bool
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
        if legacy_open_case:
            case.evidence_document = old_read.model_dump(
                mode="json",
                exclude={
                    "observed_agreement_id",
                    "observed_tariff_id",
                    "relationship_conflict",
                    "latest_read_finished_at",
                },
            )
            db.commit()
    inspected = inspect_evidence(factory, step1_settings(), saved.user_id, saved.id)
    detail = next(item for item in inspected["reviews"] if item["review_case_id"] == str(case_id))["late_object"]
    assert detail["operation_id"] == str(old_read.operation_id)
    assert detail["external_object_id"] == "567"
    assert datetime.fromisoformat(detail["latest_read_started_at"]) == old_read.latest_read_started_at
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
    observation = LateSubscriptionPoint("456", 701, original_live_proven=True)
    read_started_at = datetime.now(UTC)
    read_finished_at = read_started_at + timedelta(microseconds=1)
    terminal.record_late_object(
        factory,
        saved,
        old_read.operation_id,
        "567",
        read_started_at,
        read_finished_at=read_finished_at,
        subscription_point=observation,
    )
    with pytest.raises(PurchaseRefused, match="purchase_resolution_stale"):
        terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    command = request(factory, saved, confirmed=True)
    command = command.model_copy(
        update={"case_id": case_id, "evidence": command.evidence.model_copy(update={"operations": proofs})}
    )
    premature = command.evidence.model_copy(
        update={"senders_stopped_at": read_started_at, "confirmed_at": read_started_at}
    )
    with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
        terminal.resolve_purchase(
            factory, step1_settings(), command.model_copy(update={"evidence": premature}), PRINCIPAL
        )
    terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    assert terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL).already_resolved
    terminal.record_late_object(
        factory,
        saved,
        old_read.operation_id,
        "567",
        old_read.read_started_at,
        read_finished_at=old_read.latest_observation_at,
        subscription_point=observation,
    )
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


async def test_exact_terminal_replay_ignores_unrelated_closed_history(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    _, _, purchase = background_scenario
    factory = postgres_session_factory
    command = request(factory, purchase)
    result = terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    with factory() as db:
        case = db.get(ManualReviewCase, result.review_case_id)
        db.add_all(
            [
                ManualReviewCase(
                    reason_code="other_review",
                    scope_kind=case.scope_kind,
                    scope_reference=case.scope_reference,
                    evidence_schema_version=case.evidence_schema_version,
                    evidence_document={},
                    case_state="resolved",
                    created_at=case.created_at + timedelta(seconds=index + 1),
                    resolved_at=case.resolved_at,
                    resolved_by_principal=PRINCIPAL,
                    resolution_schema_version=terminal.SCHEMA,
                    resolution_document=case.resolution_document,
                )
                for index in range(102)
            ]
        )
        db.commit()
    repeated = terminal.resolve_purchase(factory, step1_settings(), command, PRINCIPAL)
    assert repeated.already_resolved and repeated.review_case_id == result.review_case_id


def assert_terminal_downgrade_refused(factory: sessionmaker[Session], database_test_url: URL) -> None:
    versions = text("SELECT version_num FROM alembic_version")
    with factory() as db:
        previous_heads = set(db.scalars(versions))
    with alembic_test_config(database_test_url) as config, pytest.raises(CommandError, match="downgrade refused"):
        alembic_command.downgrade(config, "20261031_0006")
    with factory() as db:
        assert set(db.scalars(versions)) == previous_heads


@pytest.mark.parametrize("attested", [True, False], ids=["attested", "unrelated"])
async def test_late_unbound_agreement_review_and_downgrade(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], database_test_url: URL, attested: bool
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
        case = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == terminal.LATE_REASON)).one()
        assert case.case_state == "open"
        case_id = case.review_case_id
        object_id = terminal.LateObjectEvidence.model_validate(case.evidence_document).external_object_id
    assert all(req.method == "GET" for req in transport.requests[count:])
    assert_terminal_downgrade_refused(factory, database_test_url)

    command = request(factory, saved, confirmed=True)
    proof = (
        terminal.OperationEvidence(
            operation_id=op.id, outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, external_object_id=object_id
        )
        if attested
        else terminal.OperationEvidence(
            operation_id=op.id,
            outcome=terminal.TerminalEvidenceKind.NO_EXTERNAL_EFFECT,
            unrelated_object_ids=(object_id,),
        )
    )
    operations = tuple(proof if item.operation_id == op.id else item for item in command.evidence.operations)
    evidence = command.evidence.model_copy(update={"operations": operations})
    result = terminal.resolve_purchase(
        factory, step1_settings(), command.model_copy(update={"case_id": case_id, "evidence": evidence}), PRINCIPAL
    )
    assert result.state == PurchaseIntentState.RESOLVED_NO_EXTERNAL_EFFECT
    if attested:
        assert_terminal_downgrade_refused(factory, database_test_url)
    else:
        with alembic_test_config(database_test_url) as config:
            alembic_command.downgrade(config, "20261031_0006")


@pytest.mark.parametrize(
    ("later_state", "complete"),
    [
        pytest.param("active", True, id="active"),
        pytest.param("active", False, id="active-without-price"),
        pytest.param("ended", True, id="ended"),
    ],
)
async def test_initial_completion_checks_newer_subscription_read(
    paid_source: Scenario, later_state: str, complete: bool
) -> None:
    scenario = paid_source
    factory = scenario.factory
    with factory() as db:
        sub = db.get(ExternalSubscription, scenario.subscription_id)
        purchase = service.read_purchase(factory, sub.user_id, sub.purchase_intent_id)
    await reconcile(scenario)
    before = effective(factory)
    assert before[1]["grants"]
    original = request(factory, purchase, confirmed=True)
    if later_state == "ended":
        scenario.transport.subscriptions[0]["state"] = 3
    if not complete:
        scenario.transport.subscriptions[0].pop("total_price")
    read = await reconcile(scenario)
    assert read.proof.identity == IdentityProof.MATCH
    assert read.proof.lifecycle == later_state and read.proof.complete == complete
    assert read.proof.read_started_at > original.evidence.confirmed_at
    with pytest.raises(PurchaseRefused, match="purchase_resolution_stale"):
        terminal.resolve_purchase(factory, scenario.config, original, PRINCIPAL)
    refreshed = request(factory, purchase, confirmed=True)
    old_confirmation = refreshed.model_copy(update={"evidence": original.evidence})
    if later_state == "active":
        with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
            terminal.resolve_purchase(factory, scenario.config, old_confirmation, PRINCIPAL)
        assert service.read_purchase(factory, purchase.user_id, purchase.id).held
        assert effective(factory) == before
    else:
        refreshed = old_confirmation
    assert terminal.resolve_purchase(factory, scenario.config, refreshed, PRINCIPAL).state == (
        PurchaseIntentState.RESOLVED_EXTERNAL_TERMINAL
    )
    assert terminal.resolve_purchase(factory, scenario.config, refreshed, PRINCIPAL).already_resolved


@pytest.mark.parametrize("state", [2, -2, 3], ids=["active", "inactive", "ended"])
async def test_initial_completion_checks_newer_first_binding(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    state: int,
) -> None:
    transport, _, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    original = synthetic_prepare(factory, transport, purchase, uncertain=True, subscription_receipt=567)
    agreement, subscription = original.operations
    assert subscription.candidate_id == "567" and subscription.bound_id is None
    command = request(factory, original, confirmed=True)
    assert command.evidence.operations[0].operation_id == agreement.id
    proof = terminal.OperationEvidence(
        operation_id=subscription.id, outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, external_object_id="567"
    )
    first_confirmation = command.evidence.model_copy(update={"operations": (command.evidence.operations[0], proof)})

    transport.subscriptions[0]["state"] = state
    transport.hide.add("/subscriptions")
    assert await _recover_from_cli(factory, original, transport, monkeypatch) == 0
    linked = service.read_purchase(factory, original.user_id, original.id)
    assert linked.held and linked.operations[1].bound_id == "567"
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == original.id))
        [observation] = db.scalars(
            select(BillingStateObservation).where(BillingStateObservation.subscription_id == sub.subscription_id)
        ).all()
        assert observation.evidence_schema_version == "prepared-subscription:v1"
        assert observation.observed_at > first_confirmation.confirmed_at
        work = db.scalar(select(BillingWorkItem).where(BillingWorkItem.scope_reference == str(sub.subscription_id)))
        assert work is not None and work.work_state == "pending"
        work_id = work.work_item_id
    refreshed = request(factory, linked, confirmed=True)
    with_old_confirmation = refreshed.model_copy(update={"evidence": first_confirmation})
    if state != 3:
        with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
            terminal.resolve_purchase(factory, config, with_old_confirmation, PRINCIPAL)
        assert service.read_purchase(factory, original.user_id, original.id).held
        with factory() as db:
            assert db.get(BillingWorkItem, work_id).work_state == "pending"
    else:
        refreshed = with_old_confirmation
    assert terminal.resolve_purchase(factory, config, refreshed, PRINCIPAL).state == (
        PurchaseIntentState.RESOLVED_EXTERNAL_TERMINAL
    )
    assert terminal.resolve_purchase(factory, config, refreshed, PRINCIPAL).already_resolved


@pytest.mark.parametrize("prior_state", [OperationState.PENDING, OperationState.PROVEN_NOT_SENT])
async def test_terminal_completion_retains_unsent_proof_after_terms_change_review(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], prior_state: OperationState
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)

    def respond(message: httpx.Request) -> httpx.Response:
        if message.method == "POST" and message.url.path.endswith("/subscriptions"):
            assert prior_state == OperationState.PROVEN_NOT_SENT
            raise httpx.ConnectError("synthetic no-send", request=message)
        return transport.respond(message)

    if prior_state == OperationState.PENDING:
        transport.fail_create = "/agreements"
        transport.hide.add("/agreements")
    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        before = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert before.operations[1].state == prior_state
        transport.change_price()
        transport.hide.clear()
        reviewed = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
    agreement, subscription = reviewed.operations
    assert agreement.bound_id and subscription.state == OperationState.MANUAL_REVIEW
    assert reviewed.reason == "purchase_terms_changed_after_preparation"
    command = request(factory, reviewed, confirmed=True)
    agreement_proof = command.evidence.operations[0]
    assert agreement_proof.operation_id == agreement.id
    wrong = terminal.OperationEvidence(
        operation_id=subscription.id,
        outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
        external_object_id="99999",
    )
    wrong_command = command.model_copy(
        update={"evidence": command.evidence.model_copy(update={"operations": (agreement_proof, wrong)})}
    )
    with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
        terminal.resolve_purchase(factory, config, wrong_command, PRINCIPAL)
    assert service.read_purchase(factory, reviewed.user_id, reviewed.id).held
    unsent = terminal.OperationEvidence(operation_id=subscription.id, outcome=terminal.TerminalEvidenceKind.NOT_SENT)
    command = command.model_copy(
        update={"evidence": command.evidence.model_copy(update={"operations": (agreement_proof, unsent)})}
    )
    assert terminal.resolve_purchase(factory, config, command, PRINCIPAL).state == (
        PurchaseIntentState.RESOLVED_EXTERNAL_TERMINAL
    )
    assert not service.read_purchase(factory, reviewed.user_id, reviewed.id).held


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


@pytest.mark.parametrize(
    ("field", "value", "healthy"),
    [
        (None, None, True),
        ("organization_id", None, True),
        ("agreement_number", None, True),
        ("is_offer", None, True),
        ("organization_id", 999, False),
    ],
)
async def test_resolution_and_late_inventory_preserve_an_unrelated_product(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    field: str | None,
    value: int | None,
    healthy: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    sibling = historical_link(factory, purchase, transport, "brief_decoder", 1)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    if field:
        transport.agreements[0][field] = value
    result = await inventory(sources, factory, sibling)
    assert not result.complete  # New financial CREATE remains customer-wide strict.
    assert next(item for item in result.products if item.product_id == "brief_decoder").complete is healthy
    with pytest.raises(PurchaseInventoryIncomplete):
        result.require_clear(sibling)
    saved = service.read_purchase(factory, sibling.user_id, sibling.id)
    assert saved.held and saved.operations == sibling.operations
    with factory() as db:
        subscription_id = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.purchase_intent_id == sibling.id)
        )
        assert subscription_id is not None
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.user_id == sibling.user_id,
                    BillingProductAccessScope.product_id == "brief_decoder",
                )
            )
            is None
        )
    scenario = Scenario(factory, step1_settings(paid_access_clock_skew_seconds=10), transport, sources, subscription_id)
    await run_inventory(scenario)
    with factory() as db:
        primary = db.scalar(
            select(BillingProductAccessScope.primary_subscription_id).where(
                BillingProductAccessScope.user_id == sibling.user_id,
                BillingProductAccessScope.product_id == "brief_decoder",
            )
        )
        assert (primary == subscription_id) is healthy
        state = db.scalar(select(PaidAccessState).where(PaidAccessState.user_id == sibling.user_id))
        grants = state.effective_state_document["grants"] if state else []
        assert any(item["product_id"] == "brief_decoder" for item in grants) is healthy


async def test_late_subscription_relationship_is_recorded_consistently_by_cli_and_inventory(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, sources, old = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    old = synthetic_prepare(factory, transport, old, uncertain=False)
    sibling = historical_link(factory, old, transport, "brief_decoder", 1)
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    transport.subscriptions[0]["agreement_id"] = 457
    client = sources.require_lbx()
    get_agreement = client.get_agreement

    async def unavailable_original(*, agreement_id: int, budget: PreflightBudget) -> Agreement:
        if agreement_id == 456:
            raise LbxResponseInvalid()
        return await get_agreement(agreement_id=agreement_id, budget=budget)

    monkeypatch.setattr(client, "get_agreement", unavailable_original)
    await inventory(sources, factory, sibling)
    operation = next(op for op in old.operations if op.kind == Kind.SUBSCRIPTION)
    await recover_financial(
        sources,
        config,
        factory=factory,
        user_id=old.user_id,
        purchase_id=old.id,
        operation_id=operation.id,
    )
    inspection = inspect_evidence(factory, config, old.user_id, old.id)
    [case] = [item for item in inspection["reviews"] if item["reason"] == terminal.LATE_REASON]
    assert case["late_object"]["operation_id"] == str(operation.id)
    assert case["late_object"]["external_object_id"] == "567"
    assert case["late_object"]["observed_agreement_id"] == "457"
    with factory() as db:
        assert has_late_purchase_review_for_product(db, old.customer_id, "proposal_ai")
        assert has_late_purchase_review_for_product(db, old.customer_id, "brief_decoder")


@pytest.mark.parametrize("reader", ["recover", "inventory"])
async def test_bound_sibling_conflict_can_be_closed_without_claiming_its_subscription(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    reader: str,
) -> None:
    transport, sources, old = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    old = synthetic_prepare(factory, transport, old, uncertain=True)
    sibling = historical_link(factory, old, transport, "brief_decoder", 1)
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    old_operation = next(op for op in old.operations if op.kind == Kind.SUBSCRIPTION)
    foreign_sub = next(op.bound_id for op in sibling.operations if op.kind == Kind.SUBSCRIPTION)
    transport.subscriptions.pop(0)
    transport.subscriptions[0]["agreement_id"] = 456

    async def read() -> None:
        if reader == "recover":
            await recover_financial(
                sources,
                config,
                factory=factory,
                user_id=old.user_id,
                purchase_id=old.id,
                operation_id=old_operation.id,
            )
        else:
            await inventory(sources, factory, sibling)

    await read()
    [case] = [
        item
        for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert case["late_object"]["external_object_id"] == foreign_sub
    assert case["late_object"]["observed_agreement_id"] == "456"
    assert case["late_object"]["bound_to_another_operation"] is True
    command = request(factory, old, confirmed=True)

    def exact_case(evidence: terminal.OperationEvidence) -> terminal.TerminalRequest:
        operations = tuple(
            evidence if item.operation_id == old_operation.id else item for item in command.evidence.operations
        )
        return command.model_copy(
            update={
                "case_id": UUID(case["review_case_id"]),
                "evidence": command.evidence.model_copy(update={"operations": operations}),
            }
        )

    with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
        terminal.resolve_purchase(
            factory,
            config,
            exact_case(
                terminal.OperationEvidence(
                    operation_id=old_operation.id,
                    outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
                    external_object_id=foreign_sub,
                )
            ),
            PRINCIPAL,
        )
    terminal.resolve_purchase(
        factory,
        config,
        exact_case(
            terminal.OperationEvidence(
                operation_id=old_operation.id,
                outcome=terminal.TerminalEvidenceKind.NO_EXTERNAL_EFFECT,
                unrelated_object_ids=(foreign_sub,),
            )
        ),
        PRINCIPAL,
    )
    await read()
    with factory() as db:
        assert not has_open_purchase_review(db, old.customer_id, reason=terminal.LATE_REASON)

    # When LBX points to the retained owner again, a stale old-agreement listing
    # still cannot turn its permanent subscription into an old original.
    if reader == "inventory":
        transport.subscriptions[0]["agreement_id"] = 457
        client = sources.require_lbx()
        discover = client.discover_subscriptions

        async def stale_list(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
            rows = await discover(user_id=user_id, budget=budget)
            return tuple(row.model_copy(update={"agreement_id": 456}) for row in rows)

        monkeypatch.setattr(client, "discover_subscriptions", stale_list)
        await read()
        with factory() as db:
            assert not has_open_purchase_review(db, old.customer_id, reason=terminal.LATE_REASON)
    else:
        transport.subscriptions[0]["tariff_id"] = 702
        await read()
        [changed] = [
            item
            for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
            if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
        ]
        assert changed["late_object"]["observed_tariff_id"] == 702


@pytest.mark.parametrize("mode", ["visible", "omitted", "operator"])
async def test_open_historical_conflict_fences_the_observed_tariff_without_a_local_agreement(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    transport, sources, old = background_scenario
    factory = postgres_session_factory
    config = step1_settings(paid_access_clock_skew_seconds=10)
    old = synthetic_prepare(factory, transport, old, uncertain=False)
    sibling = historical_link(factory, old, transport, "brief_decoder", 1)
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    transport.agreements.append(dict(transport.agreements[0], agreement_id=999, agreement_number="other-agreement"))
    transport.subscriptions[0]["agreement_id"] = 999
    assert transport.subscriptions[0]["tariff_id"] == sibling.accepted.selection.tariff_id
    client = sources.require_lbx()
    discover = client.discover_subscriptions

    async def omit_old(
        *, user_id: int, budget: PreflightBudget, agreement_id: int | None = None
    ) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget, agreement_id=agreement_id)
        return tuple(row for row in rows if row.subscription_id != 567)

    with factory() as db:
        subscription_id = db.scalar(
            select(ExternalSubscription.subscription_id).where(ExternalSubscription.purchase_intent_id == sibling.id)
        )
        assert subscription_id is not None
        if mode == "operator":
            db.add(
                BillingProductAccessScope(
                    user_id=sibling.user_id,
                    product_id="brief_decoder",
                    primary_retired_at=datetime.now(UTC),
                )
            )
            db.commit()
    scenario = Scenario(factory, config, transport, sources, subscription_id)
    if mode == "operator":
        with monkeypatch.context() as patch:
            patch.setattr(client, "discover_subscriptions", omit_old)
            await run_inventory(scenario)

    result = await inventory(sources, factory, sibling)
    assert not next(product for product in result.products if product.product_id == "brief_decoder").complete
    [case] = [
        item
        for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert case["late_object"]["observed_agreement_id"] == "999"
    assert case["late_object"]["observed_tariff_id"] == sibling.accepted.selection.tariff_id
    if mode != "visible":
        monkeypatch.setattr(client, "discover_subscriptions", omit_old)
    if mode == "operator":
        inspection = inspect_evidence(factory, config, sibling.user_id, sibling.id)
        operator_request = resolution_request(sibling, inspection).model_copy(update={"resolution": "select-primary"})
        with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
            await resolve_review(sources, config, factory=factory, request=operator_request, principal=PRINCIPAL)
    else:
        await run_inventory(scenario)
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.product_id == "brief_decoder"
                )
            )
            is None
        )
    assert not any(item["product_id"] == "brief_decoder" for item in effective(factory)[1]["grants"])


@pytest.mark.parametrize("mode", ["inventory_agreement", "recover_agreement", "listing"])
async def test_permanent_owner_conflict_survives_missing_agreement_or_listing(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    transport, sources, original = background_scenario
    factory = postgres_session_factory
    config = step1_settings(paid_access_clock_skew_seconds=10)
    old = synthetic_prepare(factory, transport, original, uncertain=True)
    sibling = historical_link(factory, old, transport, "brief_decoder", 1)
    third = historical_link(factory, old, transport, "acceptance_builder", 2)
    tariff_id = third.accepted.selection.tariff_id
    assert tariff_id == sibling.accepted.selection.tariff_id
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    transport.subscriptions.pop(0)
    assert transport.subscriptions[0]["subscription_id"] == 568
    transport.subscriptions[0]["agreement_id"] = 456
    client = sources.require_lbx()
    get_agreement = client.get_agreement
    discover = client.discover_subscriptions

    async def unavailable_original(*, agreement_id: int, budget: PreflightBudget) -> Agreement:
        if agreement_id == 456:
            raise LbxResponseInvalid()
        return await get_agreement(agreement_id=agreement_id, budget=budget)

    async def omit_bound(
        *, user_id: int, budget: PreflightBudget, agreement_id: int | None = None
    ) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget, agreement_id=agreement_id)
        return tuple(row for row in rows if row.subscription_id != 568)

    if mode == "listing":
        monkeypatch.setattr(client, "discover_subscriptions", omit_bound)
    else:
        monkeypatch.setattr(client, "get_agreement", unavailable_original)
    if mode == "recover_agreement":
        operation = next(item for item in old.operations if item.kind == Kind.SUBSCRIPTION)
        await recover_financial(
            sources,
            config,
            factory=factory,
            user_id=old.user_id,
            purchase_id=old.id,
            operation_id=operation.id,
        )
    else:
        result = await inventory(sources, factory, third)
        assert not next(item for item in result.products if item.product_id == "acceptance_builder").complete

    [case] = [
        item
        for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert case["late_object"]["external_object_id"] == "568"
    assert case["late_object"]["observed_agreement_id"] == "456"
    assert case["late_object"]["observed_tariff_id"] == tariff_id
    assert case["late_object"]["bound_to_another_operation"] is True
    with factory() as db:
        subscription_id = db.scalar(
            select(ExternalSubscription.subscription_id).where(
                ExternalSubscription.purchase_intent_id == third.id,
            )
        )
        assert subscription_id is not None

    # The persisted conflict still applies on a subsequent attempt whose listing omits it.
    monkeypatch.setattr(client, "discover_subscriptions", omit_bound)
    await run_inventory(Scenario(factory, config, transport, sources, subscription_id))
    with factory() as db:
        assert (
            db.scalar(
                select(BillingProductAccessScope.primary_subscription_id).where(
                    BillingProductAccessScope.user_id == third.user_id,
                    BillingProductAccessScope.product_id == "acceptance_builder",
                )
            )
            is None
        )
    assert not any(item["product_id"] == "acceptance_builder" for item in effective(factory)[1]["grants"])


@pytest.mark.parametrize("legacy_audit", [False, True])
async def test_changed_tariff_after_audited_disproof_blocks_financial_create(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], legacy_audit: bool
) -> None:
    transport, sources, original = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    old = synthetic_prepare(factory, transport, original, uncertain=True)
    candidate = transport.subscriptions.pop()
    agreement = transport.agreements[0]
    agreement["close_date"] = "2026-11-17"
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="after-audited-disproof")
    operation = next(item for item in old.operations if item.kind == Kind.SUBSCRIPTION)
    assert operation.bound_id is None

    async def recover() -> None:
        await recover_financial(
            sources,
            config,
            factory=factory,
            user_id=old.user_id,
            purchase_id=old.id,
            operation_id=operation.id,
        )

    agreement["close_date"] = None
    transport.subscriptions.append(candidate)
    await recover()
    [case] = [
        item
        for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    agreement["close_date"] = "2026-11-17"
    if legacy_audit:
        with factory() as db:
            row = db.get(ManualReviewCase, UUID(case["review_case_id"]))
            row.evidence_document = terminal.LateObjectEvidence.model_validate(row.evidence_document).model_dump(
                mode="json",
                exclude={"observed_agreement_id", "observed_tariff_id", "relationship_conflict"},
            )
            db.commit()
    document = request(factory, old, confirmed=True).model_dump(mode="json")
    document["case_id"] = case["review_case_id"]
    proof = next(item for item in document["evidence"]["operations"] if item["operation_id"] == str(operation.id))
    proof["unrelated_object_ids"] = [str(candidate["subscription_id"])]
    resolution = terminal.TerminalRequest.model_validate(document)
    terminal.resolve_purchase(factory, config, resolution, PRINCIPAL)

    agreement["close_date"] = None
    if not legacy_audit:
        await recover()
        with factory() as db:
            assert not has_open_purchase_review(db, old.customer_id, reason=terminal.LATE_REASON)

    candidate["tariff_id"] = 702
    await recover()
    with pytest.raises(PurchaseRefused):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == 0
    assert transport.creates("/subscriptions") == 0
    [changed] = [
        item
        for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert changed["review_case_id"] != case["review_case_id"]
    assert changed["late_object"]["observed_tariff_id"] == 702
    assert terminal.resolve_purchase(factory, config, resolution, PRINCIPAL).already_resolved


async def test_positive_terminal_attestation_supersedes_earlier_disproof_for_create(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, original = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    old = synthetic_prepare(factory, transport, original, uncertain=True)
    candidate = transport.subscriptions.pop()
    agreement = transport.agreements[0]
    closed_on = datetime.now(UTC).date().isoformat()
    agreement["close_date"] = closed_on
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="after-original-confirmation")
    operation = next(item for item in old.operations if item.kind == Kind.SUBSCRIPTION)
    object_id = str(candidate["subscription_id"])

    async def observe_and_close(tariff_id: int, proof: terminal.OperationEvidence) -> terminal.TerminalRequest:
        agreement["close_date"] = None
        candidate.update(tariff_id=tariff_id, state=2)
        await recover_financial(
            sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id, operation_id=operation.id
        )
        [case] = [
            item
            for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
            if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
        ]
        assert case["late_object"]["observed_tariff_id"] == tariff_id
        agreement["close_date"] = closed_on
        candidate["state"] = 3
        command = request(factory, old, confirmed=True)
        operations = tuple(proof if item.operation_id == operation.id else item for item in command.evidence.operations)
        command = command.model_copy(
            update={
                "case_id": UUID(case["review_case_id"]),
                "evidence": command.evidence.model_copy(update={"operations": operations}),
            }
        )
        terminal.resolve_purchase(factory, config, command, PRINCIPAL)
        return command

    transport.subscriptions.append(candidate)
    old_tariff_id = candidate["tariff_id"]
    disproof = await observe_and_close(
        old_tariff_id,
        terminal.OperationEvidence(
            operation_id=operation.id,
            outcome=terminal.TerminalEvidenceKind.NO_EXTERNAL_EFFECT,
            unrelated_object_ids=(object_id,),
        ),
    )
    confirmation = await observe_and_close(
        old_tariff_id + 1,
        terminal.OperationEvidence(
            operation_id=operation.id,
            outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
            external_object_id=object_id,
        ),
    )
    assert disproof.case_id != confirmation.case_id
    agreement["close_date"] = None
    candidate.update(tariff_id=old_tariff_id, state=2)

    with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    [late] = [
        item
        for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
        if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
    ]
    assert late["late_object"]["external_object_id"] == object_id
    assert late["late_object"]["observed_tariff_id"] == old_tariff_id
    assert terminal.resolve_purchase(factory, config, disproof, PRINCIPAL).already_resolved
    assert terminal.resolve_purchase(factory, config, confirmation, PRINCIPAL).already_resolved


async def test_failed_point_read_of_exact_old_subscription_is_scoped_to_its_owner(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, old = background_scenario
    factory = postgres_session_factory
    old = synthetic_prepare(factory, transport, old, uncertain=False)
    sibling = historical_link(factory, old, transport, "brief_decoder", 1)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, old, confirmed=True), PRINCIPAL)
    client = sources.require_lbx()
    read = client.get_subscription

    async def invalid_old_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        if subscription_id == 567:
            raise LbxResponseInvalid()
        return await read(subscription_id=subscription_id, budget=budget)

    monkeypatch.setattr(client, "get_subscription", invalid_old_point)
    result = await inventory(sources, factory, sibling)
    assert not result.complete
    assert next(item for item in result.products if item.product_id == "brief_decoder").complete


async def test_ended_listing_candidates_use_the_existing_point_read_budget(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, sources, old = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    old = synthetic_prepare(factory, transport, old, uncertain=False)
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    original_point = transport.subscriptions[0]
    original_point["state"] = 3
    operation = next(op for op in old.operations if op.kind == Kind.SUBSCRIPTION)
    for value in range(568, 587):
        external_id = str(value)
        observed = datetime.now(UTC)
        terminal.record_late_object(factory, old, operation.id, external_id, observed, read_finished_at=observed)
        with factory() as db:
            case_id = db.scalar(
                select(ManualReviewCase.review_case_id).where(
                    ManualReviewCase.reason_code == terminal.LATE_REASON,
                    ManualReviewCase.case_state == "open",
                )
            )
        command = request(factory, old, confirmed=True)
        proofs = tuple(
            item.model_copy(update={"external_object_id": external_id}) if item.operation_id == operation.id else item
            for item in command.evidence.operations
        )
        terminal.resolve_purchase(
            factory,
            config,
            command.model_copy(
                update={
                    "case_id": case_id,
                    "evidence": command.evidence.model_copy(update={"operations": proofs}),
                }
            ),
            PRINCIPAL,
        )
        transport.subscriptions.append({**original_point, "subscription_id": value})
    replacement = await accept(sources, factory, key="ended-history-replacement")
    transport.requests.clear()
    result = await inventory(sources, factory, replacement)
    assert result.complete and result.products[0].complete
    assert sum("/subscriptions/" in item.url.path for item in transport.requests) == 20
    transport.subscriptions.append({**original_point, "subscription_id": 587})
    transport.requests.clear()
    with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert not any("/subscriptions/" in item.url.path for item in transport.requests)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


async def test_terminal_migration_refuses_downgrade_with_retained_external_history(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    database_test_url: URL,
) -> None:
    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    terminal.resolve_purchase(factory, step1_settings(), request(factory, purchase, confirmed=True), PRINCIPAL)
    assert_terminal_downgrade_refused(factory, database_test_url)
    assert not service.read_purchase(factory, purchase.user_id, purchase.id).held
