"""Source account ambiguity cannot suspend already-issued local access deadlines."""

import pytest
from pydantic import SecretStr
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, sessionmaker

from app.domains.billing import work
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.work_contracts import WorkLane
from app.domains.identity.services.auth import as_utc
from app.infrastructure.queries import billing_reconciliation
from app.jobs.billing import BillingWorker
from app.models import AccessInvalidationOutbox, BillingWorkItem, ExternalBillingCustomer, PurchasedAllowance
from apps.api.tests.test_paid_access_postgres import effective, reconcile
from apps.api.tests.test_paid_access_recovery_postgres import expiry

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("configured", [True, False])
@pytest.mark.parametrize("repair", [False, True], ids=["existing-deadline", "missing-deadline"])
async def test_local_expiry_survives_ambiguous_source_accounts(
    paid_scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    configured: bool,
    repair: bool,
) -> None:
    factory = postgres_session_factory
    transport, sources, config, _, user_id = paid_scenario
    await reconcile(paid_scenario, factory)
    before = effective(factory)
    deadline = as_utc(expiry(factory).next_attempt_at)
    with factory() as db:
        db.add(
            ExternalBillingCustomer(
                external_billing_account_id="historical-conflicting-account",
                user_id=user_id,
                billing_customer_key="synthetic-conflicting-customer",
                provider_origin=config.lbx_provider_origin,
            )
        )
        if repair:
            db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
        db.commit()
    if repair:
        work.ensure_sweep(factory, config)
    if not configured:
        # Preserve origin while disabling source authentication.
        config = config.model_copy(update={"lbx_server_password": SecretStr("")})
    monkeypatch.setattr(billing_reconciliation, "database_now", lambda db: deadline)
    transport.requests.clear()
    worker = BillingWorker(config, factory, sources.require_lbx() if configured else None)
    try:
        assert work.inspect_backlog(factory, config)[0] > 0
        source_refusals = 0
        for _ in range(10):
            if effective(factory)[0] > before[0]:
                break
            try:
                assert await worker.tick(WorkLane.LOCAL)
            except BillingRefused as error:
                # Source enrollment still refuses ambiguity, after local repair commits.
                assert repair and configured and error.code == "billing_connection_conflict"
                source_refusals += 1
        assert source_refusals == int(repair and configured)
        assert effective(factory) == (before[0] + 1, {"grants": [], "allowances": []})
        if configured:
            with pytest.raises(BillingRefused, match="billing_connection_conflict"):
                await worker.tick(WorkLane.URGENT)
        else:
            assert not await worker.tick(WorkLane.URGENT)
        assert work.inspect_backlog(factory, config)[0] > 0
        assert transport.requests == []
    finally:
        await worker.aclose()
    with factory() as db:
        assert db.scalar(select(AccessInvalidationOutbox.pending_revision)) == before[0] + 1
        assert db.scalar(select(func.count()).select_from(PurchasedAllowance)) == 1
