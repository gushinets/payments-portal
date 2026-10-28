"""Persist paired-customer conflicts observed during shared financial recovery."""

from uuid import UUID

from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.customers import lock_user, mark_customer_identity_conflict
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.queries import billing_background, billing_customers, purchases


def record_customer_conflict(factory: SessionFactory, expected: CustomerOpen, claim: WorkClaim | None) -> None:
    with factory() as db:
        initial = billing_background.customer(db, expected.customer_id)
        lock_user(db, initial.user_id)
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
        customer = billing_customers.lock_customer(db, expected.customer_id)
        operation = billing_customers.customer_operation(db, expected.customer_id)
        if (
            operation is None
            or operation.send_fence != expected.fence
            or customer.billing_customer_key != expected.outer_key
        ):
            raise BillingRefused("billing_customer_pending", 409)
        if claim is not None:
            from app.domains.billing.work import verify_claim

            verify_claim(db, claim)
        mark_customer_identity_conflict(db, customer, operation)
        db.commit()
