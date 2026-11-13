"""Shared read-only validation for source claims and committed receipts."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import lock_customer, lock_user
from app.domains.billing.reconciliation_contracts import (
    RECONCILIATION_READ_SCHEMAS,
    ReconciliationResult,
    ReconciliationSubject,
    SubscriptionProof,
)
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.infrastructure.queries import billing_reconciliation as queries, purchases
from app.infrastructure.queries.billing_customers import customer_operation
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    ExternalBillingCustomer,
    ExternalSubscription,
    ExternalCreateOperation,
    PurchaseIntent,
    User,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperationState as State,
)


@dataclass(frozen=True)
class ClaimedSource:
    user: User
    customer: ExternalBillingCustomer
    customer_operation: ExternalCreateOperation
    row: PurchaseIntent
    operations: list[ExternalCreateOperation]
    scope: BillingProductAccessScope
    subscription: ExternalSubscription
    now: datetime


def source_receipt_current(
    db: Session, source: ReconciliationResult, sub: ExternalSubscription, *, require_latest: bool = True
) -> bool:
    """Caller holds the user lock through its decision; never renew source authority."""
    observation = db.get(BillingStateObservation, source.observation_id)
    document = source.proof.document()
    document.update(reads=list(source.proof.reads), reasons=list(source.proof.reasons))
    return (
        sub.subscription_id == source.subject.subscription_id
        and (not require_latest or sub.latest_observation_id == source.observation_id)
        and sub.reconciliation_fencing_token == source.subject.fence
        and sub.external_subscription_id == source.subject.provider_subscription_id
        and sub.external_agreement_id == source.subject.agreement_id
        and sub.purchase_intent_id == source.purchase.id
        and observation is not None
        and observation.evidence_schema_version in RECONCILIATION_READ_SCHEMAS
        and observation.subscription_id == sub.subscription_id
        and observation.user_id == source.purchase.user_id
        and observation.product_id == sub.product_id
        and observation.external_billing_account_id == source.purchase.account_id
        and all(observation.evidence_document.get(key) == value for key, value in document.items())
    )


def lock_source_claim(db: Session, subject: ReconciliationSubject, proof: SubscriptionProof) -> ClaimedSource:
    """Lock and validate the original claim; never write facts or paid state."""
    purchase = subject.purchase
    user = lock_user(db, purchase.user_id)
    customer = lock_customer(db, purchase.customer_id)
    customer_op = customer_operation(db, customer.customer_id)
    row = service._locked(db, purchase)
    operations = purchases.operations(db, purchase.id, lock=True)
    scope = queries.scope(db, purchase.user_id, purchase.accepted.selection.product_id)
    current = queries.subscription(db, subject.subscription_id, lock=True)
    now = as_utc(queries.database_now(db))
    if (
        current is None
        or scope is None
        or current.reconciliation_lease_owner != subject.owner
        or current.reconciliation_fencing_token != subject.fence
        or current.reconciliation_lease_expires_at is None
        or as_utc(current.reconciliation_lease_expires_at) <= now
        or proof.read_started_at > proof.read_finished_at
        or proof.read_started_at < subject.claimed_at
        or proof.read_finished_at > now
        or proof.read_finished_at >= subject.lease_expires_at
    ):
        raise BillingRefused("subscription_reconciliation_stale", 409)
    if (
        current.purchase_intent_id != purchase.id
        or current.user_id != purchase.user_id
        or current.product_id != purchase.accepted.selection.product_id
        or current.customer_id != purchase.customer_id
        or current.mapping_revision_id != purchase.accepted.meaning.revision_id
        or current.external_billing_account_id != purchase.account_id
        or current.external_subscription_id != subject.provider_subscription_id
        or current.external_agreement_id != subject.agreement_id
        or service.accepted(row) != purchase.accepted
        or customer.binding_state != Binding.BOUND
        or customer.provider_customer_id != subject.customer.provider_id
        or customer.billing_customer_key != subject.customer.outer_key
        or customer.provider_origin != purchase.accepted.provider_origin
        or customer_op is None
        or customer_op.create_operation_id != subject.customer.operation_id
        or customer_op.request_correlation_key != subject.customer.outer_key
        or customer_op.send_fence != subject.customer.fence
        or customer_op.operation_state != State.BOUND
        or customer_op.bound_external_object_id != subject.customer.provider_id
        or {
            (
                op.create_operation_id,
                op.operation_kind,
                op.request_correlation_key,
                op.bound_external_object_id,
                op.send_fence,
                op.operation_state,
            )
            for op in operations
        }
        != {(op.id, op.kind, op.key, op.bound_id, op.fence, op.state) for op in purchase.operations}
    ):
        raise BillingRefused("subscription_provenance_changed", 409)
    latest = db.get(BillingStateObservation, current.latest_observation_id) if current.latest_observation_id else None
    if latest is not None and as_utc(latest.observed_at) > proof.read_started_at:
        raise BillingRefused("subscription_reconciliation_stale", 409)
    service._verify_original_consent(db, row, purchase.accepted)
    return ClaimedSource(user, customer, customer_op, row, operations, scope, current, now)
