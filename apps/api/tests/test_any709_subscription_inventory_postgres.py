"""Every new subscription send requires current customer-wide inventory proof."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.purchases import advance_purchase, recover_financial
from app.composition.sources import source_resources
from app.domains.purchases import service
from app.domains.purchases.contracts import PurchaseRefused
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from app.models import PurchaseIntentState as Intent
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_any709_step3_postgres import TOKEN, accept, setup_purchase

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def calendar(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 10, 27, 12, tzinfo=UTC))


def add_external_subscription(transport: PurchaseTransport, state: int | None) -> None:
    transport.agreements.append(
        {"agreement_id": 9999, "user_id": 345, "organization_id": 21, "agreement_number": "synthetic-external"}
    )
    transport.subscriptions.append(
        {
            "subscription_id": 9999,
            "agreement_id": 9999,
            "tariff_id": 701,
            "period_id": 901,
            "period_type": 3,
            "period_length": 1,
            "state": state,
            "current_blocking": 0,
            "is_demo": False,
            "is_offer_agrm": False,
            "total_price": 100,
            "currency_symbol": "руб",
            "outer_id": "synthetic-external",
            "subscription_start_date": None,
            "last_tariffication_period_start": "1970-01-01 00:00:00",
            "services": [
                {
                    "tariff_service_id": 1001,
                    "multiplicator": 1,
                    "price": 100,
                    "bulk_price": None,
                    "bulk_include_amount": None,
                    "periodic_service": 1,
                    "bulk_service": False,
                }
            ],
        }
    )


@pytest.mark.parametrize("resume", [False, True], ids=["first-subscription-send", "proven-not-sent-resume"])
@pytest.mark.parametrize("external_state", [-2, 3, None], ids=["competing", "ended", "incomplete"])
async def test_subscription_send_rechecks_inventory_after_agreement_preparation(
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    resume: bool,
    external_state: int | None,
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    reject_subscription = resume

    def respond(request: httpx.Request) -> httpx.Response:
        if reject_subscription and request.method == "POST" and request.url.path.endswith("/subscriptions"):
            raise httpx.ConnectError("synthetic no-send", request=request)
        response = transport.respond(request)
        if not resume and request.method == "POST" and request.url.path.endswith("/agreements"):
            # The external purchase appears after the first inventory check.
            add_external_subscription(transport, external_state)
        return response

    async with source_resources(
        config, kernel_transport=httpx.MockTransport(transport.kernel), lbx_transport=httpx.MockTransport(respond)
    ) as sources:
        purchase = await accept(sources, factory)
        if resume:
            paused = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
            assert next(op for op in paused.operations if op.kind == Kind.AGREEMENT).state == State.BOUND
            assert next(op for op in paused.operations if op.kind == Kind.SUBSCRIPTION).state == State.PROVEN_NOT_SENT
            assert transport.creates("/subscriptions") == 0
            reject_subscription = False
            add_external_subscription(transport, external_state)
        if external_state == 3:
            result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
            assert result.state == Intent.LINKED
        else:
            code = (
                "purchase_inventory_incomplete" if external_state is None else "purchase_existing_subscription_review"
            )
            with pytest.raises(PurchaseRefused, match=code):
                await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
            result = service.read_purchase(factory, purchase.user_id, purchase.id)
            operation = next(op for op in result.operations if op.kind == Kind.SUBSCRIPTION)
            assert transport.creates("/subscriptions") == 0
            if external_state is None:
                assert result.state != Intent.MANUAL_REVIEW
                assert operation.state == (State.PROVEN_NOT_SENT if resume else State.PENDING)
                # Complete healthy inventory may resume the same operation.
                next(row for row in transport.subscriptions if row["subscription_id"] == 9999)["state"] = 3
                result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
                assert result.state == Intent.LINKED
            else:
                assert result.state == Intent.MANUAL_REVIEW and operation.state == State.MANUAL_REVIEW
                # A later clean inventory cannot silently clear a known conflict.
                next(row for row in transport.subscriptions if row["subscription_id"] == 9999)["state"] = 3
                result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
                assert result.state == Intent.MANUAL_REVIEW
        assert result.held and result.accepted == purchase.accepted
        assert [op.id for op in result.operations] == [op.id for op in purchase.operations]
        assert transport.creates("/users") == transport.creates("/agreements") == 1
        assert transport.creates("/subscriptions") == (0 if external_state == -2 else 1)


@pytest.mark.parametrize("entrypoint", ["advance", "recovery"])
async def test_unknown_subscription_remains_get_only_despite_new_competing_inventory(
    migrated_database: Engine, postgres_session_factory: sessionmaker[Session], entrypoint: str
) -> None:
    factory, config = postgres_session_factory, step1_settings()
    transport = setup_purchase(factory)
    transport.fail_create = "/subscriptions"
    transport.hide.add("/subscriptions")
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        purchase = await accept(sources, factory)
        pending = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert next(op for op in pending.operations if op.kind == Kind.SUBSCRIPTION).state == State.UNKNOWN
        assert transport.creates("/subscriptions") == 1
        add_external_subscription(transport, -2)
        transport.hide.remove("/subscriptions")
        start = len(transport.requests)
        if entrypoint == "advance":
            result = await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        else:
            result = await recover_financial(
                sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id
            )
        assert result.state == Intent.LINKED and result.held and result.accepted == purchase.accepted
        assert next(op for op in result.operations if op.kind == Kind.SUBSCRIPTION).bound_id == "567"
        assert transport.creates("/agreements") == transport.creates("/subscriptions") == 1
        for request in transport.requests[start:]:
            assert request.method == "GET"
            if request.url.path.endswith("/subscriptions"):
                assert "agreement_id" in json.loads(request.content)
