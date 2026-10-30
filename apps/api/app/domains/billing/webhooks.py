"""Atomic redacted inbox and coalesced hint enqueue; no source I/O or fact writes."""

import hashlib
import json
from uuid import uuid4

from app.core.settings import Settings
from app.domains.billing import work
from app.domains.billing.webhook_contracts import CORRELATION_SCHEMA, RECEIPT_SCHEMA, HintReceipt, SubscriptionHint
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.infrastructure.queries import billing_reconciliation, billing_webhooks, billing_work
from app.models import ExternalBillingCustomerBindingState, ExternalBillingWebhookDelivery, WebhookDeliveryState


def receive_hint(factory: SessionFactory, configuration: Settings, hint: SubscriptionHint) -> HintReceipt:
    account = configuration.lbx_external_billing_account_id
    with factory() as db:
        now = as_utc(billing_reconciliation.database_now(db))
        subject = billing_webhooks.subscription_for_hint(
            db,
            account=account,
            tenant=configuration.instance_tenant_id,
            region=configuration.instance_region,
            provider_subscription_id=hint.subscription_id,
        )
        # Unknown/conflicting hints retain hashes only; supplied IDs never route
        # an account, user, product or new binding.
        correlation: dict[str, str | int] = {
            "subject_hash": hashlib.sha256(
                json.dumps([account, hint.subscription_id, hint.agreement_id, hint.customer_id]).encode()
            ).hexdigest()
        }
        queued = False
        if subject is not None:
            sub, customer, purchase = subject
            if (
                sub.external_agreement_id == hint.agreement_id
                and customer.external_billing_account_id == purchase.external_billing_account_id == account
                and customer.user_id == purchase.user_id == sub.user_id
                and purchase.customer_id == sub.customer_id
                and purchase.product_id == sub.product_id
                and purchase.mapping_revision_id == sub.mapping_revision_id
                and customer.provider_origin == configuration.lbx_provider_origin
                and customer.binding_state == ExternalBillingCustomerBindingState.BOUND
                and customer.provider_customer_id is not None
                and (hint.customer_id is None or hint.customer_id == customer.provider_customer_id)
            ):
                work.enroll_subscription(db, sub, hint=True)
                row = billing_work.by_key(db, work.RECONCILIATION, work.key(sub))
                if row.work_state in {"pending", "running"}:
                    correlation.update(
                        subscription_id=str(sub.subscription_id),
                        work_item_id=str(row.work_item_id),
                        enqueue_generation=row.enqueue_generation,
                    )
                    queued = True
        identity = uuid4()
        db.add(
            ExternalBillingWebhookDelivery(
                delivery_id=identity,
                external_billing_account_id=account,
                provider_event_id=None,
                payload_hash=hint.payload_hash,
                correlation_schema_version=CORRELATION_SCHEMA,
                correlation_document=correlation,
                evidence_schema_version=RECEIPT_SCHEMA,
                evidence_document={"event": hint.event},
                processing_state=WebhookDeliveryState.PENDING if queued else WebhookDeliveryState.IGNORED,
                received_at=now,
                processed_at=None if queued else now,
                last_error_classification=None if queued else "correlation_unproven",
            )
        )
        db.commit()
        return HintReceipt(identity, queued)
