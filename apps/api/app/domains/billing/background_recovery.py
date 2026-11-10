"""Local uncertain-create recovery, pause and notification transactions."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing import customers, work
from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.customer_scope import connection_account
from app.domains.billing.customer_reviews import record_customer_review
from app.domains.billing.work_contracts import WorkClaim, RecoveryEscalation
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
    ExternalBillingCustomer,
)

RECOVERY = "external_create_recovery"
DEADLINE = "external_create_deadline"
INVENTORY = "customer_inventory"
INVENTORY_SECONDS = 6 * 60 * 60


def _recovery_deadline(db: Session, op: ExternalCreateOperation) -> datetime | None:
    return (
        op.unknown_recovery_deadline_at
        if op.operation_kind == Kind.CUSTOMER
        else purchases.financial_recovery_deadline(op, billing_customers.recovery_work(db, op.create_operation_id))
    )


def _pause_recovery(db: Session, op: ExternalCreateOperation, account: str) -> None:
    """Caller holds business locks; revoke automatic work, never its scope hold."""
    row = billing_customers.recovery_work(db, op.create_operation_id)
    if row is not None:
        row.work_state = "paused"
        row.priority = 1
        row.lease_owner = None
        row.lease_expires_at = None
        row.last_error_classification = "recovery_deadline_reached"
    deadline = work_queries.by_key(db, DEADLINE, f"{account}:{op.create_operation_id}")
    if deadline is None:
        enroll_operation(db, op, account)
    elif deadline.work_state == "completed" and not deadline.payload_document.get("notification_sent"):
        deadline.work_state = "pending"
        deadline.next_attempt_at = billing_reconciliation.database_now(db)


def pause_expired_recovery(db: Session, op: ExternalCreateOperation, account: str) -> bool:
    """Caller holds business locks and verifies the automatic queue claim."""
    deadline = _recovery_deadline(db, op)
    if (
        op.operation_state in {State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW}
        and op.bound_external_object_id is None
        and deadline is not None
        and as_utc(deadline) <= as_utc(billing_reconciliation.database_now(db))
    ):
        _pause_recovery(db, op, account)
        return True
    return False


def hint_inventory(db: Session, customer: ExternalBillingCustomer) -> None:
    coalesce(
        db,
        kind=INVENTORY,
        key=f"{customer.external_billing_account_id}:{customer.customer_id}",
        scope_kind="customer",
        reference=str(customer.customer_id),
        due=as_utc(billing_reconciliation.database_now(db)),
        priority=1,
        payload={},
        hint=True,
    )


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
        identities = [
            op.create_operation_id
            for op in queries.missing_operations(db, configuration, account=connection_account(db, configuration))
        ]
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
        inventory = queries.missing_inventory(db, configuration, account=connection_account(db, configuration))
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
            customers.lock_customer(db, customer.customer_id)
            op = billing_customers.customer_operation(db, customer.customer_id)
        else:
            row = purchases.owned(db, customer.user_id, op.purchase_intent_id, lock=True)
            operations = purchases.operations(db, row.purchase_intent_id, lock=True)
            op = next(item for item in operations if item.create_operation_id == identity)
        db.refresh(op)
        if op.operation_state not in {State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW} or (
            op.operation_kind != Kind.CUSTOMER and op.bound_external_object_id is not None
        ):
            return False
        valid = (
            customer.provider_origin == configuration.lbx_provider_origin
            and customer.external_billing_account_id == connection_account(db, configuration)
        )
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
        enroll_operation(db, op, customer.external_billing_account_id)
        if not valid:
            row.work_state = "invalid"
            row.priority = 1
            row.last_error_classification = "billing_recovery_unproven"
            deadline = work_queries.by_key(db, DEADLINE, f"{customer.external_billing_account_id}:{identity}")
            deadline.work_state = "invalid"
            deadline.last_error_classification = "billing_recovery_unproven"
        db.commit()
        return True


def subject(
    factory: SessionFactory, configuration: Settings, claim: WorkClaim
) -> tuple[Kind, UUID, UUID | None, CustomerOpen, State] | None:
    with factory() as db:
        found = queries.operation_subject(db, UUID(claim.reference))
        if found is None:
            raise BillingRefused("billing_recovery_unproven", 409)
        op, customer = found
        customers.lock_user(db, customer.user_id)
        customers.lock_customer(db, customer.customer_id)
        if op.operation_kind == Kind.CUSTOMER:
            op = billing_customers.customer_operation(db, customer.customer_id)
        else:
            purchase = purchases.owned(db, customer.user_id, op.purchase_intent_id, lock=True)
            op = next(
                item
                for item in purchases.operations(db, purchase.purchase_intent_id, lock=True)
                if item.create_operation_id == op.create_operation_id
            )
        db.refresh(op)
        db.refresh(customer)
        user = db.get(User, customer.user_id)
        if (
            customer.external_billing_account_id != connection_account(db, configuration)
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
        if pause_expired_recovery(db, op, customer.external_billing_account_id):
            db.commit()
            return None
        return (
            op.operation_kind,
            customer.user_id,
            op.purchase_intent_id,
            customers._snapshot(customer, customer_op, user),
            op.operation_state,
        )


def customer_snapshot(
    factory: SessionFactory, configuration: Settings, identity: UUID
) -> tuple[CustomerOpen, tuple[Purchase, ...]]:
    with factory() as db:
        customer = queries.customer(db, identity)
        if customer is None or customer.external_billing_account_id != connection_account(db, configuration):
            raise BillingRefused("billing_identity_unproven", 409)
        user = db.get(User, customer.user_id)
        if user is None or (user.tenant_id, user.region) != (
            configuration.instance_tenant_id,
            configuration.instance_region,
        ):
            raise BillingRefused("billing_identity_unproven", 409)
        customers.lock_user(db, customer.user_id)
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
            customers.lock_customer(db, customer.customer_id)
            billing_customers.customer_operation(db, customer.customer_id)
        db.refresh(op)
        queue = billing_customers.recovery_work(db, op.create_operation_id)
        if queue is not None and queue.lease_owner != claim.owner:
            return  # Shared bind already finalized, or a newer owner/hint won.
        row = work.verify_claim(db, claim)
        done = op.operation_state in {State.PENDING, State.PROVEN_NOT_SENT, State.BOUND} or (
            op.operation_kind != Kind.CUSTOMER and op.bound_external_object_id is not None
        )
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


def recovery_paused(factory: SessionFactory, claim: WorkClaim) -> bool:
    """Distinguish an intentional durable pause from a lost/stale acknowledgement."""
    with factory() as db:
        row = work_queries.item(db, claim.id)
        return bool(
            row is not None
            and claim.kind == RECOVERY
            and row.work_kind == RECOVERY
            and row.scope_reference == claim.reference
            and row.work_state == "paused"
        )


def apply_deadline(factory: SessionFactory, claim: WorkClaim) -> RecoveryEscalation | None:
    """No provider I/O, never converts completed no-send evidence into UNKNOWN."""
    with factory() as db:
        found = queries.operation_subject(db, UUID(claim.reference))
        if found is None:
            raise BillingRefused("billing_recovery_unproven", 409)
        op, customer = found
        customers.lock_user(db, customer.user_id)
        if op.operation_kind == Kind.CUSTOMER:
            customers.lock_customer(db, customer.customer_id)
            op = billing_customers.customer_operation(db, customer.customer_id)
            purchase = None
        else:
            purchase = purchases.owned(db, customer.user_id, op.purchase_intent_id, lock=True)
            op = next(
                item
                for item in purchases.operations(db, purchase.purchase_intent_id, lock=True)
                if item.create_operation_id == op.create_operation_id
            )
        # Initial lookup may have cached POSSIBLE_SEND before another writer
        # completed. Row locks serialize decisions but do not refresh that cache.
        db.refresh(op)
        now = as_utc(billing_reconciliation.database_now(db))
        deadline = _recovery_deadline(db, op)
        deadline = as_utc(deadline) if deadline else None
        due = deadline if deadline and deadline > now else None
        unresolved = op.operation_state in {State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW} and (
            op.bound_external_object_id is None
        )
        if due is None and deadline and unresolved:
            reason = "external_create_outcome_unknown:" + op.operation_kind.value
            cases = billing_customers.open_customer_reviews(db, op.create_operation_id)
            if not any(case.reason_code == reason for case in cases):
                if purchase is None:
                    record_customer_review(db, op, reason)
                else:
                    service._locked(db, service._snapshot(db, purchase))
                    financial._review(db, purchase, op, reason)
            from app.domains.billing.paid_access import reduce_paid_access

            reduce_paid_access(db, customer.user_id)
            work.verify_claim(db, claim)  # Queue ownership follows the paid-state locks.
            _pause_recovery(db, op, customer.external_billing_account_id)
            db.flush()
            case = next(
                case
                for case in billing_customers.open_customer_reviews(db, op.create_operation_id)
                if case.reason_code == reason
            )
            notice = RecoveryEscalation(
                op.create_operation_id,
                op.operation_kind.value,
                case.review_case_id,
            )
            # The deadline claim remains durable notification work until the
            # SDK accepts it. No reporting/network occurs under these locks.
            db.commit()
            return notice
        row = work.verify_claim(db, claim)
        work.finish(db, row, claim, due=due)
        db.commit()
        return None


def finish_deadline_notification(factory: SessionFactory, claim: WorkClaim, *, notified: bool) -> None:
    with factory() as db:
        row = work.verify_claim(db, claim)
        work.finish(
            db,
            row,
            claim,
            due=None if notified else as_utc(billing_reconciliation.database_now(db)) + timedelta(minutes=5),
            error=None if notified else "recovery_notification_pending",
        )
        if notified:
            row.payload_document = {**row.payload_document, "notification_sent": True}
        db.commit()
