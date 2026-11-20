"""Terminal evidence at the public recovery entry point and the first durable bind."""

import asyncio
import json
import time
from functools import partial
from threading import Event
from uuid import UUID
from concurrent.futures import Future
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy import select, text
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchase_recovery import recover_financial
from app.composition.purchases import advance_purchase, confirm_purchase
from app.composition.sources import SourceResources, source_resources
from app.domains.billing import customers, terminal_resolution as terminal
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.operator_contracts import LateSubscriptionPoint
from app.domains.billing.operator_review import digest, has_late_purchase_review_for_product
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase, PurchaseRefused
from app.infrastructure.queries import billing_operator
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.financial import NewAgreement, Subscription
from app.models import (
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalSubscription,
    ManualReviewCase,
    PurchaseIntentState,
)
from apps.api.tests.factories.original_operation import original_proof
from apps.api.tests.factories.reconciliation import agreement_factory
from apps.api.tests.test_any709_step2_postgres import seed
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_step3_postgres import TOKEN, accept
from apps.api.tests.test_billing_worker_postgres import historical_link
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    synthetic_prepare,
)
from apps.api.tests.test_billing_scoped_inventory_postgres import inventory
from apps.api.tests.test_purchase_terminal_resolution_postgres import PRINCIPAL, _recover_from_cli, request

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


def _confirmation(
    factory: sessionmaker[Session], purchase: Purchase, *proofs: terminal.OperationEvidence, case_id: UUID | None = None
) -> terminal.TerminalRequest:
    command = request(factory, purchase, confirmed=True)
    supplied = {item.operation_id: item for item in proofs}
    operations = tuple(supplied.get(item.operation_id, item) for item in command.evidence.operations)
    evidence = command.evidence.model_copy(update={"operations": operations})
    return command.model_copy(update={"evidence": evidence, "case_id": case_id})


def _close_uncertain_subscription(
    factory: sessionmaker[Session], transport: PurchaseTransport, purchase: Purchase, *, unrelated: bool = False
) -> Purchase:
    old = synthetic_prepare(
        factory, transport, purchase, uncertain=True, subscription_receipt=567 if unrelated else None
    )
    transport.agreements[0]["close_date"] = datetime.now(UTC).date().isoformat()
    transport.subscriptions[0]["state"] = 3
    op = next(item for item in old.operations if item.kind == Kind.SUBSCRIPTION)
    proof = (
        terminal.OperationEvidence(
            operation_id=op.id, outcome=terminal.TerminalEvidenceKind.NO_EXTERNAL_EFFECT, unrelated_object_ids=("567",)
        )
        if unrelated
        else terminal.OperationEvidence(
            operation_id=op.id, outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, external_object_id="567"
        )
    )
    terminal.resolve_purchase(factory, step1_settings(), _confirmation(factory, old, proof), PRINCIPAL)
    return service.read_purchase(factory, old.user_id, old.id)


def _unsent_subscription_case(
    factory: sessionmaker[Session], transport: PurchaseTransport, old: Purchase
) -> tuple[Purchase, UUID]:
    config = step1_settings()
    agreement, subscription = old.operations
    today = datetime.now(UTC).date()
    sent = NewAgreement(user_id=345, organization_id=21, agreement_number=agreement.key, create_date=today)
    financial.claim_financial(factory, old, agreement, sent.request_document(), configuration=config, token=TOKEN)
    transport.agreements.append(
        {**agreement_factory().model_dump(), **sent.request_document(), "close_date": today.isoformat()}
    )
    old = service.read_purchase(factory, old.user_id, old.id)
    agreement_proof = terminal.OperationEvidence(
        operation_id=agreement.id, outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, external_object_id="456"
    )
    terminal.resolve_purchase(factory, config, _confirmation(factory, old, agreement_proof), PRINCIPAL)
    old = service.read_purchase(factory, old.user_id, old.id)
    # Inventory later identifies a live subscription under the attested agreement.
    observed = datetime.now(UTC)
    terminal.record_late_object(
        factory,
        old,
        subscription.id,
        "567",
        observed,
        read_finished_at=observed,
        subscription_point=LateSubscriptionPoint("456", 701, original_live_proven=True),
    )
    [late] = [
        case for case in inspect_evidence(factory, config, old.user_id, old.id)["reviews"] if case["state"] == "open"
    ]
    return old, UUID(late["review_case_id"])


