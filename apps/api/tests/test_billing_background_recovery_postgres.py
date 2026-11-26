"""SIMULATED source objects, disposable PostgreSQL, no background CREATE."""

from __future__ import annotations

import asyncio
from collections import Counter
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from time import monotonic
from uuid import UUID, uuid4

import httpx
import pytest

from apps.api.tests.factories.original_operation import financial_claim_clock
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchase_inventory import collect_inventory
from app.composition.purchase_observation import prepared_subscription_observation as _observation
from app.composition.purchases import advance_purchase, confirm_purchase, recover_financial
from app.composition.sources import SourceResources, source_resources
from app.domains.billing import background_recovery as recovery, customers, work
from app.domains.billing import late_purchase_reviews as late
from app.domains.billing import terminal_resolution as terminal
from app.domains.billing.operator_diagnostics import inspect_evidence
from app.domains.billing.operator_review import case_digest
from app.domains.billing.reconciliation import read_source_time
from app.domains.billing.work_contracts import WorkLane
from app.domains.catalog.link_publication import publish_product_link
from app.domains.identity.services.auth import make_session_token
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete, PurchaseRefused
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx.errors import LbxAttemptsExhausted, LbxTimeout
from app.integrations.lbx.financial import Agreement, NewAgreement, NewSubscription, Subscription
from app.jobs.billing import BillingWorker
from app.models import (
    AuthSession,
    BillingPurchaseScopeHold,
    BillingStateObservation,
    BillingWorkItem,
    ManualReviewCase,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ExternalSubscription,
    PaidAccessState,
    PurchasedAllowance,
    AccessInvalidationOutbox,
    User,
)
from apps.api.tests.factories.original_operation import original_proof
from apps.api.tests.factories.billing_operator import terminal_object_request
from apps.api.tests.factories.reconciliation import agreement_factory, subscription_factory
from apps.api.tests.support.any709_step1 import link_document, link_selection, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_step3_postgres import TOKEN, accept, setup_purchase
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def background_scenario(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[tuple[PurchaseTransport, SourceResources, Purchase]]:
    from app.integrations.lbx import current_offer

    monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))
    factory = postgres_session_factory
    config = step1_settings()
    transport = setup_purchase(factory)
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        customer = customers.reserve_customer(factory, config, TOKEN)
        customer = customers.claim_customer_send(factory, config, TOKEN, customer)
        transport.customer = {"user_id": 345, "outer_id": customer.outer_key}
        customers.apply_customer_read(factory, customer, provider_id="345", outer_key=customer.outer_key)
        yield transport, sources, purchase


def synthetic_prepare(
    factory: sessionmaker[Session], transport: PurchaseTransport, purchase: Purchase, *, uncertain: bool
) -> Purchase:
    """Original possible-send history plus synthetic GET objects; no source POST."""
    config = step1_settings()
    for kind in (Kind.AGREEMENT, Kind.SUBSCRIPTION):
        purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
        op = next(op for op in purchase.operations if op.kind == kind)
        if kind == Kind.AGREEMENT:
            command = NewAgreement(
                user_id=345, organization_id=21, agreement_number=op.key, create_date=date(2026, 10, 27)
            )
            point = agreement_factory().model_dump()
            point["agreement_number"] = op.key
            point["create_date"] = command.create_date.isoformat()
            transport.agreements.append(point)
            provider_id = 456
        else:
            command = NewSubscription(
                agreement_id=456, tariff_id=701, period_id=901, tariff_service_id=1001, quantity=1, outer_id=op.key
            )
            point = subscription_factory().model_dump()
            point["total_price"] = 100
            point["services"][0].update(multiplicator=1, price=100)
            transport.subscriptions.append(point)
            provider_id = 567
        claimed = financial.claim_financial(
            factory, purchase, op, command.request_document(), configuration=config, token=TOKEN
        )
        if kind == Kind.SUBSCRIPTION and uncertain:
            pass  # Simulated lost reply/crash after possible-send commit.
        else:
            financial.bind_financial(
                factory,
                purchase,
                claimed,
                provider_id,
                proof=original_proof(
                    factory, service.read_purchase(factory, purchase.user_id, purchase.id), claimed, transport
                ),
                observation=_observation(Subscription.model_validate(point), purchase)
                if kind == Kind.SUBSCRIPTION
                else None,
            )
    return service.read_purchase(factory, purchase.user_id, purchase.id)


def job(factory: sessionmaker[Session], kind: str, reference: UUID) -> BillingWorkItem:
    with factory() as db:
        return db.scalar(
            select(BillingWorkItem).where(
                BillingWorkItem.work_kind == kind, BillingWorkItem.scope_reference == str(reference)
            )
        )


def due(factory: sessionmaker[Session], kind: str, reference: UUID) -> None:
    with factory() as db:
        row = db.get(BillingWorkItem, job(factory, kind, reference).work_item_id)
        row.next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()


def original(factory: sessionmaker[Session], operation_id: UUID) -> tuple:
    with factory() as db:
        op = db.get(ExternalCreateOperation, operation_id)
        return op.request_correlation_key, op.recovery_hint_document, op.unknown_since, op.unknown_recovery_deadline_at


async def test_late_case_survives_omission_and_fences_replacement(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, old = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    old = synthetic_prepare(factory, transport, old, uncertain=True)
    transport.agreements[0]["close_date"] = "2026-10-27"
    transport.subscriptions[0]["state"] = 3
    request = terminal_object_request(factory, config, old, subscription_id="567")
    finished = terminal.resolve_purchase(factory, config, request, "os-euid:1000")
    terminal_purchase = service.read_purchase(factory, old.user_id, old.id)
    replacement = await accept(sources, factory, key="late-case-replacement")
    transport.agreements[0]["close_date"] = None
    transport.subscriptions[0]["state"] = 2

    with pytest.raises(PurchaseRefused):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    with factory() as db:
        [case] = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).all()
        assert case.scope_reference == str(old.id)
        assert case.case_state == "open" and case.evidence_document["external_object_id"] == "567"
        case_id, expected_digest = case.review_case_id, case_digest(case)
    transport.hide.add("/subscriptions")
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert service.read_purchase(factory, replacement.user_id, replacement.id).held
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    assert inspect_evidence(factory, config, old.user_id, replacement.id)["blocking_late_reviews"] == [
        {
            "purchase_intent_id": str(old.id),
            "review_case_id": str(case_id),
            "expected_case_digest": expected_digest,
        }
    ]

    other_token, token_hash, expires = make_session_token()
    with factory.begin() as db:
        user_id = uuid4()
        db.add(
            User(
                id=user_id,
                tenant_id=config.instance_tenant_id,
                region=config.instance_region,
                email="other-buyer@example.test",
                email_normalized="other-buyer@example.test",
                email_verified_at=datetime.now(UTC),
                first_name="Synthetic",
            )
        )
        db.flush()
        db.add(
            AuthSession(
                user_id=user_id,
                tenant_id=config.instance_tenant_id,
                region=config.instance_region,
                token_hash=token_hash,
                expires_at=expires,
            )
        )
    other = await confirm_purchase(
        sources, config, factory=factory, token=other_token, key="other", meaning=replacement.accepted.meaning
    )
    other_customer = customers.reserve_customer(factory, config, other_token)
    other_customer = customers.claim_customer_send(factory, config, other_token, other_customer)
    customers.apply_customer_read(factory, other_customer, provider_id="346", outer_key=other_customer.outer_key)
    assert inspect_evidence(factory, config, other.user_id, other.id)["blocking_late_reviews"] == []
    other_agreement = other.operations[0]
    other_claim = financial.claim_financial(
        factory,
        other,
        other_agreement,
        NewAgreement(
            user_id=346, organization_id=21, agreement_number=other_agreement.key, create_date=date(2026, 10, 27)
        ).request_document(),
        configuration=config,
        token=other_token,
    )
    assert other_claim.may_send
    other_work_id = job(factory, "external_create_recovery", other_claim.id).work_item_id
    with factory.begin() as db:
        other_work = db.get(BillingWorkItem, other_work_id)
        other_work.lease_owner = "other-customer-work"
        other_work.lease_expires_at = datetime.now(UTC) + timedelta(minutes=1)

    closure = late.ClosureRequest(
        user_id=old.user_id,
        purchase_id=old.id,
        case_id=case_id,
        expected_digest=expected_digest,
        reason="Exact object terminated",
        reference="Synthetic confirmation",
        evidence=late.ClosureEvidence(
            outcome=late.ClosureKind.EXTERNAL_TERMINAL,
            external_object_id="567",
            confirmed_at=request.evidence.confirmed_at,
        ),
    )
    with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
        late.close_case(factory, config, closure, "os-euid:1000")
    with pytest.raises(PurchaseRefused, match="billing_review_stale"):
        late.close_case(factory, config, closure.model_copy(update={"purchase_id": replacement.id}), "os-euid:1000")
    assert service.read_purchase(factory, replacement.user_id, replacement.id).held
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0

    transport.subscriptions[0]["state"] = 3
    closure = closure.model_copy(
        update={"evidence": closure.evidence.model_copy(update={"confirmed_at": datetime.now(UTC)})}
    )
    result = late.close_case(factory, config, closure, "os-euid:1000")
    assert result.review_case_id == case_id and result.state == finished.state
    assert late.close_case(factory, config, closure, "os-euid:1000").already_resolved
    with factory() as db:
        assert db.get(BillingWorkItem, other_work_id).lease_owner == "other-customer-work"
    assert terminal.resolve_purchase(factory, config, request, "os-euid:1000").review_case_id == finished.review_case_id
    assert service.read_purchase(factory, old.user_id, old.id) == terminal_purchase
    transport.hide.clear()
    linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert linked.held and linked.state == "linked"
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1

    transport.subscriptions[0]["state"] = 2
    await recover_financial(
        sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id, operation_id=old.operations[1].id
    )
    blockers = inspect_evidence(factory, config, old.user_id, linked.id)["blocking_late_reviews"]
    assert len(blockers) == 1 and blockers[0]["review_case_id"] != str(case_id)
    assert service.read_purchase(factory, linked.user_id, linked.id) == linked


