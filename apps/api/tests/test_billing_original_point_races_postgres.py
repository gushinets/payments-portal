"""Original financial identity across competing recovery transactions."""

from dataclasses import replace
from typing import Any
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool
import pytest

from app.composition import purchase_recovery as recovery
from app.composition.billing_operator import resolve_review
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing import terminal_resolution as terminal
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import PurchaseRefused
from app.domains.purchases.recovery_evidence import retained_points
from app.integrations.lbx.errors import LbxTimeout
from app.models import ExternalCreateOperation, ManualReviewCase, PaidAccessState
from apps.api.tests.factories.billing_operator import resolution_request, terminal_object_request
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    synthetic_prepare,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("order", ["bound_before_retention", "conflict_before_bind"])
async def test_competing_unique_reads_cannot_authorize_conflicting_purchase(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], order: str
) -> None:
    transport, sources, initial = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, initial, uncertain=True)
    op = purchase.operations[1]
    seen: list[str] = []

    class ReaderInterrupted(Exception):
        """The point committed but the background reader did not apply its failure."""

    async def recover(delegate: Any) -> None:
        await recovery.recover_financial(
            sources,
            config,
            factory=factory,
            user_id=purchase.user_id,
            purchase_id=purchase.id,
            operation_id=op.id,
            delegate=delegate,
        )

    async def competing_reader(function: Any, *args: Any, **kwargs: Any) -> Any:
        if function is recovery.retain_original_point and args[3].operation_id == op.id:
            seen.append(args[3].external_object_id)
        if function is financial.financial_pending and order == "conflict_before_bind":
            raise ReaderInterrupted()
        return await run_in_threadpool(function, *args, **kwargs)

    async def first_reader(function: Any, *args: Any, **kwargs: Any) -> Any:
        point = function is recovery.retain_original_point and args[3].operation_id == op.id
        if point:
            seen.append(args[3].external_object_id)
        if point and order == "bound_before_retention":
            transport.subscriptions[0]["subscription_id"] = 568
            await recover(competing_reader)
        if function is financial.bind_financial and order == "conflict_before_bind":
            transport.subscriptions[0]["subscription_id"] = 568
            with pytest.raises(ReaderInterrupted):
                await recover(competing_reader)
        return await run_in_threadpool(function, *args, **kwargs)

    try:
        await recover(first_reader)
    except PurchaseRefused as error:
        assert error.code in {"purchase_pending", "purchase_review_required"}
    assert seen == ["567", "568"]
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.operations[1].bound_id == ("568" if order == "bound_before_retention" else None)
    with factory() as db:
        points = retained_points(db, db.get(ExternalCreateOperation, op.id))
        assert (
            points
            and points.conflict
            and {points.primary.external_object_id, points.conflict.external_object_id} == {"567", "568"}
        )
        access = db.scalar(select(PaidAccessState))
        assert access is None or not access.effective_state_document["grants"]
    if order == "bound_before_retention":
        restore = resolution_request(saved, inspect_evidence(factory, config, saved.user_id, saved.id))
        with pytest.raises(PurchaseRefused, match="billing_review_resolution_unsupported"):
            await resolve_review(sources, config, factory=factory, request=restore, principal="os-euid:1000")
    transport.agreements[0]["close_date"] = "2026-11-05"
    transport.subscriptions[0]["state"] = 3
    for identity in ("567", "568"):
        req = terminal_object_request(factory, config, saved, subscription_id=identity)
        # The fixture uses a bound ID by default. Explicitly attest each disputed ID.
        evidence = tuple(
            item.model_copy(update={"external_object_id": identity}) if item.operation_id == op.id else item
            for item in req.evidence.operations
        )
        req = req.model_copy(update={"evidence": req.evidence.model_copy(update={"operations": evidence})})
        with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
            terminal.resolve_purchase(factory, config, req, "os-euid:1000")
    assert service.read_purchase(factory, purchase.user_id, purchase.id).held
    with factory() as db:
        assert (
            db.scalar(
                select(func.count())
                .select_from(ManualReviewCase)
                .where(ManualReviewCase.reason_code == terminal.TERMINAL_REASON)
            )
            == 0
        )
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("change", ["unknown", "manual_review", "matching_receipt", "other_receipt", "new_send"])
async def test_point_belongs_to_one_send_across_local_changes(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    change: str,
) -> None:
    from apps.api.tests.test_any709_step3_postgres import TOKEN

    transport, sources, initial = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, initial, uncertain=True)
    operation = purchase.operations[1]
    customer = service.customer_for_purchase(factory, config, purchase)
    sender = replace(operation, may_send=True)
    called = False
    tariff_reads = 0

    async def interleave(function: Any, *args: Any, **kwargs: Any) -> Any:
        nonlocal called
        if function is recovery.retain_original_point and args[3].operation_id == operation.id:
            called = True
            if change == "new_send":
                financial.proven_not_sent(factory, purchase, sender)
                fresh = service.read_purchase(factory, purchase.user_id, purchase.id)
                claim = financial.claim_financial(
                    factory,
                    fresh,
                    fresh.operations[1],
                    recovery.original_command(fresh, fresh.operations[1], customer),
                    configuration=config,
                    token=TOKEN,
                )
                assert claim.may_send and claim.id == operation.id and claim.fence != operation.fence
            elif change.endswith("receipt"):
                assert financial.record_receipt(factory, purchase, sender, 567 if change == "matching_receipt" else 568)
            else:
                financial.financial_pending(factory, purchase, operation, conflict=change == "manual_review")
                if change == "manual_review":
                    current = service.read_purchase(factory, purchase.user_id, purchase.id)
                    financial.financial_pending(factory, current, current.operations[1], conflict=True)
                    assert (
                        service.read_purchase(factory, purchase.user_id, purchase.id).operations[1].fence
                        == current.operations[1].fence
                    )
        return await run_in_threadpool(function, *args, **kwargs)

    async def fail_tariff(**kwargs: Any) -> None:
        nonlocal tariff_reads
        tariff_reads += 1
        raise LbxTimeout()

    monkeypatch.setattr(sources.require_lbx(), "get_tariff", fail_tariff)
    try:
        await recovery.recover_financial(
            sources,
            config,
            factory=factory,
            user_id=purchase.user_id,
            purchase_id=purchase.id,
            operation_id=operation.id,
            delegate=interleave,
        )
    except PurchaseRefused as error:
        assert error.code in {"purchase_pending", "purchase_review_required"}
    assert called
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.held and saved.operations[1].bound_id is None
    with factory() as db:
        points = retained_points(db, db.get(ExternalCreateOperation, operation.id))
    if change == "new_send":
        assert points is None and tariff_reads == 0
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
        return
    assert points and points.primary.external_object_id == "567"
    with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
        terminal.resolve_purchase(
            factory, config, terminal_object_request(factory, config, saved, subscription_id="568"), "os-euid:1000"
        )
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("terminal_response", [False, True], ids=["live", "ended"])
async def test_audited_bind_checks_latest_conflict_at_commit(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    terminal_response: bool,
) -> None:
    from app.domains.billing.reconciliation import read_source_time
    from app.domains.purchases.recovery_evidence import OriginalPointFact, retain_original_point

    transport, sources, initial = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    original = synthetic_prepare(factory, transport, initial, uncertain=True)
    subscription = original.operations[1]
    customer = service.customer_for_purchase(factory, config, original)
    command = recovery.original_command(original, subscription, customer)
    financial.financial_pending(factory, original, subscription, conflict=True)
    if terminal_response:
        transport.subscriptions[0].update(state=3, current_blocking=3)
    request = resolution_request(original, inspect_evidence(factory, config, original.user_id, original.id), bind=True)
    bind = financial.bind_financial

    def competing_point() -> OriginalPointFact:
        return OriginalPointFact(
            operation_id=subscription.id,
            operation_kind=subscription.kind,
            external_object_id="568",
            fact="live",
            point_read_finished_at=read_source_time(factory),
        )

    def retain_competing_point() -> bool:
        return retain_original_point(
            factory, original, customer, competing_point(), request_document=command, recovering_id=subscription.id
        )

    def late_point(*args: Any, **kwargs: Any) -> bool:
        retain_competing_point()
        return bind(*args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(financial, "bind_financial", late_point)
        with pytest.raises(PurchaseRefused, match="billing_review_stale"):
            await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    saved = service.read_purchase(factory, original.user_id, original.id)
    assert saved.held and saved.operations[1].bound_id is None
    with factory() as db:
        evidence = retained_points(db, db.get(ExternalCreateOperation, subscription.id))
        assert evidence and any(
            item and item.external_object_id == "568" for item in (evidence.primary, evidence.conflict)
        )
        assert db.get(ManualReviewCase, request.case_id).case_state == "open"
    result = await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    assert result["outcome"] == "resolved"
    with pytest.raises(PurchaseRefused, match="purchase_pending"):
        retain_competing_point()
    with factory() as db:
        op = db.get(ExternalCreateOperation, subscription.id)
        evidence = retained_points(db, op)
        assert op.bound_external_object_id == "567"
        assert evidence is None or (evidence.primary.external_object_id == "567" and evidence.conflict is None)
        audit = db.get(ManualReviewCase, request.case_id)
        assert audit.case_state == "resolved" and audit.resolution_document["proof"]["discovery"] == "unique_complete"
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


async def test_terminal_point_cannot_first_bind_past_a_different_live_id(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session], monkeypatch: pytest.MonkeyPatch
) -> None:
    transport, sources, initial = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, initial, uncertain=True)
    op = purchase.operations[1]

    async def read() -> None:
        await recovery.recover_financial(
            sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id, operation_id=op.id
        )

    async def fail_tariff(**kwargs: Any) -> None:
        raise LbxTimeout()

    with monkeypatch.context() as fault:
        fault.setattr(sources.require_lbx(), "get_tariff", fail_tariff)
        await read()
    transport.subscriptions[0].update(subscription_id=568, state=3, current_blocking=3)
    with pytest.raises(PurchaseRefused, match="purchase_review_required"):
        await read()
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.held and saved.operations[1].bound_id is None
    for identity in ("567", "568"):
        with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
            terminal.resolve_purchase(
                factory,
                config,
                terminal_object_request(factory, config, saved, subscription_id=identity),
                "os-euid:1000",
            )
    request = resolution_request(saved, inspect_evidence(factory, config, saved.user_id, saved.id), bind=True)
    result = await resolve_review(sources, config, factory=factory, request=request, principal="os-euid:1000")
    assert result["outcome"] == "resolved"
    bound = service.read_purchase(factory, saved.user_id, saved.id)
    assert bound.operations[1].bound_id == "568"
    transport.agreements[0]["close_date"] = "2026-11-05"
    confirmation = terminal_object_request(factory, config, bound, subscription_id="568")
    outcome = terminal.resolve_purchase(factory, config, confirmation, "os-euid:1000")
    assert outcome.state.resolved and not service.read_purchase(factory, saved.user_id, saved.id).held
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