def _legacy_audit_only_purchase(
    factory: sessionmaker[Session], transport: PurchaseTransport, old: Purchase, *, second_agreement: bool
) -> Purchase:
    config = step1_settings()
    old, case_id = _unsent_subscription_case(factory, transport, old)
    agreement, subscription = old.operations
    agreement_proof = terminal.OperationEvidence(
        operation_id=agreement.id, outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, external_object_id="456"
    )
    sub_proof = terminal.OperationEvidence(
        operation_id=subscription.id, outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, external_object_id="567"
    )
    followup = _confirmation(factory, old, agreement_proof, sub_proof, case_id=case_id)
    # Older v1 records could attest an unsent operation. They remain ownership
    # evidence and their exact command must stay replayable after the rule change.
    with factory() as db:
        case = db.get(ManualReviewCase, case_id)
        case.case_state = "resolved"
        case.resolved_at = datetime.now(UTC)
        case.resolved_by_principal = PRINCIPAL
        case.resolution_schema_version = terminal.SCHEMA
        case.resolution_document = terminal.TerminalAudit(
            request=followup,
            command_digest=digest({"request": followup.model_dump(mode="json"), "principal": PRINCIPAL}),
            before_state=old.state,
            after_state=old.state,
        ).model_dump(mode="json")
        db.commit()
    assert terminal.resolve_purchase(factory, config, followup, PRINCIPAL).already_resolved
    if second_agreement:
        transport.agreements.append({**transport.agreements[0], "agreement_id": 457})
        observed = datetime.now(UTC)
        terminal.record_late_object(factory, old, agreement.id, "457", observed, read_finished_at=observed)
        [case] = [
            item
            for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
            if item["state"] == "open"
        ]
        second = agreement_proof.model_copy(update={"external_object_id": "457"})
        terminal.resolve_purchase(
            factory,
            config,
            _confirmation(factory, old, second, sub_proof, case_id=UUID(case["review_case_id"])),
            PRINCIPAL,
        )
        assert terminal.released_operation_objects(factory, old.id)[agreement.id].confirmed == {"456", "457"}
    return old