async def test_late_subscription_survives_tariff_disagreement_and_list_omission(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, old = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    old = synthetic_prepare(factory, transport, old, uncertain=True)
    agreement, ended = transport.agreements[0], transport.subscriptions[0]
    agreement["close_date"], ended["state"] = "2026-10-27", 3
    terminal.resolve_purchase(
        factory, config, terminal_object_request(factory, config, old, subscription_id="567"), "os-euid:1000"
    )
    replacement = await accept(sources, factory, key="late-tariff-disagreement")
    transport.agreements.append({**agreement, "agreement_id": 987, "close_date": None})
    transport.subscriptions.append({**ended, "subscription_id": 789, "agreement_id": 987, "tariff_id": 702, "state": 2})
    client = sources.require_lbx()
    discover = client.discover_subscriptions

    async def stale_tariff_list(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        return tuple(
            row.model_copy(update={"tariff_id": replacement.accepted.selection.tariff_id})
            for row in await discover(user_id=user_id, budget=budget)
            if row.subscription_id == 789
        )

    with monkeypatch.context() as fault:
        fault.setattr(client, "discover_subscriptions", stale_tariff_list)
        with pytest.raises(PurchaseInventoryIncomplete):
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    with factory() as db:
        cases = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).all()
        assert len(cases) == 1
        case = cases[0]
        evidence = late.LateObjectEvidence.model_validate(case.evidence_document)
        assert case.scope_reference == str(old.id) and case.case_state == "open"
        assert (evidence.external_object_id, evidence.agreement_id, evidence.competing_tariff_id) == ("789", "987", 702)

    transport.hide.add("/subscriptions")
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("sibling_state", ["unbound", "bound", "receipt", "receipt-number-only"])
async def test_inventory_keeps_late_point_when_discovery_names_a_held_sibling(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    sibling_state: str,
) -> None:
    transport, sources, original_purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    original_purchase = synthetic_prepare(factory, transport, original_purchase, uncertain=True)
    agreement, ended = transport.agreements[0], transport.subscriptions[0]
    agreement["close_date"], ended["state"] = "2026-10-27", 3
    request = terminal_object_request(factory, config, original_purchase, subscription_id="567")
    terminal.resolve_purchase(factory, config, request, "os-euid:1000")
    agreement["close_date"] = None
    bound = sibling_state == "bound"
    sibling = historical_link(
        factory, original_purchase, transport, "brief_decoder", 1, uncertain_subscription=not bound
    )
    sibling_agreement, sibling_subscription = sibling.operations
    assert sibling_agreement.bound_id is not None
    if bound:
        assert sibling_subscription.state == State.BOUND and sibling_subscription.bound_id == "568"
        late_id = 568
        transport.subscriptions[-1].update(agreement_id=456, state=2)
    else:
        assert sibling_subscription.state == State.POSSIBLE_SEND
        assert sibling_subscription.bound_id is None and sibling_subscription.candidate_id is None
        if sibling_state.startswith("receipt"):
            assert financial.record_receipt(factory, sibling, replace(sibling_subscription, may_send=True), 568)
        late_id = 789
        transport.subscriptions[-1] = {**ended, "subscription_id": late_id, "state": 2}
        if sibling_state == "receipt-number-only":
            transport.agreements.append({**agreement, "agreement_id": 987})
            transport.subscriptions[-1]["agreement_id"] = 987
    for product, tariff, revision in (("brief_decoder", 703, 1), ("proposal_ai", 701, 2)):
        publish_product_link(
            factory,
            evaluation=link_document(selection=link_selection(product_id=product, tariff_id=tariff)),
            expected_previous_revision=revision,
            deadline=monotonic() + 5,
            lock_timeout_seconds=1,
            provider_origin=config.lbx_provider_origin,
        )
    replacement = await accept(sources, factory, key="late-point-redirect")
    client = sources.require_lbx()
    discover = client.discover_subscriptions

    async def stale_list(*, user_id: int, budget: PreflightBudget) -> tuple[Subscription, ...]:
        rows = await discover(user_id=user_id, budget=budget)
        return tuple(
            row.model_copy(update={"agreement_id": int(sibling_agreement.bound_id)})
            for row in rows
            if row.subscription_id == late_id
        )

    before = len(transport.requests)
    start = read_source_time(factory)
    with monkeypatch.context() as fault:
        fault.setattr(client, "discover_subscriptions", stale_list)
        with pytest.raises(PurchaseInventoryIncomplete):
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert sum(req.url.path.endswith(f"/subscriptions/{late_id}") for req in transport.requests[before:]) == (
        2 if bound else 1
    )
    with factory() as db:
        [case] = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).all()
        evidence = late.LateObjectEvidence.model_validate(case.evidence_document)
        assert case.case_state == "open" and case.scope_reference == str(original_purchase.id)
        assert (evidence.kind, evidence.external_object_id, evidence.agreement_id, evidence.fact) == (
            Kind.SUBSCRIPTION,
            str(late_id),
            "987" if sibling_state == "receipt-number-only" else "456",
            "live",
        )
        assert start <= evidence.read_finished_at <= read_source_time(factory)
        case_id = case.review_case_id
    transport.hide.add("/subscriptions")
    with pytest.raises(
        PurchaseRefused, match="purchase_inventory_incomplete" if bound else "purchase_existing_subscription_review"
    ):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    [blocker] = inspect_evidence(factory, config, replacement.user_id, replacement.id)["blocking_late_reviews"]
    assert blocker["review_case_id"] == str(case_id)
    if sibling_state.startswith("receipt"):
        saved = service.read_purchase(factory, sibling.user_id, sibling.id).operations[1]
        assert saved.bound_id is None and saved.candidate_id == "568"
    if bound:
        assert service.read_purchase(factory, sibling.user_id, sibling.id).operations[1].bound_id == "568"


async def test_inventory_allows_fresh_purchase_when_ended_id_has_two_closed_cases(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, first = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    first = synthetic_prepare(factory, transport, first, uncertain=True)
    second = historical_link(factory, first, transport, "brief_decoder", 1, uncertain_subscription=True)
    purchases = (first, second)
    for original, agreement, subscription in zip(purchases, transport.agreements, transport.subscriptions, strict=True):
        agreement["close_date"], subscription["state"] = "2026-10-29", 3
        request = terminal_object_request(
            factory, config, original, subscription_id=str(subscription["subscription_id"])
        )
        terminal.resolve_purchase(factory, config, request, "os-euid:1000")
    for product, tariff, revision in (("brief_decoder", 703, 1), ("proposal_ai", 701, 2)):
        publish_product_link(
            factory,
            evaluation=link_document(selection=link_selection(product_id=product, tariff_id=tariff)),
            expected_previous_revision=revision,
            deadline=monotonic() + 5,
            lock_timeout_seconds=1,
            provider_origin=config.lbx_provider_origin,
        )
    replacement = await accept(sources, factory, key="late-point-two-closed-cases")
    point = {**transport.subscriptions[0], "subscription_id": 789}
    transport.subscriptions.append(point)
    for original, agreement in zip(purchases, transport.agreements, strict=True):
        agreement["close_date"] = None
        point.update(agreement_id=agreement["agreement_id"], state=2)
        await recover_financial(
            sources,
            config,
            factory=factory,
            user_id=original.user_id,
            purchase_id=original.id,
            operation_id=original.operations[1].id,
        )
        with factory() as db:
            [case] = db.scalars(
                select(ManualReviewCase).where(
                    ManualReviewCase.reason_code == late.REASON, ManualReviewCase.case_state == "open"
                )
            ).all()
            assert (case.scope_reference, case.evidence_document["external_object_id"]) == (str(original.id), "789")
            case_id, digest = case.review_case_id, case_digest(case)
        point["state"] = 3
        closure = late.ClosureRequest(
            user_id=original.user_id,
            purchase_id=original.id,
            case_id=case_id,
            expected_digest=digest,
            reason="Confirm exact object's terminal outcome",
            reference="Synthetic confirmation",
            evidence=late.ClosureEvidence(
                outcome=late.ClosureKind.EXTERNAL_TERMINAL,
                external_object_id="789",
                confirmed_at=read_source_time(factory),
            ),
        )
        assert late.close_case(factory, config, closure, "os-euid:1000").review_case_id == case_id
    with factory() as db:
        cases = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).all()
        assert {(case.scope_reference, case.case_state) for case in cases} == {
            (str(first.id), "resolved"),
            (str(second.id), "resolved"),
        }
    point["state"] = 2
    with pytest.raises(PurchaseInventoryIncomplete):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0

    point["state"] = 3
    before = len(transport.requests)
    linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert any(req.url.path.endswith("/subscriptions/789") for req in transport.requests[before:])
    assert linked.state == "linked" and linked.operations[1].bound_id not in {None, "567", "568", "789"}
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


