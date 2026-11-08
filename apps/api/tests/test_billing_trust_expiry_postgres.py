"""Trust expiry retains the complete read which established the current window."""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.sources import SourceResources
from app.domains.billing import background_recovery, work
from app.domains.billing.work_contracts import WorkLane
from app.domains.purchases.contracts import Purchase
from app.models import BillingStateObservation, BillingWorkItem, ExternalSubscription
from apps.api.tests.support.any709_step1 import step1_settings
from apps.api.tests.support.any709_step3 import PurchaseTransport
from apps.api.tests.test_billing_subscription_reconciliation_postgres import (
    activate,
    run,
    scenario as scenario,
    snapshot,
)

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.mark.parametrize(
    ("reading", "queue"),
    [
        (reading, queue)
        for reading in ("identity", "commercial", "incomplete", "negative", "renewed", "blocked")
        for queue in ("normal", "missing")
    ]
    + [(reading, "old_payload") for reading in ("identity", "commercial", "negative")],
)
async def test_trust_expiry_preserves_its_source_observation(
    scenario: tuple[PurchaseTransport, SourceResources, Purchase],
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
    reading: str,
    queue: str,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    activate(transport)
    if reading == "renewed":
        with factory() as db:
            # Projection fences are BIGINT, including the persisted proof field.
            db.scalar(select(ExternalSubscription)).reconciliation_fencing_token = 2**31 - 2
            db.commit()
    first = await run(sources, factory)
    original = snapshot(factory)
    assert first.completeness_classification == "complete" and first.result_classification == "COMPLETE_MATCH"
    with factory() as db:
        job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
        before_payload, before_generation = dict(job.payload_document), job.enqueue_generation
    assert UUID(before_payload["supporting_observation_id"]) == first.observation_id

    if reading == "identity":
        transport.subscriptions[0]["agreement_id"] = 999
    elif reading == "commercial":
        transport.subscriptions[0]["services"][0]["price"] = 15
    elif reading in {"incomplete", "negative"}:
        transport.subscriptions[0]["total_price"] = None
    if reading in {"negative", "blocked"}:
        transport.subscriptions[0]["current_blocking"] = 1
    second = await run(sources, factory)
    current = snapshot(factory)
    if reading in {"identity", "commercial"}:
        assert (
            second.result_classification
            == f"subscription_{'identity_conflict' if reading == 'identity' else 'commercial_mismatch'}"
        )
        assert current[4:6] == original[4:6]
        assert current[6] == second.observation_id
        assert current[2:4] == ("blocked", "ineligible")
    elif reading == "incomplete":
        assert current == original
    elif reading == "negative":
        assert current[4:6] == original[4:6] and current[6] == second.observation_id
        assert current[2:4] == ("blocked", "eligible")
    else:
        assert second.result_classification == "COMPLETE_MATCH"
        assert current[4] > original[4]
        if reading == "blocked":
            assert current[2] == "blocked"
    renewed = reading in {"renewed", "blocked"}
    expected = second.observation_id if renewed else first.observation_id

    with factory() as db:
        job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
        assert UUID(job.payload_document["supporting_observation_id"]) == expected
        assert job.enqueue_generation == before_generation + renewed
        if not renewed:
            assert job.payload_document == before_payload
        if queue == "missing":
            db.execute(delete(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
        elif queue == "old_payload":
            # Reproduce an expiry row persisted by the pre-fix scheduler.
            job.payload_document = {**job.payload_document, "supporting_observation_id": str(second.observation_id)}
        db.commit()
    if queue == "missing":
        assert work.enroll_batch(factory, step1_settings()) == 1
        assert work.enroll_batch(factory, step1_settings()) == 0
        with factory() as db:
            job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
            assert UUID(job.payload_document["supporting_observation_id"]) == expected

    # Advance the DB clock, retaining real proof/apply, queue and expiry writers.
    monkeypatch.setattr(work.billing_reconciliation, "database_now", lambda db: current[5] + timedelta(seconds=1))
    requests = len(transport.requests)
    for _ in range(10):
        claim = work.claim_work(factory, step1_settings(), WorkLane.LOCAL)
        assert claim is not None
        if claim.kind == work.EXPIRY:
            break
        assert claim.kind == background_recovery.DEADLINE
        background_recovery.apply_deadline(factory, claim)
    assert claim.kind == work.EXPIRY
    work.expire_trust(factory, claim)
    assert len(transport.requests) == requests
    assert snapshot(factory) == current
    with factory() as db:
        expiry = db.scalar(
            select(BillingStateObservation).where(
                BillingStateObservation.evidence_schema_version == "subscription-trust-expiry:v1"
            )
        )
        assert expiry.basis_observation_id == expected
        assert UUID(expiry.evidence_document["supporting_observation_id"]) == expected
        assert expiry.effective_at == current[5] and expiry.resulting_access_revision is None
        job = db.scalar(select(BillingWorkItem).where(BillingWorkItem.work_kind == work.EXPIRY))
        assert job.work_state == "completed" and job.payload_document == expiry.evidence_document
    assert work.enroll_batch(factory, step1_settings()) == 0
    assert work.claim_work(factory, step1_settings(), WorkLane.LOCAL) is None
