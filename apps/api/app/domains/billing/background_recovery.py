"""Shared local recovery scheduling, deadlines and scoped inventory evidence."""

from datetime import timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing import customers, work
from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase
from app.infrastructure.persistence.billing_work import coalesce, ensure_recovery
from app.infrastructure.queries import (
    billing_background as queries,
    billing_customers,
    billing_reconciliation,
    purchases,
    billing_work as work_queries,
)
from app.models import (
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    User,
    ExternalBillingCustomerBindingState as Binding,
    BillingProductAccessScope,
)

RECOVERY = "external_create_recovery"
DEADLINE = "external_create_deadline"
INVENTORY = "customer_inventory"
INVENTORY_SECONDS = 6 * 60 * 60


def enroll_operation(db: Session, operation: ExternalCreateOperation, account: str, *, sent: bool = False) -> None:
    """Caller owns the permanent claim transaction; do not reset send leases."""
    now = as_utc(billing_reconciliation.database_now(db))
    recovery = billing_customers.recovery_work(db, operation.create_operation_id)
    if recovery is not None and (sent or recovery.priority == 0):
        recovery.priority = 1
        recovery.next_attempt_at = now
        if sent:
            recovery.enqueue_generation += 1
    coalesce(
        db,
        kind=DEADLINE,
        key=f"{account}:{operation.create_operation_id}",
        scope_kind="create_operation",
        reference=str(operation.create_operation_id),
        due=as_utc(
            operation.unknown_recovery_deadline_at
            if operation.operation_kind == Kind.CUSTOMER
            else purchases.financial_recovery_deadline(operation, recovery)
        ),
        priority=1,
        payload={"unknown_since": as_utc(operation.unknown_since).isoformat(), "send_fence": str(operation.send_fence)},
        replace_deadline=True,
    )


def repair_batch(factory: SessionFactory, configuration: Settings) -> int:
    with factory() as db:
        identities = [op.create_operation_id for op in queries.missing_operations(db, configuration)]
    repaired = 0
    for identity in identities:
        try:
            repaired += int(_repair_operation(factory, configuration, identity))
        except BillingRefused as error:
            if error.code != "billing_busy":
                raise
            # Another local flow owns the user; the next sweep retries the same
            # original missing set. No no-send/result evidence is manufactured.
    with factory() as db:
        inventory = queries.missing_inventory(db, configuration)
        now = as_utc(billing_reconciliation.database_now(db))
        for customer in inventory:
            coalesce(
                db,
                kind=INVENTORY,
                key=f"{customer.external_billing_account_id}:{customer.customer_id}",
                scope_kind="customer",
                reference=str(customer.customer_id),
                due=now,
                priority=0,
                payload={},
            )
        db.commit()
        return max(repaired, len(inventory))


def _repair_operation(factory: SessionFactory, configuration: Settings, identity: UUID) -> bool:
    with factory() as db:
        found = queries.operation_subject(db, identity)
        if found is None:
            return False
        op, customer = found
        customers.lock_user(db, customer.user_id)
        if op.operation_kind == Kind.CUSTOMER:
            billing_customers.lock_customer(db, customer.customer_id)
            op = billing_customers.customer_operation(db, customer.customer_id)
        else:
            row = purchases.owned(db, customer.user_id, op.purchase_intent_id, lock=True)
            operations = purchases.operations(db, row.purchase_intent_id, lock=True)
            op = next(item for item in operations if item.create_operation_id == identity)
        db.refresh(op)
        if op.operation_state not in {State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW}:
            return False
        valid = customer.provider_origin == configuration.lbx_provider_origin
        try:
            if op.operation_kind == Kind.CUSTOMER:
                customers._receipt_id(op)
                valid = valid and op.request_correlation_key == customer.billing_customer_key
            else:
                evidence = service.accepted(row)
                service._verify_original_consent(db, row, evidence)
                service._operation(db, op)
                held = purchases.hold(db, customer.user_id, row.product_id)
                valid = (
                    valid
                    and evidence.provider_origin == customer.provider_origin
                    and op.recovery_hint_schema_version == financial.FINANCIAL_HINT_SCHEMA
                    and held is not None
                    and held.purchase_intent_id == row.purchase_intent_id
                )
        except (ValueError, service.PurchaseRefused, BillingRefused):
            valid = False
        now = as_utc(billing_reconciliation.database_now(db))
        ensure_recovery(db, str(identity), now)
        row = billing_customers.recovery_work(db, identity)
        if row.work_state in {"done", "completed"}:
            row.work_state = "pending"
            row.next_attempt_at = now
        enroll_operation(db, op, configuration.lbx_external_billing_account_id)
        if not valid:
            row.work_state = "invalid"
            row.priority = 1
            row.last_error_classification = "billing_recovery_unproven"
            deadline = work_queries.by_key(db, DEADLINE, f"{configuration.lbx_external_billing_account_id}:{identity}")
            deadline.work_state = "invalid"
            deadline.last_error_classification = "billing_recovery_unproven"
        db.commit()
        return True