@pytest.mark.parametrize("same_customer", [True, False], ids=["owned", "foreign"])
async def test_inventory_refreshes_exact_case_only_id_after_agreement_change(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    same_customer: bool,
) -> None:
    transport, sources, original_purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    original_purchase = synthetic_prepare(factory, transport, original_purchase, uncertain=True)
    agreement, ended = transport.agreements[0], transport.subscriptions[0]
    agreement["close_date"], ended["state"] = "2026-10-27", 3
    request = terminal_object_request(factory, config, original_purchase, subscription_id="567")
    terminal.resolve_purchase(factory, config, request, "os-euid:1000")
    replacement = await accept(sources, factory, key="late-case-only-id")
    agreement["close_date"] = None
    moved = {**ended, "subscription_id": 789, "state": 2}
    transport.subscriptions.append(moved)
    await recover_financial(
        sources,
        config,
        factory=factory,
        user_id=original_purchase.user_id,
        purchase_id=original_purchase.id,
        operation_id=original_purchase.operations[1].id,
    )
    with factory() as db:
        [case] = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).all()
        initial = late.LateObjectEvidence.model_validate(case.evidence_document)
        assert initial.external_object_id == "789" and initial.agreement_id == "456"
        identity = case.review_case_id
    confirmed = read_source_time(factory)
    transport.agreements.append(
        {
            **agreement,
            "agreement_id": 987,
            "agreement_number": "other-agreement",
            "user_id": 345 if same_customer else 346,
        }
    )
    moved["agreement_id"] = 987
    customer = service.customer_for_purchase(factory, config, replacement)
    before = len(transport.requests)
    async with sources.billing.operation(bound_scope=False) as budget:
        inventory = await collect_inventory(
            sources.require_lbx(), sources.billing, config, factory=factory, customer=customer, budget=budget
        )
    paths = [req.url.path for req in transport.requests[before:]]
    assert sum(path.endswith("/subscriptions/789") for path in paths) == 1
    assert any(path.endswith("/agreements/987") for path in paths)
    with factory() as db:
        [case] = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).all()
        assert case.review_case_id == identity and case.case_state == "open"
        evidence = late.LateObjectEvidence.model_validate(case.evidence_document)
        digest = case_digest(case)
    if not same_customer:
        assert not inventory.complete and evidence == initial
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
        return

    assert evidence.external_object_id == "789" and evidence.agreement_id == "987"
    assert confirmed < evidence.read_finished_at <= read_source_time(factory)
    closure = late.ClosureRequest(
        user_id=original_purchase.user_id,
        purchase_id=original_purchase.id,
        case_id=identity,
        expected_digest=digest,
        reason="Confirm exact object's terminal outcome",
        reference="Synthetic confirmation",
        evidence=late.ClosureEvidence(
            outcome=late.ClosureKind.EXTERNAL_TERMINAL, external_object_id="789", confirmed_at=confirmed
        ),
    )
    with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
        late.close_case(factory, config, closure, "os-euid:1000")
    with factory() as db:
        assert db.get(ManualReviewCase, identity).case_state == "open"
    moved["state"] = 3
    fresh = closure.model_copy(
        update={"evidence": closure.evidence.model_copy(update={"confirmed_at": read_source_time(factory)})}
    )
    assert late.close_case(factory, config, fresh, "os-euid:1000").review_case_id == identity
    linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert linked.state == "linked" and linked.operations[1].bound_id not in {None, "567", "789"}
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


@pytest.fixture
async def late_scope_scenario(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
) -> tuple[PurchaseTransport, SourceResources, Purchase, Purchase]:
    transport, sources, original_purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    original_purchase = synthetic_prepare(factory, transport, original_purchase, uncertain=True)
    agreement, ended = transport.agreements[0], transport.subscriptions[0]
    agreement["close_date"], ended["state"] = "2026-10-27", 3
    request = terminal_object_request(factory, config, original_purchase, subscription_id="567")
    terminal.resolve_purchase(factory, config, request, "os-euid:1000")
    agreement["close_date"] = None
    moved = {**ended, "subscription_id": 789, "state": 2}
    transport.subscriptions.append(moved)
    await recover_financial(
        sources,
        config,
        factory=factory,
        user_id=original_purchase.user_id,
        purchase_id=original_purchase.id,
        operation_id=original_purchase.operations[1].id,
    )
    publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(product_id="proposal_ai", tariff_id=702)),
        expected_previous_revision=1,
        deadline=monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    )
    link = publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(product_id="brief_decoder", tariff_id=701)),
        expected_previous_revision=0,
        deadline=monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    ).stored
    accepted = original_purchase.accepted
    meaning = accepted.meaning.model_copy(
        update={"product_id": "brief_decoder", "revision_id": link.mapping_revision_id}
    )
    independent = service.pin_purchase(
        factory, config, TOKEN, "late-case-independent-product", meaning, link, accepted.offer, accepted.documents
    )
    return transport, sources, original_purchase, independent


@pytest.mark.parametrize("previous_tariff", [None, 703], ids=["original-scope", "verified-competing-scope"])
async def test_unverified_late_agreement_preserves_scope_without_blocking_independent_product(
    late_scope_scenario: tuple[PurchaseTransport, SourceResources, Purchase, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    previous_tariff: int | None,
) -> None:
    transport, sources, original_purchase, independent = late_scope_scenario
    factory, config = postgres_session_factory, step1_settings()
    agreement, moved = transport.agreements[0], transport.subscriptions[-1]
    old_agreement_id = 456
    if previous_tariff is not None:
        old_agreement_id = 986
        transport.agreements.append(
            {**agreement, "agreement_id": old_agreement_id, "agreement_number": "verified-owned-agreement"}
        )
        moved.update(agreement_id=old_agreement_id, tariff_id=previous_tariff)
        await recover_financial(
            sources,
            config,
            factory=factory,
            user_id=original_purchase.user_id,
            purchase_id=original_purchase.id,
            operation_id=original_purchase.operations[1].id,
        )
    with factory() as db:
        [case] = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).all()
        before = late.LateObjectEvidence.model_validate(case.evidence_document)
        assert (before.agreement_id, before.competing_tariff_id) == (str(old_agreement_id), previous_tariff)
        assert not late.blocking_cases(db, independent)
        case_id = case.review_case_id

    transport.agreements.append(
        {**agreement, "agreement_id": 987, "agreement_number": "foreign-agreement", "user_id": 346}
    )
    moved.update(agreement_id=987, tariff_id=701)
    client = sources.require_lbx()
    get_agreement = client.get_agreement
    customer = service.customer_for_purchase(factory, config, independent)
    failed_at: list[datetime] = []

    async def fail_foreign_agreement(*, agreement_id: int, budget: PreflightBudget) -> Agreement:
        if agreement_id == 987:
            failed_at.append(read_source_time(factory))
            raise LbxTimeout()
        return await get_agreement(agreement_id=agreement_id, budget=budget)

    with monkeypatch.context() as fault:
        fault.setattr(client, "get_agreement", fail_foreign_agreement)
        async with sources.billing.operation(bound_scope=False) as budget:
            inventory = await collect_inventory(
                client, sources.billing, config, factory=factory, customer=customer, expected=independent, budget=budget
            )
            assert not inventory.complete
    [failed_read] = failed_at
    with factory() as db:
        case = db.get(ManualReviewCase, case_id)
        after = late.LateObjectEvidence.model_validate(case.evidence_document)
        assert case.case_state == "open"
        assert before.read_finished_at < after.read_finished_at <= failed_read
        assert after == before.model_copy(update={"read_finished_at": after.read_finished_at})

    async with sources.billing.operation(bound_scope=False) as budget:
        assert (await client.get_agreement(agreement_id=987, budget=budget)).user_id == 346
    transport.hide.add("/subscriptions")
    linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=independent.id)
    assert linked.state == "linked"
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


