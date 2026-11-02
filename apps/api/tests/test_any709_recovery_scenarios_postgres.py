"""Cross-step recovery regressions: real PostgreSQL, synthetic provider I/O only."""

from __future__ import annotations

import copy
import json
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition import purchases
from app.composition.sources import source_resources
from app.domains.catalog.commercial_offer import SelectedOfferSourceFailed, canonical_document, commercial_digest
from app.domains.catalog.product_link import CurrentOffer, ProductLinkRequest
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import PurchaseRefused
from app.domains.purchases.router import present_review
from app.models import BillingWorkItem, ExternalCreateOperation, ExternalCreateOperationKind as Kind
from app.models import ExternalCreateOperationState as State, PurchaseIntentState as IntentState
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import setup_purchase, accept, TOKEN

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


@pytest.mark.parametrize("path,kind", [("/agreements", Kind.AGREEMENT), ("/subscriptions", Kind.SUBSCRIPTION)])
@pytest.mark.parametrize("created", [False, True])
async def test_late_proven_unsent_resume_has_one_new_bounded_recovery_window(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    kind: Kind,
    created: bool,
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    attempts: list[httpx.Request] = []
    instant = datetime.now(UTC)
    monkeypatch.setattr(financial, "utc_now", lambda: instant)

    def respond(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith(path):
            attempts.append(request)
            if len(attempts) == 1:
                raise httpx.ConnectError("synthetic definitely unsent", request=request)
            if created:
                transport.respond(request)
                transport.hide.add(path)
            raise httpx.ReadTimeout("synthetic lost reply", request=request)
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        first = await purchases.advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        original = next(op for op in first.operations if op.kind == kind)
        assert original.state == State.PROVEN_NOT_SENT
        with factory() as db:
            op = db.get(ExternalCreateOperation, original.id)
            history = (op.unknown_since, op.unknown_recovery_deadline_at, copy.deepcopy(op.recovery_hint_document))
            work_id = db.scalar(
                select(BillingWorkItem.work_item_id).where(
                    BillingWorkItem.coalescing_key == str(op.create_operation_id)
                )
            )
        instant += timedelta(days=1)
        resumed_at = instant
        resumed = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        current = next(op for op in resumed.operations if op.kind == kind)
        assert current.id == original.id and current.key == original.key and len(attempts) == 2
        assert json.loads(attempts[0].content) == json.loads(attempts[1].content)
        assert current.state == State.UNKNOWN and resumed.state == IntentState.AWAITING_EXTERNAL_RESULT and resumed.held
        assert current.deadline == resumed_at + timedelta(hours=2)
        assert financial.escalate_overdue_financial(factory, now=instant) == 0
        with factory() as db:
            op = db.get(ExternalCreateOperation, original.id)
            assert (op.unknown_since, op.unknown_recovery_deadline_at, op.recovery_hint_document) == history
            work = db.get(BillingWorkItem, work_id)
            assert work.active_recovery_deadline_at == current.deadline == work.next_attempt_at
            assert work.attempt_count == 2
        # Explicit advance and GET-only recovery never resend or renew this window.
        instant += timedelta(hours=1)
        again = await purchases.advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert next(op for op in again.operations if op.kind == kind).deadline == current.deadline
        assert len(attempts) == 2
        if created:
            transport.hide.remove(path)
            recovered = await purchases.recover_financial(
                sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
            )
            assert next(op for op in recovered.operations if op.kind == kind).state == State.BOUND
            assert financial.escalate_overdue_financial(factory, now=current.deadline + timedelta(seconds=1)) == 0
        else:
            # The scanner rechecks the active attempt, including after scheduling changes.
            with factory() as db:
                work = db.get(BillingWorkItem, work_id)
                work.next_attempt_at = instant
                db.commit()
            assert financial.escalate_overdue_financial(factory, now=current.deadline - timedelta(microseconds=1)) == 0
            assert financial.escalate_overdue_financial(factory, now=current.deadline) == 1
            assert service.read_purchase(factory, purchase.user_id, purchase.id).state == IntentState.MANUAL_REVIEW
        assert len(attempts) == 2


@pytest.mark.parametrize("incomplete", ["missing_state", "too_many"])
@pytest.mark.parametrize("previous_no_send", [False, True])
async def test_incomplete_inventory_recovers_same_unsent_purchase_after_healthy_read(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], incomplete: str, previous_no_send: bool
) -> None:
    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    healthy = previous_no_send
    send_attempts = 0
    ended = {"subscription_id": 888, "agreement_id": 999, "tariff_id": 701, "state": 3}

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal send_attempts
        path = request.url.path.removeprefix("/api/rest/v1")
        body = json.loads(request.content) if request.content else {}
        if request.method == "POST" and path == "/agreements":
            send_attempts += 1
            if previous_no_send and send_attempts == 1:
                raise httpx.ConnectError("synthetic definitely unsent", request=request)
        if request.method == "GET" and path == "/subscriptions" and "agreement_id" not in body:
            rows = (
                [ended]
                if healthy or incomplete != "too_many"
                else [{**ended, "subscription_id": 888 + i} for i in range(21)]
            )
            return transport.response(rows)
        if request.method == "GET" and path == "/subscriptions/888":
            value = dict(ended)
            if not healthy and incomplete == "missing_state":
                value.pop("state")
            return transport.response(value)
        if request.method == "GET" and path == "/agreements/999":
            return transport.response(
                {"agreement_id": 999, "user_id": 345, "organization_id": 21, "agreement_number": "synthetic-old"}
            )
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        if previous_no_send:
            first = await purchases.advance_purchase(
                sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
            )
            assert next(op for op in first.operations if op.kind == Kind.AGREEMENT).state == State.PROVEN_NOT_SENT
            healthy = False
        with pytest.raises(PurchaseRefused, match="purchase_inventory_incomplete"):
            await purchases.advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        pending = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert pending.state in {IntentState.PREPARING, IntentState.AWAITING_EXTERNAL_RESULT} and pending.held
        assert next(op for op in pending.operations if op.kind == Kind.AGREEMENT).state == (
            State.PROVEN_NOT_SENT if previous_no_send else State.PENDING
        )
        assert next(op for op in pending.operations if op.kind == Kind.SUBSCRIPTION).state == State.PENDING
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 0
        healthy = True
        resumed = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        assert resumed.id == purchase.id and resumed.state == IntentState.LINKED and resumed.held
        assert [op.id for op in resumed.operations] == [op.id for op in pending.operations]
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
        assert send_attempts == (2 if previous_no_send else 1)


def legacy_fingerprint(account_id: str, selection: ProductLinkRequest, offer: CurrentOffer) -> str:
    """The pre-fix digest, retained only to exercise immutable accepted history."""
    return commercial_digest(
        canonical_document(
            {
                "scope": account_id,
                "selection": selection.model_dump(),
                "money": asdict(offer.money),
                "period": asdict(offer.period),
                "quantity": asdict(offer.quantity),
                "price_id": offer.price_id,
                "period_membership_id": offer.period_membership_id,
                "defaults": [selection.tariff_service_id],
                "prepaid": offer.prepaid,
                "full_funding_required": offer.full_funding_required,
                "block_to_close_days": offer.block_to_close_days,
            }
        )
    )


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("resume_on_effective_date", [False, True])
async def test_future_schedule_preserves_current_terms_and_partially_prepared_purchase(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    legacy: bool,
    resume_on_effective_date: bool,
) -> None:
    from app.integrations.lbx import current_offer

    factory = postgres_session_factory
    transport = setup_purchase(factory)
    config = step1_settings()
    pause_after_agreement = True

    def respond(request: httpx.Request) -> httpx.Response:
        if pause_after_agreement and transport.agreements and request.url.path.startswith("/api/rest/v1/tariffs"):
            return httpx.Response(503)
        return transport.respond(request)

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        with monkeypatch.context() as legacy_context:
            if legacy:
                legacy_context.setattr(current_offer, "current_offer_fingerprint", legacy_fingerprint)
            purchase = await accept(sources, factory)
        with pytest.raises(SelectedOfferSourceFailed):
            await purchases.advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        prepared = service.read_purchase(factory, purchase.user_id, purchase.id)
        assert next(op for op in prepared.operations if op.kind == Kind.AGREEMENT).state == State.BOUND
        assert next(op for op in prepared.operations if op.kind == Kind.SUBSCRIPTION).state == State.PENDING
        pause_after_agreement = False
        _, before, _ = await purchases.review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
        prices = json.loads(transport.offer.bodies["prices"])
        selected = next(row for row in prices["response"] if row["start_date"] == "2026-10-01")
        selected["next_change_date"] = "2026-11-01"
        prices["response"].append(
            {**selected, "start_date": "2026-11-01", "next_change_date": "2027-01-01", "price_id": 1999}
        )
        transport.offer.bodies["prices"] = json.dumps(prices).encode()
        services = json.loads(transport.offer.bodies["services"])
        inline = services["response"][0]["prices"][0]
        services["response"][0]["prices"].append({**inline, "price_start_date": "2026-11-01"})
        transport.offer.bodies["services"] = json.dumps(services).encode()
        link, after, documents = await purchases.review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
        assert before.fingerprint == after.fingerprint and before.price_id == after.price_id
        assert before.period.price_effective_until != after.period.price_effective_until
        assert (
            present_review("proposal_ai", link.mapping_revision_id, before, documents).terms
            == present_review("proposal_ai", link.mapping_revision_id, after, documents).terms
        )
        if resume_on_effective_date:
            monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 11, 1, 12, tzinfo=UTC))
        resumed = await purchases.advance_purchase(
            sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id
        )
        assert resumed.state == (IntentState.MANUAL_REVIEW if resume_on_effective_date else IntentState.LINKED)
        assert resumed.held
        assert resumed.accepted == purchase.accepted
        assert transport.creates("/agreements") == 1
        assert transport.creates("/subscriptions") == (0 if resume_on_effective_date else 1)
        # On the actual effective date the new price identity is material, even at the same amount.
        monkeypatch.setattr(current_offer, "utc_now", lambda: datetime(2026, 11, 1, 12, tzinfo=UTC))
        _, effective, _ = await purchases.review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="proposal_ai"
        )
        assert effective.price_id == 1999 and effective.fingerprint != after.fingerprint
