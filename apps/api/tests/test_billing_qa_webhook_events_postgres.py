"""ANY-715 QA: every supported event is only a durable, owned hint. SIMULATED."""

from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.composition.reconciliation import reconcile_subscription
from app.domains.billing import work
from app.integrations.lbx.webhook import SubscriptionEvent
from app.models import BillingWorkItem, ExternalBillingWebhookDelivery, ExternalSubscription, WebhookDeliveryState
from apps.api.tests.factories.billing_webhook import AUTH_HEADER, AUTH_VALUE, PATH, hint_payload, webhook_settings
from apps.api.tests.test_billing_qa_isolation_postgres import (
    assert_no_access_writes,
    product_snapshot,
)
from apps.api.tests.test_billing_webhook_postgres import (
    anyio_backend as anyio_backend,
    client as client,
    scenario as scenario,
)

pytestmark = [pytest.mark.postgres, pytest.mark.anyio]


@pytest.mark.parametrize("event", SubscriptionEvent)
async def test_billing_qa_webhook_event_queues_owned_and_ignores_unknown(
    client: httpx.AsyncClient,
    scenario: tuple,
    postgres_session_factory: sessionmaker[Session],
    event: SubscriptionEvent,
) -> None:
    transport, sources, _ = scenario
    factory = postgres_session_factory
    with factory() as db:
        subscription_id = db.scalars(select(ExternalSubscription.subscription_id)).one()
    await reconcile_subscription(
        sources.require_lbx(), sources.billing, webhook_settings(), factory=factory, subscription_id=subscription_id
    )
    before = product_snapshot(factory, "proposal_ai")
    expected_generation = (
        next(job["enqueue_generation"] for job in before["queue"] if job["work_kind"] == work.RECONCILIATION) + 1
    )
    request_count = len(transport.requests)
    known = await client.post(PATH, json=hint_payload(event=event.value), headers={AUTH_HEADER: AUTH_VALUE})
    assert known.status_code == 200 and known.json()["outcome"] == "queued"
    unknown = await client.post(
        PATH,
        json=hint_payload(event=event.value, subscription_id=999999),
        headers={AUTH_HEADER: AUTH_VALUE},
    )
    assert unknown.status_code == 200 and unknown.json()["outcome"] == "ignored"
    assert len(transport.requests) == request_count
    after = product_snapshot(factory, "proposal_ai")
    for key in ("subscription", "scope", "observations"):
        assert after[key] == before[key]
    with factory() as db:
        deliveries = {row.delivery_id: row for row in db.scalars(select(ExternalBillingWebhookDelivery))}
        assert len(deliveries) == 2
        queued = deliveries[UUID(known.json()["delivery_id"])]
        ignored = deliveries[UUID(unknown.json()["delivery_id"])]
        assert queued.processing_state == WebhookDeliveryState.PENDING
        assert ignored.processing_state == WebhookDeliveryState.IGNORED
        assert queued.evidence_document == ignored.evidence_document == {"event": event.value}
        assert queued.correlation_document["subscription_id"] == str(before["subscription"]["subscription_id"])
        assert set(ignored.correlation_document) == {"subject_hash"}
        job = db.scalars(
            select(BillingWorkItem).where(
                BillingWorkItem.work_kind == work.RECONCILIATION,
                BillingWorkItem.scope_reference == queued.correlation_document["subscription_id"],
            )
        ).one()
        assert job.enqueue_generation == queued.correlation_document["enqueue_generation"] == expected_generation
        assert job.next_attempt_at <= datetime.now(UTC) and job.lease_owner is None
    assert_no_access_writes(factory)