@pytest.mark.parametrize(
    ("relationships", "legacy"),
    [
        (((986, 701),), False),
        (((986, 701),), True),
        (((986, 703),), False),
        (((987, 701),), False),
        (((986, 703), (986, 701)), False),
    ],
    ids=["verified-relationship", "legacy-case", "different-tariff", "different-agreement", "matching-reread"],
)
async def test_reopened_late_case_only_reuses_verified_relationship(
    late_scope_scenario: tuple[PurchaseTransport, SourceResources, Purchase, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    relationships: tuple[tuple[int, int], ...],
    legacy: bool,
) -> None:
    transport, sources, original, replacement = late_scope_scenario
    factory, config = postgres_session_factory, step1_settings()
    point = transport.subscriptions[-1]
    transport.agreements.append(
        {**transport.agreements[0], "agreement_id": 986, "agreement_number": "verified-owned-agreement"}
    )
    point["agreement_id"] = 986
    await recover_financial(
        sources,
        config,
        factory=factory,
        user_id=original.user_id,
        purchase_id=original.id,
        operation_id=original.operations[1].id,
    )
    with factory.begin() as db:
        [case] = late.blocking_cases(db, replacement)
        if legacy:
            case.evidence_document = {
                key: value for key, value in case.evidence_document.items() if key != "scope_read_finished_at"
            }
        previous = late.LateObjectEvidence.model_validate(case.evidence_document)
        case_id, digest = case.review_case_id, case_digest(case)
    point["state"] = 3
    closure = late.ClosureRequest(
        user_id=original.user_id,
        purchase_id=original.id,
        case_id=case_id,
        expected_digest=digest,
        reason="Confirm exact object's terminal outcome",
        reference="Synthetic confirmation",
        evidence=late.ClosureEvidence(
            outcome=late.ClosureKind.EXTERNAL_TERMINAL, external_object_id="789", confirmed_at=read_source_time(factory)
        ),
    )
    late.close_case(factory, config, closure, "os-euid:1000")

    client = sources.require_lbx()
    get_agreement = client.get_agreement
    customer = service.customer_for_purchase(factory, config, replacement)

    async def fail_new_agreement(*, agreement_id: int, budget: PreflightBudget) -> Agreement:
        if agreement_id == point["agreement_id"]:
            raise LbxTimeout()
        return await get_agreement(agreement_id=agreement_id, budget=budget)

    unscoped_case_id = None
    with monkeypatch.context() as fault:
        fault.setattr(client, "get_agreement", fail_new_agreement)
        for agreement_id, tariff in relationships:
            point.update(state=2, agreement_id=agreement_id, tariff_id=tariff)
            async with sources.billing.operation(bound_scope=False) as budget:
                result = await collect_inventory(
                    client,
                    sources.billing,
                    config,
                    factory=factory,
                    customer=customer,
                    expected=replacement,
                    budget=budget,
                )
                assert not result.complete
            if (agreement_id, tariff) != (986, 701):
                with factory() as db:
                    [unscoped] = db.scalars(
                        select(ManualReviewCase).where(
                            ManualReviewCase.reason_code == late.REASON, ManualReviewCase.case_state == "open"
                        )
                    ).all()
                    assert unscoped.evidence_document["scope_read_finished_at"] is None
                    unscoped_case_id = unscoped.review_case_id
    assert late.close_case(factory, config, closure, "os-euid:1000").already_resolved

    transport.hide.add("/subscriptions")
    if relationships[-1] == (986, 701):
        with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
        with factory() as db:
            [reopened] = late.blocking_cases(db, replacement)
            evidence = late.LateObjectEvidence.model_validate(reopened.evidence_document)
            assert reopened.review_case_id != case_id
            if unscoped_case_id is not None:
                assert reopened.review_case_id == unscoped_case_id
            assert reopened.scope_reference == str(original.id)
            assert evidence == previous.model_copy(update={"read_finished_at": evidence.read_finished_at})
            assert evidence.read_finished_at > closure.evidence.confirmed_at
    else:
        linked = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
        assert linked.state == "linked"


async def test_verified_late_scope_survives_out_of_order_rereads(
    late_scope_scenario: tuple[PurchaseTransport, SourceResources, Purchase, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, original, replacement = late_scope_scenario
    factory, config = postgres_session_factory, step1_settings()
    transport.agreements.append(
        {**transport.agreements[0], "agreement_id": 986, "agreement_number": "verified-owned-agreement"}
    )
    transport.subscriptions[-1]["agreement_id"] = 986
    client = sources.require_lbx()
    get_agreement = client.get_agreement
    earlier_at_agreement = asyncio.Event()
    finish_earlier = asyncio.Event()
    observed_times: list[datetime] = []
    customer = service.customer_for_purchase(factory, config, replacement)

    async def ordered_reads(*, agreement_id: int, budget: PreflightBudget) -> Agreement:
        if agreement_id == 986:
            observed_times.append(read_source_time(factory))
            if len(observed_times) == 2:
                raise LbxTimeout()
            earlier_at_agreement.set()
            await finish_earlier.wait()
        return await get_agreement(agreement_id=agreement_id, budget=budget)

    async def collect() -> bool:
        async with sources.billing.operation(bound_scope=False) as budget:
            return (
                await collect_inventory(
                    client,
                    sources.billing,
                    config,
                    factory=factory,
                    customer=customer,
                    expected=replacement,
                    budget=budget,
                )
            ).complete

    with monkeypatch.context() as fault:
        fault.setattr(client, "get_agreement", ordered_reads)
        earlier = asyncio.create_task(collect())
        try:
            await asyncio.wait_for(earlier_at_agreement.wait(), timeout=3)
            assert not await collect()
        finally:
            finish_earlier.set()
            verified = await earlier
    assert verified

    transport.hide.add("/subscriptions")
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    [earlier_read, later_read] = observed_times
    with factory() as db:
        [case] = late.blocking_cases(db, replacement)
        evidence = late.LateObjectEvidence.model_validate(case.evidence_document)
        assert case.scope_reference == str(original.id) and evidence.competing_tariff_id == 701
        assert evidence.scope_read_finished_at is not None and evidence.scope_read_finished_at <= earlier_read
        assert earlier_read < evidence.read_finished_at <= later_read
        case_id, digest = case.review_case_id, case_digest(case)
    closure = late.ClosureRequest(
        user_id=original.user_id,
        purchase_id=original.id,
        case_id=case_id,
        expected_digest=digest,
        reason="Confirm exact object's terminal outcome",
        reference="Synthetic confirmation before the later live observation",
        evidence=late.ClosureEvidence(
            outcome=late.ClosureKind.EXTERNAL_TERMINAL, external_object_id="789", confirmed_at=earlier_read
        ),
    )
    with pytest.raises(PurchaseRefused, match="purchase_resolution_confirmation_required"):
        late.close_case(factory, config, closure, "os-euid:1000")


@pytest.mark.parametrize(
    "error_type", [LbxAttemptsExhausted, PreflightDeadlineExceeded, None], ids=["exhausted", "deadline", "partial"]
)
async def test_new_late_id_survives_failed_agreement_read_and_list_omission(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    error_type: type[LbxAttemptsExhausted] | type[PreflightDeadlineExceeded] | None,
) -> None:
    transport, sources, old = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    old = synthetic_prepare(factory, transport, old, uncertain=True)
    agreement, point = transport.agreements[0], transport.subscriptions[0]
    agreement["close_date"], point["state"] = "2026-10-27", 3
    request = terminal_object_request(factory, config, old, subscription_id="567")
    terminal.resolve_purchase(factory, config, request, "os-euid:1000")
    replacement = await accept(sources, factory, key="new-late-id-replacement")
    transport.subscriptions.insert(0, {**point, "subscription_id": 789, "state": 2})
    client = sources.require_lbx()
    get_agreement = client.get_agreement
    reads: list[datetime] = []

    async def failed_agreement(*, agreement_id: int, budget: PreflightBudget) -> Agreement:
        assert agreement_id == 456
        if not transport.requests[-1].url.path.endswith("/subscriptions/789"):
            return await get_agreement(agreement_id=agreement_id, budget=budget)
        reads.append(datetime.now(UTC))
        if error_type is not None:
            raise error_type()
        return Agreement.model_validate({"agreement_id": agreement_id, "user_id": 345})

    with monkeypatch.context() as fault:
        fault.setattr(client, "get_agreement", failed_agreement)
        with pytest.raises(PurchaseInventoryIncomplete):
            await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    with factory() as db:
        case = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).one()
        evidence = late.LateObjectEvidence.model_validate(case.evidence_document)
        assert case.case_state == "open" and case.scope_reference == str(old.id)
        assert (evidence.kind, evidence.fact, evidence.external_object_id, evidence.agreement_id) == (
            Kind.SUBSCRIPTION,
            "live",
            "789",
            "456",
        )
        assert request.evidence.confirmed_at < evidence.read_finished_at <= reads[0]
        case_id, expected_digest = case.review_case_id, case_digest(case)

    transport.hide.add("/subscriptions")
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
    assert inspect_evidence(factory, config, replacement.user_id, replacement.id)["blocking_late_reviews"] == [
        {
            "purchase_intent_id": str(old.id),
            "review_case_id": str(case_id),
            "expected_case_digest": expected_digest,
        }
    ]
    before_recovery = len(transport.requests)
    await recover_financial(
        sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id, operation_id=old.operations[1].id
    )
    after_omission = transport.requests[before_recovery:]
    assert all(request.method == "GET" for request in after_omission)
    assert any(request.url.path.endswith("/subscriptions/789") for request in after_omission)
    with factory() as db:
        case = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).one()
        assert case.review_case_id == case_id and case.case_state == "open"
        assert (
            late.LateObjectEvidence.model_validate(case.evidence_document).read_finished_at > evidence.read_finished_at
        )


@pytest.mark.parametrize("contradiction", ["wrong-point-id", "foreign-agreement"])
async def test_conflicting_late_identity_fails_closed_without_a_case(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    contradiction: str,
) -> None:
    transport, sources, old = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    old = synthetic_prepare(factory, transport, old, uncertain=True)
    agreement, point = transport.agreements[0], transport.subscriptions[0]
    agreement["close_date"], point["state"] = "2026-10-27", 3
    terminal.resolve_purchase(
        factory, config, terminal_object_request(factory, config, old, subscription_id="567"), "os-euid:1000"
    )
    point.update(subscription_id=789, state=2)
    agreement.update(close_date=None)
    if contradiction == "foreign-agreement":
        agreement.update(user_id=999, organization_id=None)
    else:

        async def mismatched(*, subscription_id: int, budget: PreflightBudget) -> Subscription:
            assert subscription_id == 789
            return Subscription.model_validate({**point, "subscription_id": 790})

        monkeypatch.setattr(sources.require_lbx(), "get_subscription", mismatched)
    replacement = await accept(sources, factory, key="contradictory-late-identity")
    with pytest.raises(PurchaseInventoryIncomplete):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    with factory() as db:
        assert db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).first() is None
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0


