"""Local versions and admission effects for the shared scoped inventory."""

from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from app.domains.billing.customers import lock_customer
from app.domains.billing.operator_cases import audited_subscription_candidates, audited_subscription_reads
from app.domains.billing.operator_contracts import (
    AUDITED_SUBSCRIPTION_SCHEMA,
    AuditedSubscriptionEvidence,
    AuditedSubscriptionObservation,
)
from app.domains.billing.customer_reviews import customer_admission_reviews
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase
from app.domains.purchases.inventory_contracts import InventoryResult, InventoryStale
from app.infrastructure.queries import purchases as queries
from app.infrastructure.queries.billing_customers import customer_operation
from app.models import (
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperationState as State,
)


def same_purchase(current: Purchase, expected: Purchase) -> bool:
    return (
        current.id == expected.id
        and current.accepted == expected.accepted
        and current.held == expected.held
        and current.state == expected.state
        and tuple(op.admission_snapshot() for op in current.operations)
        == tuple(op.admission_snapshot() for op in expected.operations)
    )


def validate_inventory(db: Session, result: InventoryResult) -> dict[str, AuditedSubscriptionObservation]:
    """Caller holds the existing user lock; never refresh the attempt's subject."""
    customer = lock_customer(db, result.customer.customer_id)
    operation = customer_operation(db, customer.customer_id)
    if operation is not None:
        customer_admission_reviews(db, customer, operation)
    if (
        customer.binding_state != Binding.BOUND
        or customer.provider_customer_id != result.customer.provider_id
        or customer.billing_customer_key != result.customer.outer_key
        or operation is None
        or operation.create_operation_id != result.customer.operation_id
        or operation.send_fence != result.customer.fence
        or operation.operation_state != State.BOUND
        or operation.bound_external_object_id != result.customer.provider_id
    ):
        raise InventoryStale()
    # Also reject new held purchases introduced during the source reads.
    from app.infrastructure.queries.billing_background import customer_purchases

    rows = customer_purchases(db, customer.customer_id)
    if {row.purchase_intent_id for row in rows} != {item.id for item in result.purchases}:
        raise InventoryStale()
    # A late case can close after collection and replace its open-case fence
    # with a competitor that this attempt never point-read.
    if (
        rows
        and audited_subscription_candidates(db, customer.customer_id, customer.external_billing_account_id)
        != result.audited_candidates
    ):
        raise InventoryStale()
    reads = (
        audited_subscription_reads(db, result.customer, result.purchases[0], result.audited_candidates)
        if result.purchases
        else {}
    )
    if frozenset(read.id for read in reads.values()) != result.audited_observation_ids:
        raise InventoryStale()
    for expected in result.purchases:
        row = service._locked(db, expected)
        queries.operations(db, expected.id, lock=True)
        if not same_purchase(service._snapshot(db, row), expected):
            raise InventoryStale()
        service._verify_original_consent(db, row, expected.accepted)
    return reads


def save_audited_subscription_reads(
    factory: SessionFactory,
    result: InventoryResult,
    updates: dict[str, tuple[datetime, AuditedSubscriptionEvidence]],
    claim: WorkClaim | None,
) -> InventoryResult:
    from app.domains.billing.customers import lock_user
    from app.domains.billing.work import verify_claim

    purchase = result.purchases[0]
    with factory() as db:
        lock_user(db, purchase.user_id)
        previous = validate_inventory(db, result)
        if claim is not None:
            verify_claim(db, claim)
        observation_ids = {key: read.id for key, read in previous.items()}
        for external_id, (finished, evidence) in updates.items():
            if external_id in previous and as_utc(previous[external_id].observed_at) >= finished:
                raise InventoryStale()
            identity = uuid4()
            db.add(
                BillingStateObservation(
                    observation_id=identity,
                    observation_kind=BillingStateObservationKind.AUDITED_SUBSCRIPTION_READ,
                    external_billing_account_id=purchase.account_id,
                    user_id=purchase.user_id,
                    observed_at=finished,
                    work_item_id=claim.id if claim else None,
                    evidence_schema_version=AUDITED_SUBSCRIPTION_SCHEMA,
                    evidence_document=evidence.model_dump(mode="json"),
                    completeness_classification="candidate_proof",
                    result_classification=evidence.conclusion.value,
                )
            )
            observation_ids[external_id] = identity
        db.commit()
    return replace(result, audited_observation_ids=frozenset(observation_ids.values()))


def invalidate_unsent(db: Session, purchase: Purchase) -> bool:
    """Invalidate admission without changing no-send evidence or creating review."""
    operations = queries.operations(db, purchase.id, lock=True)
    changed = False
    for operation in operations:
        if operation.bound_external_object_id is None and operation.operation_state in {
            State.PENDING,
            State.PROVEN_NOT_SENT,
        }:
            operation.send_fence = uuid4()
            changed = True
    return changed


def block_admission(factory: SessionFactory, result: InventoryResult, purchase: Purchase) -> None:
    with factory() as db:
        service._locked(db, purchase)
        validate_inventory(db, result)
        if invalidate_unsent(db, purchase):
            from app.core.time import utc_now
            from app.models import PurchaseIntentState

            row = service._locked(db, purchase)
            row.state = PurchaseIntentState.AWAITING_EXTERNAL_RESULT
            row.state_updated_at = utc_now()
        db.commit()
