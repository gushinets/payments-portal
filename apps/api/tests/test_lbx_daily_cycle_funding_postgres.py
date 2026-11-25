"""ANY-898 — apply the daily funding proof through the ordinary Portal worker."""

from datetime import UTC, datetime
import json

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.composition.backend_consumers import initialize_backend_consumers
from app.composition.mapping_operator import fresh_link_evaluation
from app.composition.purchases import advance_purchase, confirm_purchase, review_purchase
from app.composition.sources import source_resources
from app.domains.catalog.link_publication import publish_product_link
from app.domains.catalog.technical_offer import TechnicalOffer
from app.models import ExternalSubscription, PurchasedAllowance
from apps.api.tests.factories.purchase_terms import reviewed_meaning
from apps.api.tests.support.any709_step1 import link_selection, step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.support.backend_consumers import backend_consumer
from apps.api.tests.support.kernel import manifest_fixture, resign
from apps.api.tests.test_any709_step2_postgres import TOKEN, seed
from apps.api.tests.test_lbx_monthly_allowance_postgres import anyio_backend as anyio_backend
from apps.api.tests.test_lbx_monthly_allowance_postgres import run_due_worker
from apps.api.tests.test_paid_access_rebase_postgres import effective
from apps.api.tests.test_paid_access_reconciliation_postgres import Scenario

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]
FIRST = "2026-11-24"
RENEWAL = "2026-11-25"