@pytest.mark.parametrize("close_late_case", [False, True], ids=["open", "closed"])
async def test_terminal_resolution_refuses_id_owned_only_by_another_late_case(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    close_late_case: bool,
) -> None:
    transport, sources, old = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    principal = "os-euid:1000"
    old = synthetic_prepare(factory, transport, old, uncertain=True)
    agreement, ended = transport.agreements[0], transport.subscriptions[0]
    agreement["close_date"], ended["state"] = "2026-10-27", 3
    terminal.resolve_purchase(
        factory, config, terminal_object_request(factory, config, old, subscription_id="567"), principal
    )

    replacement = await accept(sources, factory, key="terminal-late-case-owner")
    transport.hide.add("/subscriptions")
    transport.fail_create = "/subscriptions"
    pending = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert pending.held and pending.operations[1].state == State.UNKNOWN and pending.operations[1].candidate_id is None
    transport.hide.remove("/subscriptions")
    replacement_agreement, replacement_subscription = transport.agreements[-1], transport.subscriptions[-1]

    agreement["close_date"] = None
    disputed = {**ended, "subscription_id": 789, "state": 2}
    transport.subscriptions.append(disputed)
    await recover_financial(
        sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id, operation_id=old.operations[1].id
    )
    agreement["close_date"], disputed["state"] = "2026-10-27", 3
    with factory() as db:
        case = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).one()
        assert case.scope_reference == str(old.id) and case.evidence_document["external_object_id"] == "789"
        case_id = case.review_case_id
        expected_digest = case_digest(case)
    if close_late_case:
        closure = late.ClosureRequest(
            user_id=old.user_id,
            purchase_id=old.id,
            case_id=case_id,
            expected_digest=expected_digest,
            reason="The late object ended",
            reference="Synthetic provider confirmation",
            evidence=late.ClosureEvidence(
                outcome=late.ClosureKind.EXTERNAL_TERMINAL,
                external_object_id="789",
                confirmed_at=read_source_time(factory),
            ),
        )
        late.close_case(factory, config, closure, principal)

    replacement_agreement["close_date"], replacement_subscription["state"] = "2026-10-27", 3
    before = service.read_purchase(factory, pending.user_id, pending.id)
    request = terminal_object_request(factory, config, before, subscription_id="789")
    with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
        terminal.resolve_purchase(factory, config, request, principal)
    assert service.read_purchase(factory, pending.user_id, pending.id) == before
    with factory() as db:
        assert (
            db.scalar(
                select(ManualReviewCase.review_case_id).where(
                    ManualReviewCase.reason_code == terminal.TERMINAL_REASON,
                    ManualReviewCase.scope_reference == str(pending.id),
                )
            )
            is None
        )
        case = db.get(ManualReviewCase, case_id)
        assert case.case_state == ("resolved" if close_late_case else "open")
        assert case_digest(case) == expected_digest

    own_id = str(replacement_subscription["subscription_id"])
    correct = terminal_object_request(factory, config, before, subscription_id=own_id)
    result = terminal.resolve_purchase(factory, config, correct, principal)
    assert result.state == "resolved_external_terminal"
    assert terminal.resolve_purchase(factory, config, correct, principal) == result.model_copy(
        update={"already_resolved": True}
    )


@pytest.mark.parametrize("dispute", ["open-case", "audit-only", "closed-case-only"])
async def test_released_recovery_checks_exact_dispute_before_first_binding(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    dispute: str,
) -> None:
    transport, sources, old = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    old = synthetic_prepare(factory, transport, old, uncertain=True)
    old_agreement, old_point = transport.agreements[0], transport.subscriptions[0]
    old_agreement["close_date"], old_point["state"] = "2026-10-27", 3
    command = terminal_object_request(factory, config, old, subscription_id="567")
    completion = terminal.resolve_purchase(factory, config, command, "os-euid:1000")
    original = service.read_purchase(factory, old.user_id, old.id)
    assert not original.held and original.operations[1].bound_id is None
    with factory() as db:
        audit = db.get(ManualReviewCase, completion.review_case_id).resolution_document
    external_id = 789 if dispute == "closed-case-only" else 567
    if dispute == "closed-case-only":
        old_point = {**old_point, "subscription_id": external_id, "state": 2}
        transport.subscriptions.append(old_point)
        old_agreement["close_date"] = None
        before_recovery = len(transport.requests)
        await recover_financial(
            sources, config, factory=factory, user_id=old.user_id, purchase_id=old.id, operation_id=old.operations[1].id
        )
        assert all(request.method == "GET" for request in transport.requests[before_recovery:])
        with factory() as db:
            case = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).one()
            assert case.evidence_document["external_object_id"] == str(external_id)
            closure = late.ClosureRequest(
                user_id=old.user_id,
                purchase_id=old.id,
                case_id=case.review_case_id,
                expected_digest=case_digest(case),
                reason="Exact object terminated",
                reference="Synthetic confirmation",
                evidence=late.ClosureEvidence(
                    outcome=late.ClosureKind.EXTERNAL_TERMINAL,
                    external_object_id=str(external_id),
                    confirmed_at=datetime.now(UTC),
                ),
            )
        old_agreement["close_date"], old_point["state"] = "2026-10-27", 3
        assert late.close_case(factory, config, closure, "os-euid:1000").review_case_id == closure.case_id
    replacement = await accept(sources, factory, key="late-bind-replacement")
    transport.hide.add("/subscriptions")
    transport.fail_create = "/subscriptions"
    pending = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
    assert pending.held and pending.operations[1].state == State.UNKNOWN
    if dispute != "closed-case-only":
        old_agreement["close_date"], old_point["state"] = None, 2
    failed_agreements = []

    async def exhausted(*, agreement_id: int, budget: PreflightBudget) -> Agreement:
        failed_agreements.append(agreement_id)
        raise LbxAttemptsExhausted()

    if dispute == "open-case":
        with monkeypatch.context() as fault:
            fault.setattr(sources.require_lbx(), "get_agreement", exhausted)
            with pytest.raises(LbxAttemptsExhausted):
                await recover_financial(
                    sources,
                    config,
                    factory=factory,
                    user_id=old.user_id,
                    purchase_id=old.id,
                    operation_id=old.operations[1].id,
                )
        assert failed_agreements == [456]
    with factory() as db:
        reviews = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).all()
        assert len(reviews) == int(dispute != "audit-only")
        if dispute == "open-case":
            [review] = reviews
            assert review.scope_reference == str(old.id) and review.case_state == "open"
            review_id = review.review_case_id
    # The exact ID now point-reads as the replacement's original. Its receipt
    # lets recovery reach the writer even while customer discovery omits it.
    new_point = transport.subscriptions.pop()
    old_point.update({**new_point, "subscription_id": external_id})
    financial.record_receipt(factory, pending, replace(pending.operations[1], may_send=True), external_id)
    before = service.read_purchase(factory, pending.user_id, pending.id)
    reason = "purchase_existing_subscription_review" if dispute == "open-case" else "purchase_review_required"
    with pytest.raises(PurchaseRefused, match=reason):
        await recover_financial(sources, config, factory=factory, user_id=pending.user_id, purchase_id=pending.id)
    if dispute == "audit-only":
        duplicate = terminal_object_request(factory, config, before, subscription_id="567")
        with pytest.raises(PurchaseRefused, match="purchase_resolution_proof_incomplete"):
            terminal.resolve_purchase(factory, config, duplicate, "os-euid:1000")
    assert service.read_purchase(factory, pending.user_id, pending.id) == before and before.held
    assert service.read_purchase(factory, old.user_id, old.id) == original
    with factory() as db:
        assert (
            db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == pending.id)) is None
        )
        assert db.get(ManualReviewCase, completion.review_case_id).resolution_document == audit
        if dispute == "open-case":
            assert db.get(ManualReviewCase, review_id).case_state == "open"
        if dispute == "closed-case-only":
            assert db.get(ManualReviewCase, closure.case_id).case_state == "resolved"
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1


