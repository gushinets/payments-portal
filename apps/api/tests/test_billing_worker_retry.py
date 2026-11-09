"""A refused inner retry is progress only after the existing owner commits it."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.composition import billing_background
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.work_contracts import WorkClaim, WorkLane
from app.jobs.billing import BillingWorker
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State
from apps.api.tests.support.any709_step1 import step1_settings

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize("kind", [recovery.RECOVERY, recovery.INVENTORY])
@pytest.mark.parametrize("saved", [False, True])
async def test_inner_retry_acknowledgement_controls_worker_progress(
    monkeypatch: pytest.MonkeyPatch,
    kind: str,
    saved: bool,
) -> None:
    now = datetime.now(UTC)
    customer = CustomerOpen(uuid4(), uuid4(), uuid4(), "synthetic-customer", "345")
    claim = WorkClaim(uuid4(), kind, str(customer.customer_id), "owner", 0, now, now + timedelta(seconds=90))
    worker = BillingWorker(step1_settings(), lambda: None, object())
    retries = []

    async def unavailable(*args: Any, **kwargs: Any) -> None:
        raise BillingRefused("billing_busy", 409)

    async def delegate(lane: WorkLane, function: Any, *args: Any, **kwargs: Any) -> Any:
        if function is work.claim_work:
            return claim
        if function is recovery.subject:
            return Kind.CUSTOMER, uuid4(), None, customer, State.UNKNOWN
        if function is recovery.customer_snapshot:
            raise BillingRefused("billing_busy", 409)
        if function is work.retry_work:
            retries.append(kwargs["error"])
            return saved
        if function is recovery.recovery_paused:
            assert kind == recovery.RECOVERY and not saved
            return False
        raise AssertionError(f"Unexpected delegation: {function.__name__}")

    monkeypatch.setattr(billing_background, "recover_customer", unavailable)
    monkeypatch.setattr(worker, "db", delegate)
    try:
        if saved:
            assert await worker.tick(WorkLane.URGENT)
            assert worker.last_progress_at is not None
        else:
            with pytest.raises(BillingRefused, match="billing_work_stale"):
                await worker.tick(WorkLane.URGENT)
            assert worker.last_progress_at is None
        assert retries == ["billing_busy"]
    finally:
        await worker.aclose()