def subject(
    factory: SessionFactory, configuration: Settings, claim: WorkClaim
) -> tuple[Kind, UUID, UUID | None, CustomerOpen, State]:
    with factory() as db:
        found = queries.operation_subject(db, UUID(claim.reference))
        if found is None:
            raise BillingRefused("billing_recovery_unproven", 409)
        op, customer = found
        user = db.get(User, customer.user_id)
        if (
            customer.external_billing_account_id != configuration.lbx_external_billing_account_id
            or customer.provider_origin != configuration.lbx_provider_origin
            or user is None
            or (user.tenant_id, user.region) != (configuration.instance_tenant_id, configuration.instance_region)
        ):
            raise BillingRefused("billing_recovery_unproven", 409)
        customer_op = (
            op if op.operation_kind == Kind.CUSTOMER else billing_customers.customer_operation(db, customer.customer_id)
        )
        if customer_op is None or customer_op.request_correlation_key != customer.billing_customer_key:
            raise BillingRefused("billing_identity_unproven", 409)
        work.verify_operation_claim(db, claim, op.create_operation_id)  # Queue lock last.
        return (
            op.operation_kind,
            customer.user_id,
            op.purchase_intent_id,
            customers._snapshot(customer, customer_op),
            op.operation_state,
        )


def customer_snapshot(
    factory: SessionFactory, configuration: Settings, identity: UUID
) -> tuple[CustomerOpen, tuple[Purchase, ...]]:
    with factory() as db:
        customer = queries.customer(db, identity)
        if customer is None or customer.external_billing_account_id != configuration.lbx_external_billing_account_id:
            raise BillingRefused("billing_identity_unproven", 409)
        user = db.get(User, customer.user_id)
        if user is None or (user.tenant_id, user.region) != (
            configuration.instance_tenant_id,
            configuration.instance_region,
        ):
            raise BillingRefused("billing_identity_unproven", 409)
        rows = queries.customer_purchases(db, identity)
        if len(rows) >= 100:
            raise BillingRefused("purchase_inventory_incomplete", 409)
        snapshots = tuple(service._snapshot(db, row) for row in rows)
        for row, snapshot in zip(rows, snapshots):
            service._verify_original_consent(db, row, snapshot.accepted)
        op = billing_customers.customer_operation(db, identity)
        if (
            op is None
            or customer.provider_origin != configuration.lbx_provider_origin
            or op.request_correlation_key != customer.billing_customer_key
            or op.bound_external_object_id != customer.provider_customer_id
            or op.operation_state != State.BOUND
            or customer.binding_state != Binding.BOUND
        ):
            raise BillingRefused("billing_identity_unproven", 409)
        return customers._snapshot(customer, op), snapshots


def finish_recovery(factory: SessionFactory, claim: WorkClaim) -> None:
    with factory() as db:
        found = queries.operation_subject(db, UUID(claim.reference))
        if found is None:
            raise BillingRefused("billing_recovery_unproven", 409)
        op, customer = found
        customers.lock_user(db, customer.user_id)
        if op.purchase_intent_id is not None:
            purchase = service._snapshot(db, purchases.owned(db, customer.user_id, op.purchase_intent_id))
            service._locked(db, purchase)
            purchases.operations(db, purchase.id, lock=True)
        else:
            billing_customers.lock_customer(db, customer.customer_id)
            billing_customers.customer_operation(db, customer.customer_id)
        db.refresh(op)
        queue = billing_customers.recovery_work(db, op.create_operation_id)
        if queue is not None and queue.lease_owner != claim.owner:
            return  # Shared bind already finalized, or a newer owner/hint won.
        row = work.verify_claim(db, claim)
        done = op.operation_state in {State.PENDING, State.PROVEN_NOT_SENT, State.BOUND}
        now = as_utc(billing_reconciliation.database_now(db))
        interval = min(work.URGENT_SECONDS, 30 * 2 ** min(max(row.attempt_count - 1, 0), 4))
        work.finish(
            db,
            row,
            claim,
            due=None
            if done
            else max(
                now + timedelta(seconds=1),
                claim.started_at + timedelta(seconds=work.spread_seconds(claim.id, interval)),
            ),
        )
        db.commit()