@pytest.mark.parametrize("candidates", [0, 1, 2])
async def test_billing_background_recovery_zero_one_multiple_and_delayed_visibility(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    candidates: int,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    before = original(factory, op.id)
    if candidates == 0:
        transport.hide.add("/subscriptions")
    if candidates == 2:
        transport.subscriptions.append({**transport.subscriptions[0], "subscription_id": 999})
    count = len(transport.requests)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    target = next(item for item in saved.operations if item.id == op.id)
    assert target.state == {0: State.UNKNOWN, 1: State.BOUND, 2: State.MANUAL_REVIEW}[candidates]
    assert original(factory, op.id) == before and saved.held
    assert all(req.method == "GET" for req in transport.requests[count:])
    if candidates == 1:
        with factory() as db:
            sub = db.scalar(select(ExternalSubscription))
            assert job(factory, work.RECONCILIATION, sub.subscription_id) is not None
        assert job(factory, recovery.RECOVERY, op.id).work_state == "completed"
    if candidates == 0:
        transport.hide.clear()
        due(factory, recovery.RECOVERY, op.id)
        restarted = BillingWorker(step1_settings(), factory, sources.require_lbx())
        assert await restarted.tick(WorkLane.URGENT)
        assert (
            next(
                item
                for item in service.read_purchase(factory, purchase.user_id, purchase.id).operations
                if item.id == op.id
            ).state
            == State.BOUND
        )
    if candidates == 2:
        transport.subscriptions.pop()
        due(factory, recovery.RECOVERY, op.id)
        assert await worker.tick(WorkLane.URGENT)
        saved = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert next(item for item in saved.operations if item.id == op.id).state == State.MANUAL_REVIEW
    with factory() as db:
        for model in (PaidAccessState, PurchasedAllowance, AccessInvalidationOutbox):
            assert db.scalar(select(func.count()).select_from(model)) == 0
        assert all(obs.resulting_access_revision is None for obs in db.scalars(select(BillingStateObservation)))
    await worker.aclose()


@pytest.mark.parametrize("unsent", [False, True])
async def test_billing_background_recovery_independent_deadline_and_no_send(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    unsent: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    # Set original time before claiming; the permanent two-hour pair is immutable.
    past = datetime.now(UTC) - timedelta(hours=3)
    financial_claim_clock(monkeypatch, lambda: financial.utc_now())
    monkeypatch.setattr(financial, "utc_now", lambda: past)
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    if unsent:
        # A separate original completed typed result; no background authority.
        with factory() as db:
            row = db.get(ExternalCreateOperation, op.id)
            row.operation_state = State.POSSIBLE_SEND
            db.commit()
        from dataclasses import replace

        financial.proven_not_sent(factory, purchase, replace(op, may_send=True))
    before = original(factory, op.id)
    count = len(transport.requests)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.LOCAL)  # Provider outage cannot block this.
    # The bound agreement deadline may run first.
    await worker.tick(WorkLane.LOCAL)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    state = next(item for item in saved.operations if item.id == op.id).state
    assert state == (State.PROVEN_NOT_SENT if unsent else State.MANUAL_REVIEW)
    assert original(factory, op.id) == before and saved.held
    assert len(transport.requests) == count
    if not unsent:
        assert not await worker.tick(WorkLane.URGENT)  # Automatic discovery is paused.
        assert job(factory, recovery.RECOVERY, op.id).work_state == "paused"
        from app.composition.purchases import recover_financial

        await recover_financial(
            sources,
            step1_settings(),
            factory=factory,
            user_id=purchase.user_id,
            purchase_id=purchase.id,
            operation_id=op.id,
        )
        assert (
            next(
                item
                for item in service.read_purchase(factory, purchase.user_id, purchase.id).operations
                if item.id == op.id
            ).state
            == State.BOUND
        )
    await worker.aclose()


@pytest.mark.parametrize("uncertain_product", ["proposal_ai", "brief_decoder"])
async def test_billing_background_recovery_two_products_same_tariff_isolated(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    uncertain_product: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=uncertain_product == "proposal_ai")
    second = historical_link(
        factory, first, transport, "brief_decoder", 1, uncertain_subscription=uncertain_product == "brief_decoder"
    )
    target, other = (first, second) if uncertain_product == "proposal_ai" else (second, first)
    op = next(item for item in target.operations if item.kind == Kind.SUBSCRIPTION)
    preserved = service.read_purchase(factory, other.user_id, other.id)
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == other.id))
        other_job = db.get(BillingWorkItem, job(factory, work.RECONCILIATION, sub.subscription_id).work_item_id)
        other_job.next_attempt_at = datetime.now(UTC) + timedelta(minutes=15)
        db.commit()
        untouched = (
            sub.latest_observation_id,
            sub.projection_valid_until,
            other_job.next_attempt_at,
            other_job.enqueue_generation,
        )
    count = len(transport.requests)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    assert service.read_purchase(factory, other.user_id, other.id) == preserved
    with factory() as db:
        sub = db.get(ExternalSubscription, sub.subscription_id)
        other_job = db.get(BillingWorkItem, other_job.work_item_id)
        assert (
            sub.latest_observation_id,
            sub.projection_valid_until,
            other_job.next_attempt_at,
            other_job.enqueue_generation,
        ) == untouched
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 2
    assert (
        next(
            item for item in service.read_purchase(factory, target.user_id, target.id).operations if item.id == op.id
        ).state
        == State.BOUND
    )
    recovery.repair_batch(factory, step1_settings())
    inventory_start = len(transport.requests)
    assert await worker.tick(WorkLane.NORMAL)
    inventory = job(factory, recovery.INVENTORY, target.customer_id)
    assert inventory.last_error_classification is None
    assert (
        (datetime.now(UTC) + timedelta(hours=4)) < inventory.next_attempt_at <= (datetime.now(UTC) + timedelta(hours=6))
    )
    assert Counter(request.url.path for request in transport.requests[inventory_start:]) == {
        "/api/rest/v1/users/345": 3,
        "/api/rest/v1/tariffs/701": 2,
        "/api/rest/v1/subscriptions": 2,
        "/api/rest/v1/subscriptions/567": 1,
        "/api/rest/v1/subscriptions/568": 1,
        "/api/rest/v1/agreements/456": 1,
        "/api/rest/v1/agreements/457": 1,
    }
    # A later attempt must reread effective terms, even when its discovery
    # membership is unchanged. Successful reads never survive the attempt.
    transport.subscriptions[0]["services"][0]["price"] = 101
    transport.subscriptions[0]["total_price"] = 101
    with factory() as db:
        db.get(BillingWorkItem, inventory.work_item_id).next_attempt_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    next_attempt = len(transport.requests)
    assert await worker.tick(WorkLane.NORMAL)
    assert job(factory, recovery.INVENTORY, target.customer_id).last_error_classification is None
    assert service.read_purchase(factory, first.user_id, first.id).state == "manual_review"
    assert service.read_purchase(factory, second.user_id, second.id).state == "linked"
    assert (
        sum(request.url.path == "/api/rest/v1/subscriptions/567" for request in transport.requests[next_attempt:]) == 1
    )
    assert all(req.method == "GET" for req in transport.requests[count:])
    await worker.aclose()