async def test_unsent_subscription_cannot_be_attested_after_release(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, _, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    old, case_id = _unsent_subscription_case(factory, transport, purchase)
    agreement, subscription = old.operations
    reviews = inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
    [release] = [review for review in reviews if review["reason"] == terminal.TERMINAL_REASON]
    original, unsent = (terminal.OperationEvidence.model_validate(item) for item in release["original_operations"])
    assert original.operation_id == agreement.id and original.external_object_id == "456"
    assert unsent.operation_id == subscription.id and unsent.outcome == terminal.TerminalEvidenceKind.NOT_SENT
    positive = terminal.OperationEvidence(
        operation_id=subscription.id, outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, external_object_id="567"
    )
    with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
        terminal.resolve_purchase(
            factory, config, _confirmation(factory, old, original, positive, case_id=case_id), PRINCIPAL
        )
    disproof = terminal.OperationEvidence(
        operation_id=subscription.id,
        outcome=terminal.TerminalEvidenceKind.NO_EXTERNAL_EFFECT,
        unrelated_object_ids=("567",),
    )
    resolution = _confirmation(factory, old, original, disproof, case_id=case_id)
    terminal.resolve_purchase(factory, config, resolution, PRINCIPAL)
    assert terminal.resolve_purchase(factory, config, resolution, PRINCIPAL).already_resolved
    assert not terminal.released_operation_objects(factory, old.id)[subscription.id].confirmed


async def test_agreement_case_cannot_attest_another_operation(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    old = synthetic_prepare(factory, transport, purchase, uncertain=True)
    agreement, subscription = old.operations
    transport.agreements[0]["close_date"] = datetime.now(UTC).date().isoformat()
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    transport.agreements[0]["close_date"] = None
    await recover_financial(
        sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id, operation_id=agreement.id
    )
    [case] = [
        item for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"] if item["state"] == "open"
    ]
    assert case["late_object"]["operation_id"] == str(agreement.id)
    case_id = UUID(case["review_case_id"])
    transport.agreements[0]["close_date"] = datetime.now(UTC).date().isoformat()
    positive = terminal.OperationEvidence(
        operation_id=subscription.id, outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, external_object_id="567"
    )
    with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
        terminal.resolve_purchase(factory, config, _confirmation(factory, old, positive, case_id=case_id), PRINCIPAL)
    resolution = _confirmation(factory, old, case_id=case_id)
    terminal.resolve_purchase(factory, config, resolution, PRINCIPAL)
    assert terminal.resolve_purchase(factory, config, resolution, PRINCIPAL).already_resolved
    assert not terminal.released_operation_objects(factory, old.id)[subscription.id].confirmed


async def test_disproved_live_subscription_still_blocks_same_tariff_until_ended(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    old = synthetic_prepare(factory, transport, purchase, uncertain=True)
    subscription = next(op for op in old.operations if op.kind == Kind.SUBSCRIPTION)
    candidate = transport.subscriptions.pop()
    transport.agreements[0]["close_date"] = datetime.now(UTC).date().isoformat()
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="after-disproved-live-subscription")
    transport.agreements[0]["close_date"] = None
    candidate.update(subscription_id=1567, outer_id="independent-subscription")
    transport.subscriptions.append(candidate)
    await recover_financial(
        sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id, operation_id=subscription.id
    )
    [case] = [
        item for item in inspect_evidence(factory, config, old.user_id, old.id)["reviews"] if item["state"] == "open"
    ]
    disproof = terminal.OperationEvidence(
        operation_id=subscription.id,
        outcome=terminal.TerminalEvidenceKind.NO_EXTERNAL_EFFECT,
        unrelated_object_ids=("1567",),
    )
    terminal.resolve_purchase(
        factory, config, _confirmation(factory, old, disproof, case_id=UUID(case["review_case_id"])), PRINCIPAL
    )
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    candidate["state"] = 3
    linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert linked.state == PurchaseIntentState.LINKED
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


@pytest.mark.parametrize("entrypoint", ["recover", "inventory"])
async def test_agreement_attested_during_point_read_does_not_create_relationship_conflict(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    entrypoint: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    old = _legacy_audit_only_purchase(factory, transport, purchase, second_agreement=False)
    agreement, subscription = old.operations
    second_agreement = {**transport.agreements[0], "agreement_id": 457, "close_date": None}
    transport.agreements.append(second_agreement)
    observed = datetime.now(UTC)
    terminal.record_late_object(factory, old, agreement.id, "457", observed, read_finished_at=observed)
    [unresolved] = [
        case for case in inspect_evidence(factory, config, old.user_id, old.id)["reviews"] if case["state"] == "open"
    ]
    transport.subscriptions.append(
        {"subscription_id": 567, "agreement_id": 457, "tariff_id": 701, "state": 3, "current_blocking": 0}
    )
    replacement = await accept(sources, factory, key="replacement-after-concurrent-attestation")
    client = sources.require_lbx()
    get_subscription = client.get_subscription
    entered, release = asyncio.Event(), asyncio.Event()

    async def wait_before_point(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
        assert subscription_id == 567
        entered.set()
        await release.wait()
        return await get_subscription(subscription_id=subscription_id, budget=budget)

    async def observe_subscription() -> None:
        if entrypoint == "recover":
            await recover_financial(sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id)
        else:
            await inventory(sources, factory, replacement)

    with monkeypatch.context() as patch:
        patch.setattr(client, "get_subscription", wait_before_point)
        pending = asyncio.create_task(observe_subscription())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            second_agreement["close_date"] = transport.agreements[0]["close_date"]
            confirmation = _confirmation(
                factory,
                old,
                terminal.OperationEvidence(
                    operation_id=agreement.id,
                    outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
                    external_object_id="457",
                ),
                terminal.OperationEvidence(
                    operation_id=subscription.id,
                    outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL,
                    external_object_id="567",
                ),
                case_id=UUID(unresolved["review_case_id"]),
            )
            terminal.resolve_purchase(factory, config, confirmation, PRINCIPAL)
        finally:
            release.set()
            await pending

    # A fresh recover also sees both agreements, but cannot clear a false durable case.
    await recover_financial(sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id)
    assert all(case["state"] != "open" for case in inspect_evidence(factory, config, old.user_id, old.id)["reviews"])
    linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert linked.state == PurchaseIntentState.LINKED


@pytest.mark.parametrize("second_agreement", [False, True], ids=["one-agreement", "two-agreements"])
async def test_public_recover_reads_subscription_attested_after_the_initial_release(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    second_agreement: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    old = _legacy_audit_only_purchase(factory, transport, purchase, second_agreement=second_agreement)
    replacement = await accept(sources, factory, key="replacement-after-recover")
    transport.subscriptions.append({"subscription_id": 567, "agreement_id": 999, "tariff_id": 701})
    transport.hide.update({"/agreements", "/subscriptions"})
    start = len(transport.requests)
    assert await _recover_from_cli(factory, old, transport, monkeypatch) == 0
    reads = [(item.method, item.url.path.removeprefix("/api/rest/v1")) for item in transport.requests[start:]]
    assert ("GET", "/subscriptions/567") in reads and all(method == "GET" for method, _ in reads)
    [reopened] = [case for case in json.loads(capsys.readouterr().out)["reviews"] if case["state"] == "open"]
    assert reopened["late_object"]["observed_agreement_id"] == "999"
    assert reopened["late_object"]["external_object_id"] == "567" and reopened["late_object"]["relationship_conflict"]
    assert service.read_purchase(factory, old.user_id, old.id) == old
    for _ in range(2):
        with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
            await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("reopen_agreement", [False, True])
async def test_recover_records_audit_owned_subscription_conflict_on_the_original_purchase(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reopen_agreement: bool,
) -> None:
    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    original = _close_uncertain_subscription(factory, transport, purchase)
    subscription = next(op for op in original.operations if op.kind == Kind.SUBSCRIPTION)
    assert subscription.bound_id is None
    assert terminal.released_operation_objects(factory, original.id)[subscription.id].confirmed == {"567"}

    other = historical_link(factory, original, transport, "brief_decoder", 1, uncertain_subscription=True)
    transport.subscriptions[:] = [item for item in transport.subscriptions if item["subscription_id"] == 567]
    other_agreement = next(item for item in transport.agreements if item["agreement_id"] == 457)
    other_agreement["close_date"] = datetime.now(UTC).date().isoformat()
    terminal.resolve_purchase(factory, config, request(factory, other, confirmed=True), PRINCIPAL)
    if reopen_agreement:
        other_agreement["close_date"] = None
    transport.subscriptions[0].update(agreement_id=457, state=2)

    assert await _recover_from_cli(factory, other, transport, monkeypatch) == 0
    [conflict] = [
        case
        for case in inspect_evidence(factory, config, original.user_id, original.id)["reviews"]
        if case["state"] == "open"
    ]
    assert conflict["late_object"]["operation_id"] == str(subscription.id)
    assert conflict["late_object"]["external_object_id"] == "567"
    assert conflict["late_object"]["observed_agreement_id"] == "457"
    assert conflict["late_object"]["relationship_conflict"] is True
    output = json.loads(capsys.readouterr().out)
    assert output["purchase_intent_id"] == str(other.id)
    assert output["related_late_reviews"] == [
        {"purchase_intent_id": str(original.id), "review_case_id": conflict["review_case_id"]}
    ]
    if not reopen_agreement:
        assert not any(case["state"] == "open" for case in output["reviews"])
    assert all(
        case.get("late_object", {}).get("external_object_id") != "567"
        for case in inspect_evidence(factory, config, other.user_id, other.id)["reviews"]
    )
    with factory() as db:
        for product_id, tariff_id in (("proposal_ai", 702), ("brief_decoder", 701)):
            assert has_late_purchase_review_for_product(db, original.customer_id, product_id, tariff_id=tariff_id)
    assert await _recover_from_cli(factory, other, transport, monkeypatch) == 0
    assert json.loads(capsys.readouterr().out)["related_late_reviews"] == output["related_late_reviews"]
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("second_agreement", [False, True], ids=["one-agreement", "two-agreements"])
async def test_advance_retains_audited_subscription_conflict_after_listing_omission(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    second_agreement: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    old = _legacy_audit_only_purchase(factory, transport, purchase, second_agreement=second_agreement)
    assert all(op.bound_id is None for op in old.operations)
    replacement = await accept(sources, factory, key="replacement-after-audit")
    transport.subscriptions.append({"subscription_id": 567, "agreement_id": 999, "tariff_id": 701})

    start = len(transport.requests)
    with pytest.raises(PurchaseRefused):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert any(
        req.method == "GET" and req.url.path.endswith("/subscriptions/567") for req in transport.requests[start:]
    )
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    open_cases = [
        case for case in inspect_evidence(factory, config, old.user_id, old.id)["reviews"] if case["state"] == "open"
    ]

    transport.hide.add("/subscriptions")
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    [case] = open_cases
    assert case["reason"] == terminal.LATE_REASON
    assert case["late_object"]["external_object_id"] == "567"
    assert case["late_object"]["observed_agreement_id"] == "999"
    assert case["late_object"]["relationship_conflict"] is True


@pytest.mark.parametrize("entrypoint", ["advance", "recover"])
async def test_stale_listing_of_unrelated_subscription_does_not_create_late_review(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    entrypoint: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    old = synthetic_prepare(factory, transport, purchase, uncertain=True)
    transport.agreements[0]["close_date"] = datetime.now(UTC).date().isoformat()
    terminal.resolve_purchase(factory, config, request(factory, old, confirmed=True), PRINCIPAL)
    replacement = await accept(sources, factory, key="replacement-after-stale-list")
    transport.agreements.append(
        {**transport.agreements[0], "agreement_id": 990, "agreement_number": "another-agreement", "close_date": None}
    )
    foreign = dict(
        transport.subscriptions[0],
        subscription_id=989,
        agreement_id=990,
        tariff_id=988,
        outer_id="another-subscription",
    )
    transport.subscriptions[:] = [foreign]
    respond = transport.respond

    def stale_list(req: httpx.Request) -> httpx.Response:
        if req.method == "GET" and req.url.path.endswith("/subscriptions"):
            filters = json.loads(req.content)
            if filters.get("agreement_id") in {None, 456}:
                transport.requests.append(req)
                return transport.response([dict(foreign, agreement_id=456)])
        return respond(req)

    start = len(transport.requests)
    if entrypoint == "recover":
        with monkeypatch.context() as patch:
            patch.setattr(transport, "respond", stale_list)
            exit_code = await _recover_from_cli(factory, old, transport, patch)
    else:
        async with source_resources(
            config,
            kernel_transport=httpx.MockTransport(transport.kernel),
            lbx_transport=httpx.MockTransport(stale_list),
        ) as stale_sources:
            with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
                await advance_purchase(stale_sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert any(req.url.path.endswith("/subscriptions/989") for req in transport.requests[start:])
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    assert all(
        case["reason"] != terminal.LATE_REASON
        for case in inspect_evidence(factory, config, old.user_id, old.id)["reviews"]
    )
    if entrypoint == "recover":
        assert exit_code == 1
        assert json.loads(capsys.readouterr().err)["detail"]["code"] == "lbx_scope_mismatch"

    linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert linked.state == PurchaseIntentState.LINKED
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


@pytest.mark.parametrize("observed_agreement", [456, 457])
async def test_attested_subscription_under_either_closed_agreement_allows_replacement(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    observed_agreement: int,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    old = _legacy_audit_only_purchase(factory, transport, purchase, second_agreement=True)
    transport.subscriptions.append({"subscription_id": 567, "agreement_id": observed_agreement, "tariff_id": 701})
    assert await _recover_from_cli(factory, old, transport, monkeypatch) == 0
    assert not any(
        case["state"] == "open" for case in inspect_evidence(factory, step1_settings(), old.user_id, old.id)["reviews"]
    )
    replacement = await accept(sources, factory, key="replacement-after-closed-agreements")
    linked = await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert linked.state == PurchaseIntentState.LINKED
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


@pytest.mark.parametrize("unrelated", [False, True], ids=["audit-confirms", "audit-disproves"])
async def test_released_recover_obeys_audited_subscription_ownership(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    unrelated: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    old = _close_uncertain_subscription(factory, transport, purchase, unrelated=unrelated)
    transport.subscriptions[0].update(agreement_id=999, state=2)
    transport.hide.add("/subscriptions")
    start = len(transport.requests)
    assert await _recover_from_cli(factory, old, transport, monkeypatch) == 0
    reads = transport.requests[start:]
    assert all(item.method == "GET" for item in reads)
    assert sum(item.url.path.endswith("/subscriptions/567") for item in reads) == (0 if unrelated else 1)
    cases = [
        case
        for case in json.loads(capsys.readouterr().out)["reviews"]
        if case["reason"] == terminal.LATE_REASON and case["state"] == "open"
    ]
    assert service.read_purchase(factory, old.user_id, old.id) == old
    replacement = await accept(sources, factory, key="after-audited-subscription")
    if unrelated:
        assert not cases
        saved = await advance_purchase(
            sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id
        )
        assert saved.state == PurchaseIntentState.LINKED
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
        # Fresh listing and point now agree on the original, reopened agreement.
        transport.agreements[0]["close_date"] = None
        transport.subscriptions[0]["agreement_id"] = 456
        transport.hide.clear()
        assert await _recover_from_cli(factory, old, transport, monkeypatch) == 0
        opened_ids = {
            item["late_object"]["external_object_id"]
            for item in json.loads(capsys.readouterr().out)["reviews"]
            if item["reason"] == terminal.LATE_REASON and item["state"] == "open"
        }
        assert opened_ids == {"456", "567"}
    else:
        [case] = cases
        assert case["late_object"]["external_object_id"] == "567"
        assert case["late_object"]["observed_agreement_id"] == "999"
        with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
            await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("foreign", [True, False], ids=["attested-original", "genuine-replacement"])
async def test_replacement_recover_checks_terminal_owner_at_first_bind(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    foreign: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    old = _close_uncertain_subscription(factory, transport, purchase)
    replacement = await accept(sources, factory, key="recover-replacement")
    transport.hide.add("/subscriptions")
    transport.fail_create = "/subscriptions"
    await advance_purchase(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/subscriptions") == transport.creates("/agreements") == 1
    transport.hide.clear()
    old_point, new_point = transport.subscriptions
    assert (old_point["subscription_id"], new_point["subscription_id"]) == (567, 568)
    if foreign:
        # Discovery and the authenticated point now agree on the wrong object's origin.
        old_point.update(agreement_id=new_point["agreement_id"], state=new_point["state"])
        respond = transport.respond

        def omit_genuine_subscription(item: httpx.Request) -> httpx.Response:
            if item.method == "GET" and item.url.path.endswith("/subscriptions"):
                transport.requests.append(item)
                return transport.response([old_point])
            return respond(item)

        monkeypatch.setattr(transport, "respond", omit_genuine_subscription)
    start = len(transport.requests)
    result = await _recover_from_cli(factory, replacement, transport, monkeypatch)
    saved = service.read_purchase(factory, replacement.user_id, replacement.id)
    op = next(item for item in saved.operations if item.kind == Kind.SUBSCRIPTION)
    with factory() as db:
        external_id = db.scalar(
            select(ExternalSubscription.external_subscription_id).where(
                ExternalSubscription.purchase_intent_id == replacement.id
            )
        )
    assert op.bound_id == external_id == (None if foreign else "568")
    assert service.read_purchase(factory, old.user_id, old.id) == old
    reads = transport.requests[start:]
    assert all(item.method == "GET" for item in reads)
    expected_point = "/subscriptions/567" if foreign else "/subscriptions/568"
    assert any(item.url.path.endswith(expected_point) for item in reads)
    if foreign:
        assert result == 1 and json.loads(capsys.readouterr().err)["detail"]["code"] == "purchase_review_required"
        assert saved.held and saved.state == PurchaseIntentState.MANUAL_REVIEW
        [case] = [
            item
            for item in inspect_evidence(factory, step1_settings(), saved.user_id, saved.id)["reviews"]
            if item["state"] == "open"
        ]
        assert (case["reason"], case["scope_reference"]) == ("financial_binding_conflict", str(op.id))
    else:
        assert result == 0 and saved.state == PurchaseIntentState.LINKED


@pytest.mark.parametrize("audit_first", [True, False], ids=["audit-first", "bind-first"])
async def test_audit_and_first_binding_serialize_across_users(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    audit_first: bool,
) -> None:
    transport, sources, old = background_scenario
    factory = postgres_session_factory
    config = step1_settings()
    token = "other-buyer"
    seed(factory, token=token, email="second@example.com")
    other = await confirm_purchase(
        sources, config, factory=factory, token=token, key="other", meaning=old.accepted.meaning
    )
    assert old.user_id != other.user_id and old.account_id == other.account_id
    other_customer = customers.claim_customer_send(
        factory, config, token, customers.reserve_customer(factory, config, token)
    )
    customers.apply_customer_read(factory, other_customer, provider_id="346", outer_key=other_customer.outer_key)
    for purchase, provider_user, credential in ((old, 345, TOKEN), (other, 346, token)):
        op = next(item for item in purchase.operations if item.kind == Kind.AGREEMENT)
        command = NewAgreement(
            user_id=provider_user, organization_id=21, agreement_number=op.key, create_date=datetime.now(UTC).date()
        )
        financial.claim_financial(
            factory, purchase, op, command.request_document(), configuration=config, token=credential
        )
    old = service.read_purchase(factory, old.user_id, old.id)
    other = service.read_purchase(factory, other.user_id, other.id)
    old_op = next(op for op in old.operations if op.kind == Kind.AGREEMENT)
    new_op = next(op for op in other.operations if op.kind == Kind.AGREEMENT)
    proof = terminal.OperationEvidence(
        operation_id=old_op.id, outcome=terminal.TerminalEvidenceKind.EXTERNAL_TERMINAL, external_object_id="456"
    )
    audit = partial(terminal.resolve_purchase, factory, config, _confirmation(factory, old, proof), PRINCIPAL)
    bind = partial(
        financial.bind_financial, factory, other, new_op, 456, proof=original_proof(factory, other, new_op, transport)
    )

    # Hold the winner's transaction open until PostgreSQL sees the other user waiting on it.
    leader_ready = Event()
    contender_pid: Future[int] = Future()
    leader_id = old_op.id if audit_first else new_op.id
    check = billing_operator.lock_and_check_other_financial_owner

    def check_with_overlap(
        db: Session,
        operation: ExternalCreateOperation,
        external_id: str,
        *,
        audit_schema: str,
        audit_reasons: tuple[str, ...],
    ) -> bool:
        if operation.create_operation_id != leader_id:
            contender_pid.set_result(db.scalar(text("SELECT pg_backend_pid()")))
        conflict = check(db, operation, external_id, audit_schema=audit_schema, audit_reasons=audit_reasons)
        if operation.create_operation_id == leader_id:
            leader_ready.set()
            pid = contender_pid.result(timeout=5)
            until = time.monotonic() + 5
            while not db.scalar(text("SELECT pg_backend_pid() = ANY(pg_blocking_pids(:pid))"), {"pid": pid}):
                assert time.monotonic() < until, "the other writer did not wait for this identity"
                time.sleep(0.01)
        return conflict

    monkeypatch.setattr(billing_operator, "lock_and_check_other_financial_owner", check_with_overlap)
    first, second = (audit, bind) if audit_first else (bind, audit)
    leader = asyncio.create_task(asyncio.to_thread(first))
    assert await asyncio.to_thread(leader_ready.wait, 5)
    winner, loser = await asyncio.gather(leader, asyncio.to_thread(second), return_exceptions=True)
    assert isinstance(loser, PurchaseRefused)
    new_saved = service.read_purchase(factory, other.user_id, other.id)
    agreement_id = next(op.bound_id for op in new_saved.operations if op.kind == Kind.AGREEMENT)
    if audit_first:
        assert isinstance(winner, terminal.TerminalResult) and loser.code == "purchase_review_required"
        assert agreement_id is None and new_saved.state == PurchaseIntentState.MANUAL_REVIEW
        assert not service.read_purchase(factory, old.user_id, old.id).held
    else:
        assert winner is True and loser.code == "purchase_resolution_proof_incomplete"
        assert agreement_id == "456" and service.read_purchase(factory, old.user_id, old.id).held
