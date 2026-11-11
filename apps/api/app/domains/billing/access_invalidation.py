"""Coalesced delivery lifecycle; User -> outbox -> queue, never HTTP under locks."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import NoResultFound

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import lock_user
from app.domains.billing.work import finish, spread_seconds, verify_claim
from app.domains.billing.work_contracts import (
    WorkClaim,
    InvalidationDelivery,
    InvalidationFailureCode,
    InvalidationInspection,
    InvalidationSchedulingStatus,
)
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.infrastructure.persistence.billing_work import coalesce
from app.infrastructure.queries import billing_reconciliation, billing_work, paid_access
from app.models import BillingWorkKind, BillingWorkScope, BillingWorkState

# Delivery uses canonical symbols through the existing TEXT-backed queue seam.
# Converting legacy ORM fields/producers to PersistedEnumType belongs to ANY-800.
KIND = BillingWorkKind.ACCESS_INVALIDATION


def delivery_key(recipient_id: str, user_id: UUID) -> str:
    # User UUID is globally unique and resolves its canonical tenant/region.
    return f"{recipient_id}:{user_id}"


def schedule_delivery(db: Session, user_id: UUID, now: datetime, *, recipient_id: str, hint: bool = True) -> None:
    coalesce(
        db,
        kind=KIND,
        key=delivery_key(recipient_id, user_id),
        recipient_id=recipient_id,
        scope_kind=BillingWorkScope.USER,
        reference=str(user_id),
        due=now,
        priority=0,
        payload={},
        hint=hint,
    )


def repair_delivery(factory: SessionFactory, configuration: Settings) -> int:
    with factory() as db:
        users = billing_work.missing_invalidations(
            db,
            configuration.instance_tenant_id,
            configuration.instance_region,
            configuration.billing_worker_scan_batch_size,
        )
    repaired = 0
    for recipient_id, identity in users:
        try:
            with factory() as db:
                user = lock_user(db, identity)
                if (user.tenant_id, user.region) != (configuration.instance_tenant_id, configuration.instance_region):
                    continue
                outbox = paid_access.outbox(db, identity, recipient_id)
                row = billing_work.by_key(db, KIND, delivery_key(recipient_id, identity), lock=True)
                if (
                    outbox
                    and outbox.pending_revision > outbox.delivered_revision
                    and (row is None or row.work_state == BillingWorkState.COMPLETED)
                ):
                    schedule_delivery(
                        db,
                        identity,
                        max(as_utc(outbox.next_attempt_at), as_utc(billing_reconciliation.database_now(db))),
                        recipient_id=recipient_id,
                    )
                    db.commit()
                    repaired += 1
        except BillingRefused as error:
            if error.code != "billing_busy":
                raise
    return repaired


def capture_delivery(factory: SessionFactory, configuration: Settings, claim: WorkClaim) -> InvalidationDelivery | None:
    with factory() as db:
        user = lock_user(db, UUID(claim.reference))
        if (
            claim.kind != KIND
            or claim.recipient_id is None
            or (user.tenant_id, user.region)
            != (
                configuration.instance_tenant_id,
                configuration.instance_region,
            )
        ):
            raise BillingRefused("billing_work_stale", 409)
        outbox = paid_access.outbox(db, user.id, claim.recipient_id)
        row = verify_claim(db, claim)
        if row.coalescing_key != delivery_key(claim.recipient_id, user.id):
            raise BillingRefused("billing_work_stale", 409)
        if outbox is None or outbox.pending_revision <= outbox.delivered_revision:
            finish(db, row, claim, due=None)
            db.commit()
            return None
        delivery = InvalidationDelivery(
            claim.recipient_id, user.tenant_id, user.region, user.id, outbox.pending_revision
        )
        outbox.attempt_count += 1
        db.commit()
        return delivery


def apply_delivery(
    factory: SessionFactory,
    claim: WorkClaim,
    sent: InvalidationDelivery,
    *,
    error: InvalidationFailureCode | None = None,
    permanent: bool = False,
) -> None:
    with factory() as db:
        user = lock_user(db, sent.user_id)
        outbox = paid_access.outbox(db, user.id, claim.recipient_id)
        row = verify_claim(db, claim)
        if row.coalescing_key != delivery_key(claim.recipient_id, user.id):
            raise BillingRefused("billing_work_stale", 409)
        if (
            claim.kind != KIND
            or claim.reference != str(sent.user_id)
            or claim.recipient_id != sent.recipient_id
            or outbox is None
            or (user.tenant_id, user.region) != (sent.tenant_id, sent.region)
        ):
            raise BillingRefused("billing_work_stale", 409)
        now = as_utc(billing_reconciliation.database_now(db))
        if error is None:
            # Never substitute the now-current pending revision for the sent N.
            outbox.delivered_revision = max(outbox.delivered_revision, sent.revision)
            due = now if outbox.pending_revision > outbox.delivered_revision else None
        else:
            interval = min(900, 5 * 2 ** min(row.attempt_count - 1, 8))
            due = now + timedelta(seconds=spread_seconds(claim.id, interval))
        outbox.last_error_classification = error
        outbox.next_attempt_at = due or now
        finish(db, row, claim, due=due, error=error)
        if permanent:
            row.work_state = BillingWorkState.INVALID
        db.commit()


def inspect_delivery(
    factory: SessionFactory, configuration: Settings, user_id: UUID, *, recipient_id: str, retry: bool = False
) -> InvalidationInspection:
    with factory() as db:
        try:
            user = lock_user(db, user_id)
        except NoResultFound:
            raise BillingRefused("invalidation_not_found", 404) from None
        if (user.tenant_id, user.region) != (
            configuration.instance_tenant_id,
            configuration.instance_region,
        ):
            raise BillingRefused("invalidation_not_found", 404)
        outbox = paid_access.outbox(db, user_id, recipient_id)
        row = billing_work.by_key(db, KIND, delivery_key(recipient_id, user_id), lock=True)
        if outbox is None:
            raise BillingRefused("invalidation_not_found", 404)
        if retry:
            if row is None or row.work_state != BillingWorkState.INVALID:
                raise BillingRefused("invalidation_not_parked", 409)
            now = as_utc(billing_reconciliation.database_now(db))
            row.work_state = BillingWorkState.PENDING
            row.enqueue_generation += 1
            row.next_attempt_at = outbox.next_attempt_at = now
            row.last_error_classification = outbox.last_error_classification = None
        result: InvalidationInspection = {
            "recipient_id": recipient_id,
            "user_id": str(user_id),
            "pending_revision": outbox.pending_revision,
            "delivered_revision": outbox.delivered_revision,
            "attempt_count": outbox.attempt_count,
            "last_error_classification": outbox.last_error_classification,
            "work_state": row.work_state if row else InvalidationSchedulingStatus.UNSCHEDULED,
            "next_attempt_at": row.next_attempt_at.isoformat() if row else outbox.next_attempt_at.isoformat(),
        }
        if retry:
            db.commit()
        return result
