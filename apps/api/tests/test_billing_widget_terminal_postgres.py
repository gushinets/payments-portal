"""Payment presentation after ordinary termination; PostgreSQL and SIMULATED LBX."""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.billing_operator import reconcile_purchase
from app.core.errors import AppError
from app.domains.purchases import service
from app.models import ExternalCreateOperationState as State, ManualReviewCase, PurchaseIntentState
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_any709_step3_postgres import TOKEN
from apps.api.tests.test_billing_background_recovery_postgres import (
    anyio_backend as anyio_backend,
    background_scenario as background_scenario,
    original,
    synthetic_prepare,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize(
    ("case", "reconciled"),
    [("active", False), ("blocked", False), ("ended", False), ("ended", True), ("closed", False), ("closed", True)],
)
async def test_payment_widget_terminal_refusal_preserves_original_binding(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    case: str,
    reconciled: bool,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    immutable = {op.id: original(factory, op.id) for op in purchase.operations}
    if case == "ended":
        transport.subscriptions[0]["state"] = 3
    elif case == "closed":
        transport.agreements[0]["close_date"] = "2026-11-03"
    elif case == "blocked":
        transport.subscriptions[0]["current_blocking"] = 3
    if reconciled:
        await reconcile_purchase(sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id)
    count = len(transport.requests)
    if case in {"ended", "closed"}:
        with pytest.raises(AppError) as error:
            await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert error.value.code == "purchase_not_prepared"
    else:
        result = await bootstrap_account(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        assert result.purchase_id == purchase.id and result.credential
    saved = service.read_purchase(factory, purchase.user_id, purchase.id)
    assert saved.state == PurchaseIntentState.LINKED and saved.held
    assert saved.accepted == purchase.accepted
    assert [(op.id, op.state, op.bound_id) for op in saved.operations] == [
        (op.id, State.BOUND, op.bound_id) for op in purchase.operations
    ]
    assert {op.id: original(factory, op.id) for op in saved.operations} == immutable
    with factory() as db:
        assert not list(db.scalars(select(ManualReviewCase)))
    assert all(request.method == "GET" for request in transport.requests[count:])


@pytest.mark.parametrize("conflict", ["agreement_owner", "subscription_terms"])
async def test_payment_widget_terminal_state_does_not_hide_binding_conflict(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    conflict: str,
) -> None:
    transport, sources, purchase = background_scenario
    factory = postgres_session_factory
    purchase = synthetic_prepare(factory, transport, purchase, uncertain=False)
    if conflict == "agreement_owner":
        transport.agreements[0].update(user_id=999, close_date="2026-11-03")
    else:
        transport.subscriptions[0]["state"] = 3
        transport.subscriptions[0]["services"][0]["price"] = 150
    with pytest.raises(AppError):
        await bootstrap_account(sources, step1_settings(), factory=factory, token=TOKEN, purchase_id=purchase.id)
    assert service.read_purchase(factory, purchase.user_id, purchase.id).state == PurchaseIntentState.MANUAL_REVIEW
    with factory() as db:
        assert list(db.scalars(select(ManualReviewCase.reason_code))) == ["financial_binding_conflict"]
