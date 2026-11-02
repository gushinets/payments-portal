"""Inherited customer recovery must preserve Step 9 access and quota semantics."""

import pytest
from copy import deepcopy
from datetime import datetime
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.billing import bootstrap_account
from app.composition.billing_operator import reconcile_purchase
from app.core.time import utc_now
from app.domains.billing import background_recovery
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import apply_customer_read
from app.domains.purchases import service
from app.domains.billing.work_contracts import WorkLane
from app.domains.identity.services.auth import as_utc
from app.jobs.billing import BillingWorker
from app.models import AccessInvalidationOutbox, ExternalSubscription, ManualReviewCase, PurchasedAllowance
from apps.api.tests.test_any709_step3_postgres import TOKEN
from apps.api.tests.test_paid_access_postgres import effective, reconcile
from apps.api.tests.test_billing_background_recovery_postgres import (
    background_scenario as background_scenario,
    synthetic_prepare,
)
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.test_billing_worker_postgres import historical_link

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("entrypoint", ["customer_read", "reconciliation"])
async def test_original_customer_recovery_requires_fresh_paid_proof_and_reuses_allowance(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session], entrypoint: str
) -> None:
    factory = postgres_session_factory
    transport, sources, config, sub_id, user_id = paid_scenario
    await reconcile(paid_scenario, factory)
    before = effective(factory)
    with factory() as db:
        purchase_id = db.get(ExternalSubscription, sub_id).purchase_intent_id
    purchase = service.read_purchase(factory, user_id, purchase_id)
    customer = service.customer_for_purchase(factory, config, purchase)
    original_key = transport.customer["outer_id"]
    transport.requests.clear()
    transport.customer["outer_id"] = "synthetic-wrong-key"
    if entrypoint == "customer_read":
        with pytest.raises(BillingRefused, match="billing_identity_conflict"):
            apply_customer_read(factory, customer, provider_id=customer.provider_id, outer_key="synthetic-wrong-key")
    else:
        await reconcile(paid_scenario, factory)
    denied = (before[0] + 1, {"grants": [], "allowances": []})
    assert effective(factory) == denied
    with factory() as db:
        review = db.scalars(select(ManualReviewCase)).one()
        assert review.reason_code == "customer_original_key_mismatch" and review.case_state == "open"
    transport.customer["outer_id"] = original_key
    await bootstrap_account(sources, config, factory=factory, token=TOKEN)
    assert effective(factory) == denied  # Restoring identity alone is not paid proof.
    await reconcile(paid_scenario, factory)
    assert effective(factory) == (before[0] + 2, before[1])
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1
        assert db.scalars(select(ManualReviewCase)).one().case_state == "resolved"
    assert all(request.method == "GET" for request in transport.requests)


async def test_shared_inventory_points_never_move_source_trust_past_the_first_read(
    background_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport, sources, purchase = background_scenario
    factory, config = postgres_session_factory, step1_settings()
    first = synthetic_prepare(factory, transport, purchase, uncertain=False)
    second = historical_link(factory, first, transport, "brief_decoder", 1)
    for purchase in (first, second):
        await reconcile_purchase(sources, config, factory=factory, user_id=purchase.user_id, purchase_id=purchase.id)
    background_recovery.repair_batch(factory, config)
    client = sources.require_lbx()
    read_point = client.get_subscription
    first_read_at: datetime | None = None

    async def timestamped_read(**kwargs: object) -> object:
        nonlocal first_read_at
        first_read_at = first_read_at or utc_now()
        return await read_point(**kwargs)

    monkeypatch.setattr(client, "get_subscription", timestamped_read)
    transport.requests.clear()
    before_inventory = utc_now()
    worker = BillingWorker(config, factory, client)
    try:
        assert await worker.tick(WorkLane.NORMAL)
    finally:
        await worker.aclose()
    assert first_read_at is not None
    with factory() as db:
        subscriptions = list(db.scalars(select(ExternalSubscription)))
        assert len(subscriptions) == 2
        assert all(before_inventory <= as_utc(sub.last_authoritative_read_at) <= first_read_at for sub in subscriptions)
        assert all(sub.projection_valid_until > sub.last_authoritative_read_at for sub in subscriptions)
    assert (
        sum(request.url.path.endswith(("/subscriptions/567", "/subscriptions/568")) for request in transport.requests)
        == 2
    )


async def test_inventory_competitor_cannot_hide_owned_block_or_reissue_paid_allowance(
    paid_scenario: tuple, postgres_session_factory: sessionmaker[Session]
) -> None:
    factory = postgres_session_factory
    transport, sources, config, subscription_id, _ = paid_scenario
    await reconcile(paid_scenario, factory)
    revision, document = effective(factory)
    assert revision == 1 and document["allowances"][0]["quantity"] == 100
    original = document["allowances"][0]["allowance_id"]
    transport.subscriptions[0]["current_blocking"] = 1
    competitor = deepcopy(transport.subscriptions[0])
    competitor["subscription_id"] = 999
    transport.subscriptions.append(competitor)
    background_recovery.repair_batch(factory, config)
    transport.requests.clear()
    worker = BillingWorker(config, factory, sources.require_lbx())
    try:
        assert await worker.tick(WorkLane.NORMAL)
    finally:
        await worker.aclose()
    assert effective(factory) == (revision + 1, {"grants": [], "allowances": []})
    with factory() as db:
        assert db.get(ExternalSubscription, subscription_id).financial_access_status == "blocked"
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == revision + 1
        allowance = db.scalars(select(PurchasedAllowance)).one()
        assert str(allowance.allowance_id) == original and allowance.quantity == 100
    assert all(request.method == "GET" for request in transport.requests)