def apply_deadline(factory: SessionFactory, claim: WorkClaim) -> None:
    """No provider I/O, never converts completed no-send evidence into UNKNOWN."""
    with factory() as db:
        found = queries.operation_subject(db, UUID(claim.reference))
        if found is None:
            raise BillingRefused("billing_recovery_unproven", 409)
        op, customer = found
        customers.lock_user(db, customer.user_id)
        if op.operation_kind == Kind.CUSTOMER:
            billing_customers.lock_customer(db, customer.customer_id)
            op = billing_customers.customer_operation(db, customer.customer_id)
            purchase = None
        else:
            purchase = purchases.owned(db, customer.user_id, op.purchase_intent_id, lock=True)
            service._locked(db, service._snapshot(db, purchase))
            op = next(
                item
                for item in purchases.operations(db, purchase.purchase_intent_id, lock=True)
                if item.create_operation_id == op.create_operation_id
            )
        row = work.verify_claim(db, claim)
        now = as_utc(billing_reconciliation.database_now(db))
        deadline = (
            op.unknown_recovery_deadline_at
            if op.operation_kind == Kind.CUSTOMER
            else purchases.financial_recovery_deadline(op, billing_customers.recovery_work(db, op.create_operation_id))
        )
        deadline = as_utc(deadline) if deadline else None
        due = deadline if deadline and deadline > now else None
        if due is None and deadline and op.operation_state in {State.POSSIBLE_SEND, State.UNKNOWN}:
            reason = "external_create_outcome_unknown:" + op.operation_kind.value
            if purchase is None:
                customers._manual_review(db, op, reason)
            else:
                financial._review(db, purchase, op, reason)
        work.finish(db, row, claim, due=due)
        db.commit()


def apply_inventory(
    factory: SessionFactory, claim: WorkClaim, conflicts: tuple[Purchase, ...], reason: str | None
) -> None:
    """Fence all scoped conflicts and finish their shared customer job once."""
    with factory() as db:
        customer = queries.customer(db, UUID(claim.reference))
        customers.lock_user(db, customer.user_id)
        locked = []
        for purchase in conflicts:
            row = service._locked(db, purchase)
            operations = purchases.operations(db, row.purchase_intent_id, lock=True)
            scope = billing_reconciliation.scope(db, purchase.user_id, row.product_id)
            if scope is None:
                scope = BillingProductAccessScope(
                    user_id=purchase.user_id, product_id=row.product_id, primary_subscription_id=None
                )
                db.add(scope)
                db.flush()
            subscription = purchases.linked_subscription(db, purchase.id)
            current = service._snapshot(db, row)
            if current.accepted != purchase.accepted or current.operations != purchase.operations:
                raise BillingRefused("billing_work_stale", 409)
            service._verify_original_consent(db, row, current.accepted)
            target = next(op for op in operations if op.operation_kind == Kind.SUBSCRIPTION)
            locked.append((purchase, row, target, scope, subscription))
        queue = work.verify_claim(db, claim)
        for purchase, row, target, scope, subscription in locked:
            financial._review(db, row, target, "customer_inventory_conflict")
            from app.models import (
                BillingStateObservation,
                BillingStateObservationKind,
                ExternalSubscriptionCommercialAccessStatus as Commercial,
            )

            if subscription is not None:
                subscription.commercial_access_status = Commercial.INELIGIBLE
            db.add(
                BillingStateObservation(
                    observation_kind=BillingStateObservationKind.TARGET_PRODUCT_DISCOVERY,
                    external_billing_account_id=customer.external_billing_account_id,
                    user_id=purchase.user_id,
                    product_id=purchase.accepted.selection.product_id,
                    access_scope_id=scope.access_scope_id,
                    subscription_id=subscription.subscription_id if subscription else None,
                    observed_at=as_utc(billing_reconciliation.database_now(db)),
                    evidence_schema_version="customer-inventory:v1",
                    evidence_document={"purchase_intent_id": str(purchase.id), "reason": "competing_inventory"},
                    completeness_classification="conflict",
                    result_classification="review_required",
                    resulting_access_revision=None,
                )
            )
        now = as_utc(billing_reconciliation.database_now(db))
        interval = work.URGENT_SECONDS if reason else INVENTORY_SECONDS
        work.finish(
            db,
            queue,
            claim,
            due=max(
                now + timedelta(seconds=1),
                claim.started_at + timedelta(seconds=work.spread_seconds(claim.id, interval)),
            ),
            error=reason,
        )
        db.commit()