@pytest.mark.parametrize("product", ["proposal_ai", "brief_decoder"])
@pytest.mark.parametrize("failure", ["swapped", "foreign", "incomplete", "ambiguous"])
async def test_billing_background_recovery_two_product_original_candidate_refusals(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    product: str,
    failure: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    first = synthetic_prepare(factory, transport, purchase, uncertain=product == "proposal_ai")
    second = historical_link(
        factory, first, transport, "brief_decoder", 1, uncertain_subscription=product == "brief_decoder"
    )
    index = 0 if product == "proposal_ai" else 1
    target, other = (first, second) if index == 0 else (second, first)
    op = next(op for op in target.operations if op.kind == Kind.SUBSCRIPTION)
    before = original(factory, op.id)
    preserved = service.read_purchase(factory, other.user_id, other.id)
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription).where(ExternalSubscription.purchase_intent_id == other.id))
        row = db.get(BillingWorkItem, job(factory, work.RECONCILIATION, sub.subscription_id).work_item_id)
        row.next_attempt_at = datetime.now(UTC) + timedelta(minutes=15)
        db.commit()
        untouched = (sub.latest_observation_id, sub.projection_valid_until, row.next_attempt_at, row.enqueue_generation)
    if failure == "swapped":
        transport.subscriptions[index]["agreement_id"] = transport.agreements[1 - index]["agreement_id"]
    elif failure == "foreign":
        transport.agreements[index]["user_id"] = 999
    elif failure == "incomplete":
        transport.subscriptions[index]["services"] = None
    else:
        transport.subscriptions.append({**transport.subscriptions[index], "subscription_id": 999})
    count = len(transport.requests)
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    saved = service.read_purchase(factory, target.user_id, target.id)
    target_op = next(item for item in saved.operations if item.id == op.id)
    assert target_op.bound_id is None
    assert target_op.state == (State.MANUAL_REVIEW if failure in {"foreign", "ambiguous"} else State.UNKNOWN)
    assert original(factory, op.id) == before and saved.held
    assert service.read_purchase(factory, other.user_id, other.id) == preserved
    with factory() as db:
        sub = db.get(ExternalSubscription, sub.subscription_id)
        row = db.get(BillingWorkItem, row.work_item_id)
        assert (
            sub.latest_observation_id,
            sub.projection_valid_until,
            row.next_attempt_at,
            row.enqueue_generation,
        ) == untouched
        assert db.scalar(select(func.count()).select_from(BillingPurchaseScopeHold)) == 2
    assert all(req.method == "GET" for req in transport.requests[count:])
    await worker.aclose()


@pytest.mark.parametrize("key", [None, "foreign-key"])
async def test_billing_background_recovery_customer_identity_incomplete_or_conflict(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    key: str | None,
) -> None:
    from app.models import ExternalBillingCustomer, ExternalBillingCustomerBindingState as Binding

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    original_key = transport.customer["outer_id"]
    transport.customer["outer_id"] = key
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.URGENT)
    with factory() as db:
        customer = db.get(ExternalBillingCustomer, purchase.customer_id)
        assert customer.binding_state == (Binding.BOUND if key is None else Binding.IDENTITY_CONFLICT)
    transport.customer["outer_id"] = original_key
    due(factory, recovery.RECOVERY, op.id)
    assert await worker.tick(WorkLane.URGENT)
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert next(item for item in saved.operations if item.id == op.id).state == (
        State.BOUND if key is None else State.POSSIBLE_SEND
    )
    assert saved.held
    await worker.aclose()


async def test_billing_background_recovery_bound_terminal_uses_lifecycle_not_preparation(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
) -> None:
    from app.composition.reconciliation import reconcile_subscription
    from app.composition.purchases import recover_financial
    from app.models import ExternalSubscriptionLifecycleStatus as Lifecycle

    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    transport.subscriptions[0]["state"] = 3
    with factory() as db:
        sub = db.scalar(select(ExternalSubscription))
    await reconcile_subscription(
        sources.require_lbx(), sources.billing, step1_settings(), factory=factory, subscription_id=sub.subscription_id
    )
    with factory() as db:
        ended = db.get(ExternalSubscription, sub.subscription_id)
        assert ended.lifecycle_status == Lifecycle.ENDED
        before = ended.latest_observation_id, ended.projection_valid_until
    count = len(transport.requests)
    result = await recover_financial(
        sources, step1_settings(), factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
    )
    assert result == purchase and result.held
    assert not any("/subscriptions" in request.url.path for request in transport.requests[count:])
    recovery.repair_batch(factory, step1_settings())
    worker = BillingWorker(step1_settings(), factory, sources.require_lbx())
    assert await worker.tick(WorkLane.NORMAL)
    with factory() as db:
        ended = db.get(ExternalSubscription, sub.subscription_id)
        # Customer inventory now uses the shared claimed writer for known
        # terminal bindings too; a fresh negative observation is legitimate.
        assert ended.latest_observation_id != before[0]
        assert (
            ended.last_authoritative_read_at
            <= ended.projection_valid_until
            <= ended.last_authoritative_read_at + timedelta(hours=6)
        )
        assert ended.lifecycle_status == Lifecycle.ENDED and ended.financial_access_status == "blocked"
        observation = db.get(BillingStateObservation, ended.latest_observation_id)
        assert observation.evidence_schema_version == "subscription-reconciliation:v2"
        assert db.scalar(select(func.count()).select_from(ManualReviewCase)) == 0
    await worker.aclose()


async def test_billing_background_recovery_resumed_unsent_uses_active_window_and_exact_deadline(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.queries import billing_reconciliation

    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    now = datetime.now(UTC)
    op = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    request = NewAgreement(
        user_id=345, organization_id=21, agreement_number=op.key, create_date=date(2026, 10, 27)
    ).request_document()
    financial_claim_clock(monkeypatch, lambda: financial.utc_now())
    monkeypatch.setattr(financial, "utc_now", lambda: now - timedelta(hours=3))
    claimed = financial.claim_financial(factory, purchase, op, request, configuration=step1_settings(), token=TOKEN)
    financial.proven_not_sent(factory, purchase, claimed)
    before = original(factory, op.id)
    purchase = service.read_purchase(factory, purchase.user_id, purchase.id)
    op = next(op for op in purchase.operations if op.id == claimed.id)
    monkeypatch.setattr(financial, "utc_now", lambda: now)
    resumed = financial.claim_financial(factory, purchase, op, request, configuration=step1_settings(), token=TOKEN)
    assert resumed.fence != claimed.fence and resumed.key == claimed.key
    active = job(factory, recovery.RECOVERY, op.id).active_recovery_deadline_at
    assert active == now + timedelta(hours=2) and before[3] < now
    assert job(factory, recovery.DEADLINE, op.id).next_attempt_at == active
    # Reconstruct missing local scheduling after restart using the same helper.
    with factory() as db:
        db.delete(db.get(BillingWorkItem, job(factory, recovery.DEADLINE, op.id).work_item_id))
        db.flush()
        recovery.enroll_operation(db, db.get(ExternalCreateOperation, op.id), purchase.account_id)
        db.commit()
    assert job(factory, recovery.DEADLINE, op.id).next_attempt_at == active
    count = len(transport.requests)
    for instant, state in ((active - timedelta(microseconds=1), State.POSSIBLE_SEND), (active, State.MANUAL_REVIEW)):
        monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: instant)
        with factory() as db:
            row = db.get(BillingWorkItem, job(factory, recovery.DEADLINE, op.id).work_item_id)
            row.next_attempt_at = instant
            db.commit()
        for _ in range(3):
            claim = work.claim_work(factory, step1_settings(), WorkLane.LOCAL)
            assert claim is not None and claim.kind == recovery.DEADLINE
            recovery.apply_deadline(factory, claim)
            if claim.reference == str(op.id):
                break
        else:
            pytest.fail("financial deadline was not processed")
        current = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert next(item for item in current.operations if item.id == op.id).state == state
        assert job(factory, recovery.RECOVERY, op.id).active_recovery_deadline_at == active
        assert original(factory, op.id) == before
    assert len(transport.requests) == count and current.held


async def test_billing_background_recovery_legacy_null_window_uses_original_deadline(
    background_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    transport, _, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=True)
    op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    with factory() as db:
        row = db.get(BillingWorkItem, job(factory, recovery.RECOVERY, op.id).work_item_id)
        row.active_recovery_deadline_at = None  # Existing pre-0004 financial work.
        db.delete(db.get(BillingWorkItem, job(factory, recovery.DEADLINE, op.id).work_item_id))
        db.flush()
        recovery.enroll_operation(db, db.get(ExternalCreateOperation, op.id), purchase.account_id)
        db.commit()
    assert job(factory, recovery.DEADLINE, op.id).next_attempt_at == original(factory, op.id)[3]


