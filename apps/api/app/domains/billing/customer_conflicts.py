"""Persist paired-customer conflicts observed during shared financial recovery."""

from uuid import UUID

from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.customer_reviews import record_customer_conflict as record_customer_conflict_in_transaction
from app.domains.billing.customers import lock_customer, lock_user
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import Purchase
from app.domains.purchases.inventory import require_current_attempt
from app.infrastructure.queries import billing_background, billing_customers, purchases


def record_customer_conflict(
    factory: SessionFactory,
    expected: CustomerOpen,
    claim: WorkClaim | None,
    *,
    attempts: tuple[Purchase, ...] = (),
    provider_id: str | None = None,
) -> None:
    with factory() as db:
        initial = billing_background.customer(db, expected.customer_id)
        lock_user(db, initial.user_id)
        for purchase in attempts:
            require_current_attempt(db, purchase, expected.customer_id)
        if claim is not None and claim.kind == "customer_inventory":
            if claim.reference != str(expected.customer_id):
                raise BillingRefused("billing_work_stale", 409)
        elif claim is not None:
            subject = billing_background.operation_subject(db, UUID(claim.reference))
            if subject is None or subject[1].customer_id != expected.customer_id:
                raise BillingRefused("billing_work_stale", 409)
            operation, _ = subject
            if operation.purchase_intent_id is not None:
                purchases.owned(db, initial.user_id, operation.purchase_intent_id, lock=True)
                purchases.operations(db, operation.purchase_intent_id, lock=True)
        customer = lock_customer(db, expected.customer_id)
        operation = billing_customers.customer_operation(db, expected.customer_id)
        if (
            operation is None
            or operation.create_operation_id != expected.operation_id
            or operation.send_fence != expected.fence
            or customer.billing_customer_key != expected.outer_key
        ):
            raise BillingRefused("billing_customer_pending", 409)
        record_customer_conflict_in_transaction(db, customer, operation, provider_id=provider_id, ambiguous=False)
        from app.domains.billing.paid_access import reduce_paid_access

        reduce_paid_access(db, customer.user_id)
        if claim is not None:
            from app.domains.billing.work import verify_claim

            verify_claim(db, claim)
        db.commit()
