"""Existing-primary fixtures for recovery/cadence; first selection is tested separately."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.reconciliation import reconcile_subscription
from app.core.settings import Settings
from app.models import ExternalSubscription
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario, paid_source as paid_source
from apps.api.tests.test_paid_access_rebase_postgres import effective as effective


def timestamp_cycle(year: int) -> dict[str, str]:
    return {
        "subscription_instance_start_date": f"{year}-01-31T12:34:56.123456+03:00",
        "last_tariffication_period_start": f"{year}-10-31T12:34:56.123456+03:00",
        "last_tariffication_period_end": f"{year}-11-30T12:34:56.123456+03:00",
    }


@pytest.fixture
async def paid_scenario(paid_source: Scenario, request: pytest.FixtureRequest) -> tuple:
    scenario = paid_source
    scenario.transport.subscriptions[0].update(
        subscription_instance_start_date="2026-01-31",
        last_tariffication_period_start="2026-10-31",
        last_tariffication_period_end="2026-11-29",
    )
    if getattr(request, "param", None) == "timestamp":
        scenario.transport.subscriptions[0].update(timestamp_cycle(2026))
    with scenario.factory() as db:
        user_id = db.scalar(select(ExternalSubscription.user_id))
    return scenario.transport, scenario.sources, scenario.config, scenario.subscription_id, user_id


async def reconcile(scenario: tuple, factory: sessionmaker[Session], config: Settings | None = None) -> None:
    await reconcile_subscription(
        scenario[1].require_lbx(),
        scenario[1].billing,
        config or scenario[2],
        factory=factory,
        subscription_id=scenario[3],
    )