@pytest.mark.parametrize("action", ["resolve", "close-case"])
@pytest.mark.parametrize("activity", ["recovery", "inventory", "reconciliation", "ambiguous-recovery", "customer-send"])
async def test_quiesced_write_refuses_active_work_and_replays_from_audit(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    migrated_database: Engine,
    action: str,
    activity: str,
) -> None:
    from sqlalchemy import create_engine

    from app.domains.billing.contracts import BillingRefused
    from app.domains.billing.purchase_maintenance import lock_financial_object
    from app.domains.billing.reconciliation import claim_reconciliation, read_source_time
    from app.domains.billing.work_contracts import WorkClaim
    from app.infrastructure.queries.billing_customers import recovery_work
    from app.models import BillingWorkState, ExternalBillingCustomer

    transport, sources, original_purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    original_purchase = synthetic_prepare(factory, transport, original_purchase, uncertain=False)
    transport.agreements[0]["close_date"], transport.subscriptions[0]["state"] = "2026-10-27", 3
    actor = original_purchase
    closure = None
    if action == "close-case":
        terminal.resolve_purchase(
            factory,
            config,
            terminal_object_request(factory, config, original_purchase, subscription_id="567"),
            "os-euid:1000",
        )
        replacement = await accept(sources, factory, key="maintenance-replacement")
        actor = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=replacement.id)
        assert actor.state == "linked"
        transport.agreements[0]["close_date"], transport.subscriptions[0]["state"] = None, 2
        await recover_financial(
            sources,
            config,
            factory=factory,
            user_id=original_purchase.user_id,
            purchase_id=original_purchase.id,
            operation_id=original_purchase.operations[1].id,
        )
        transport.subscriptions[0]["state"] = 3
        with factory() as db:
            case = db.scalars(select(ManualReviewCase).where(ManualReviewCase.reason_code == late.REASON)).one()
            closure = late.ClosureRequest(
                user_id=original_purchase.user_id,
                purchase_id=original_purchase.id,
                case_id=case.review_case_id,
                expected_digest=case_digest(case),
                reason="Late object ended",
                reference="Synthetic confirmation",
                evidence=late.ClosureEvidence(
                    outcome=late.ClosureKind.EXTERNAL_TERMINAL,
                    external_object_id="567",
                    confirmed_at=read_source_time(factory),
                ),
            )

    subscription_id = service.linked_subscription_id(factory, actor)
    now = read_source_time(factory)
    work_id = None
    claim = None
    if activity == "reconciliation":
        claim_reconciliation(factory, config, subscription_id, io_timeout_seconds=60)
    else:
        with factory.begin() as db:
            if activity == "inventory":
                recovery.hint_inventory(db, db.get(ExternalBillingCustomer, actor.customer_id))
                item = db.scalars(
                    select(BillingWorkItem).where(
                        BillingWorkItem.scope_kind == "customer",
                        BillingWorkItem.scope_reference == str(actor.customer_id),
                    )
                ).one()
            elif activity == "customer-send":
                from app.infrastructure.queries.billing_customers import customer_operation
                from app.infrastructure.persistence.billing_work import ensure_recovery

                operation = customer_operation(db, actor.customer_id)
                assert operation.external_billing_account_id is None
                ensure_recovery(db, str(operation.create_operation_id), now)
                item = recovery_work(db, operation.create_operation_id)
            else:
                item = recovery_work(db, actor.operations[1].id)
                item.work_state = BillingWorkState.RUNNING
            if activity != "ambiguous-recovery":
                item.lease_owner = "synthetic-active-work"
                item.lease_expires_at = now + timedelta(minutes=1)
            work_id = item.work_item_id
            if activity == "recovery":
                claim = WorkClaim(
                    work_id,
                    item.work_kind,
                    item.scope_reference,
                    item.lease_owner,
                    item.enqueue_generation,
                    now,
                    item.lease_expires_at,
                    item.recipient_id,
                )

    request = terminal_object_request(factory, config, original_purchase, subscription_id="567")

    def execute(session_factory: sessionmaker[Session] = factory) -> terminal.TerminalResult:
        if closure is not None:
            return late.close_case(session_factory, config, closure, "os-euid:1000")
        return terminal.resolve_purchase(session_factory, config, request, "os-euid:1000")

    original_before = inspect_evidence(factory, config, original_purchase.user_id, original_purchase.id)
    actor_before = inspect_evidence(factory, config, actor.user_id, actor.id)
    assert original_before["customer_work_active"] and actor_before["customer_work_active"]
    with pytest.raises(PurchaseRefused, match="billing_busy"):
        execute()
    assert inspect_evidence(factory, config, original_purchase.user_id, original_purchase.id) == original_before
    assert inspect_evidence(factory, config, actor.user_id, actor.id) == actor_before

    with factory.begin() as db:
        if activity == "reconciliation":
            sub = db.get(ExternalSubscription, subscription_id)
            sub.reconciliation_lease_expires_at = now - timedelta(seconds=1)
        else:
            item = db.get(BillingWorkItem, work_id)
            if activity == "ambiguous-recovery":
                item.work_state = BillingWorkState.PENDING
            else:
                item.lease_expires_at = now - timedelta(seconds=1)

    assert not inspect_evidence(factory, config, original_purchase.user_id, original_purchase.id)[
        "customer_work_active"
    ]
    result = execute()
    assert not result.already_resolved
    if closure is None:
        assert not service.read_purchase(factory, original_purchase.user_id, original_purchase.id).held
        if claim is not None:
            with factory() as db:
                item = db.get(BillingWorkItem, work_id)
                assert item.work_state == BillingWorkState.INVALID
                assert item.enqueue_generation == claim.generation + 1
                assert item.lease_owner is None and item.lease_expires_at is None
                with pytest.raises(BillingRefused, match="billing_work_stale"):
                    work.verify_claim(db, claim)
        actor = await accept(sources, factory, key="maintenance-replacement")
    else:
        assert service.read_purchase(factory, actor.user_id, actor.id) == actor

    with factory.begin() as db:
        recovery.hint_inventory(db, db.get(ExternalBillingCustomer, actor.customer_id))
        inventory = db.scalars(
            select(BillingWorkItem).where(
                BillingWorkItem.scope_kind == "customer", BillingWorkItem.scope_reference == str(actor.customer_id)
            )
        ).one()
        inventory.lease_owner = "replacement-inventory"
        inventory.lease_expires_at = read_source_time(factory) + timedelta(minutes=1)
        replacement_work_id = inventory.work_item_id
        replacement_lease = (inventory.lease_owner, inventory.lease_expires_at, inventory.enqueue_generation)
    restarted = create_engine(migrated_database.url)
    try:
        with factory() as locker:
            lock_financial_object(locker, original_purchase.account_id, Kind.SUBSCRIPTION, "567")
            assert execute(sessionmaker(restarted, autoflush=False)) == result.model_copy(
                update={"already_resolved": True}
            )
    finally:
        restarted.dispose()
    with factory() as db:
        item = db.get(BillingWorkItem, replacement_work_id)
        assert (item.lease_owner, item.lease_expires_at, item.enqueue_generation) == replacement_lease
    assert service.read_purchase(factory, actor.user_id, actor.id) == actor


async def test_late_subscription_on_original_agreement_blocks_its_competing_tariff(
    background_scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    seed = synthetic_prepare(factory, transport, purchase, uncertain=True)
    transport.agreements[0]["close_date"], transport.subscriptions[0]["state"] = "2026-10-27", 3
    terminal.resolve_purchase(
        factory, config, terminal_object_request(factory, config, seed, subscription_id="567"), "os-euid:1000"
    )
    original = historical_link(factory, seed, transport, "brief_decoder", 1, uncertain_subscription=True)
    agreement, ended = transport.agreements[-1], transport.subscriptions[-1]
    agreement["close_date"], ended["state"] = "2026-10-27", 3
    terminal.resolve_purchase(
        factory, config, terminal_object_request(factory, config, original, subscription_id="568"), "os-euid:1000"
    )

    publish_product_link(
        factory,
        evaluation=link_document(selection=link_selection(tariff_id=703)),
        expected_previous_revision=2,
        deadline=monotonic() + 5,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    )
    transport.offer.tariff_id = 703
    for key, data in transport.offer.bodies.items():
        transport.offer.bodies[key] = data.replace(b'"tariff_id":701', b'"tariff_id":703')
    new_purchase = await accept(sources, factory, key="other-tariff-on-original-agreement")
    assert new_purchase.accepted.selection.tariff_id == 703
    assert original.accepted.selection.tariff_id == 701

    agreement["close_date"] = None
    point = {**ended, "subscription_id": 789, "state": 2, "tariff_id": 703}
    transport.subscriptions.append(point)
    await recover_financial(
        sources,
        config,
        factory=factory,
        user_id=original.user_id,
        purchase_id=original.id,
        operation_id=original.operations[1].id,
    )

    with factory() as db:
        [case] = late.blocking_cases(db, new_purchase)
        assert case.scope_reference == str(original.id)
        assert case.evidence_document["competing_tariff_id"] == 703
    transport.hide.add("/subscriptions")
    with pytest.raises(PurchaseRefused, match="purchase_existing_subscription_review"):
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=new_purchase.id)
    assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