class DailyTransport(PurchaseTransport):
    def __init__(self) -> None:
        super().__init__()
        self.day = FIRST
        self.due = 0
        self.balance = 0
        self.offer.replace("tariff", '"float_period":1', '"float_period":2')
        for key in ("periods", "prices"):
            self.offer.replace(key, '"period_type":3', '"period_type":1')
        for key in ("services", "prices"):
            self.offer.replace(key, '"price":100', '"price":10')

    def kernel(self, request: httpx.Request) -> httpx.Response:
        document = manifest_fixture()
        for metric in document["usage_metrics"]:
            if metric["product_id"] == "brief_decoder":
                metric["metric_key"] = "brief_decoder.analyses"
        return httpx.Response(200, json=resign(document))

    def respond(self, request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/recommendedpayment/details"):
            self.requests.append(request)
            assert request.method == "GET"
            assert json.loads(request.content) == {
                "agreement_id": self.agreements[0]["agreement_id"],
                "start_period": self.day,
                "end_period": self.day,
            }
            return self.response(
                {
                    "recommended_payment": self.due,
                    "current_balance": self.balance,
                    "start_period_balance": 0,
                    "start_period": self.day,
                    "end_period": self.day,
                    "services": [
                        {
                            "subscription_instance_id": 91,
                            "service_id": 89,
                            "charge_type": 0,
                            "charge_sum": 10,
                            "tariffication_period_start": self.day,
                            "tariffication_period_end": self.day,
                            "is_predicted_charge": False,
                            "is_waiting_for_activation": False,
                        }
                    ],
                }
            )
        response = super().respond(request)
        if request.method == "POST" and request.url.path.endswith("/subscriptions"):
            self.subscriptions[-1].update(period_type=1, total_price=10)
            self.subscriptions[-1]["services"][0].update(price=10, service_id=89)
        return response

    def set_cycle(self, day: str, *, due: int, balance: int) -> None:
        self.day, self.due, self.balance = day, due, balance
        self.agreements[0].update(balance=balance, credit=0, debt_threshold=0)
        self.subscriptions[0].update(
            state=2,
            current_blocking=0,
            subscription_instance_id=91,
            subscription_start_date=f"{FIRST} 00:00:00",
            subscription_instance_start_date=f"{FIRST} 00:00:00",
            last_tariffication_period_start=day,
            last_tariffication_period_end=day,
        )


@pytest.mark.parametrize("has_previous_cycle", [False, True])
async def test_unfunded_daily_renewal_waits_for_late_payment(
    has_previous_cycle: bool,
    migrated_database: Engine,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = postgres_session_factory
    seed(factory)
    config = step1_settings(kernel_mock_enabled=False, paid_access_clock_skew_seconds=10)
    initialize_backend_consumers(config.model_copy(update={"backend_consumers": (backend_consumer(),)}), factory)
    monkeypatch.setattr("app.integrations.lbx.current_offer.utc_now", lambda: datetime(2026, 11, 20, 12, tzinfo=UTC))
    transport = DailyTransport()
    transport.pool = migrated_database.pool
    test_offer = TechnicalOffer.model_validate(
        {
            "product_id": "brief_decoder",
            "metric_key": "brief_decoder.analyses",
            "unit": "analysis",
            "quantity": 2,
            "quantity_mode": "fixed_per_cycle",
        }
    )
    selected = await fresh_link_evaluation(
        config,
        selection=link_selection(product_id="brief_decoder"),
        principal="os-euid:29001",
        technical_offer=test_offer,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    )
    publish_product_link(
        factory,
        evaluation=selected.document,
        expected_previous_revision=0,
        deadline=selected.deadline,
        lock_timeout_seconds=1,
        provider_origin=config.lbx_provider_origin,
    )
    async with source_resources(
        config,
        kernel_transport=httpx.MockTransport(transport.kernel),
        lbx_transport=httpx.MockTransport(transport.respond),
    ) as sources:
        link, offer, docs, terms = await review_purchase(
            sources, config, factory=factory, token=TOKEN, product_id="brief_decoder"
        )
        assert (offer.period.unit, offer.period.length, offer.period.anchor) == ("day", 1, "first_instance_start")
        purchase = await confirm_purchase(
            sources,
            config,
            factory=factory,
            token=TOKEN,
            key="any898",
            meaning=reviewed_meaning("brief_decoder", link.mapping_revision_id, offer.fingerprint, docs, terms),
        )
        await advance_purchase(sources, config, factory=factory, token=TOKEN, purchase_id=purchase.id)
        with factory() as db:
            subscription_id = db.scalars(select(ExternalSubscription.subscription_id)).one()
        scenario = Scenario(factory, config, transport, sources, subscription_id)

        if has_previous_cycle:
            transport.set_cycle(FIRST, due=0, balance=0)
            await run_due_worker(scenario)
        initial_revision, initial = effective(factory)
        assert len(initial["allowances"]) == int(has_previous_cycle)
        with factory() as db:
            deadline = db.get(ExternalSubscription, subscription_id).projection_valid_until

        transport.set_cycle(RENEWAL, due=10, balance=-10)
        await run_due_worker(scenario)
        assert effective(factory) == (initial_revision, initial)
        with factory() as db:
            assert db.get(ExternalSubscription, subscription_id).projection_valid_until == deadline
            assert len(db.scalars(select(PurchasedAllowance)).all()) == int(has_previous_cycle)

        transport.set_cycle(RENEWAL, due=0, balance=0)
        await run_due_worker(scenario)
        funded_revision, funded = effective(factory)
        assert funded_revision > initial_revision
        (allowance,) = funded["allowances"]
        assert allowance["quantity"] == 2
        assert allowance["allowance_id"] not in {row["allowance_id"] for row in initial["allowances"]}
        with factory() as db:
            rows = db.scalars(select(PurchasedAllowance).order_by(PurchasedAllowance.cycle_date_start)).all()
            assert [row.cycle_date_start.isoformat() for row in rows] == ([FIRST] if has_previous_cycle else []) + [
                RENEWAL
            ]
            if has_previous_cycle:
                assert str(rows[0].allowance_id) == initial["allowances"][0]["allowance_id"]

        await run_due_worker(scenario)
        assert effective(factory) == (funded_revision, funded)
        reads = len(transport.requests)
        transport.subscriptions[0]["current_blocking"] = 1
        await run_due_worker(scenario)
        assert not effective(factory)[1]["allowances"]
        assert not any(req.url.path.endswith("/recommendedpayment/details") for req in transport.requests[reads:])
        with factory() as db:
            assert len(db.scalars(select(PurchasedAllowance)).all()) == int(has_previous_cycle) + 1
