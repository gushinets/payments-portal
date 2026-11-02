"""Billing queue Application transitions. All units own short local transactions."""

from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.settings import AppEnv, Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import lock_user
from app.domains.billing.customer_scope import connection_account
from app.domains.billing.work_contracts import WorkClaim, WorkLane
from app.domains.billing.paid_deadlines import effective_deadline, schedule_deadline
from app.domains.billing.paid_access import commit_paid_state
from app.infrastructure.queries import paid_access
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.infrastructure.persistence.billing_work import coalesce
from app.infrastructure.queries import billing_reconciliation, billing_work as queries, purchases
from app.models import (
    BillingStateObservation,
    BillingStateObservationKind,
    BillingWorkItem,
    ExternalSubscription,
    ExternalSubscriptionFinancialAccessStatus as Financial,
)

RECONCILIATION = "subscription_reconciliation"
EXPIRY = "subscription_trust_expiry"
SWEEP = "billing_enrollment_sweep"
SWEEP_SECONDS = 60
URGENT_SECONDS = 300
NORMAL_SECONDS = 900
URGENT_TRUST_WINDOW = timedelta(minutes=30)


def reconciliation_outcome(factory: SessionFactory, observation_id: UUID) -> tuple[str, datetime]:
    """Telemetry reads committed evidence; queue progress is not proof success."""
    with factory() as db:
        observation = queries.observation(db, observation_id)
        outcome = (
            "verified"
            if observation.completeness_classification == "complete"
            and observation.result_classification == "COMPLETE_MATCH"
            else "incomplete"
            if observation.completeness_classification == "incomplete"
            else "conflict"
        )
        return outcome, as_utc(observation.observed_at)


def key(subscription: ExternalSubscription) -> str:
    return f"{subscription.external_billing_account_id}:{subscription.subscription_id}"


def enroll_subscription(db: Session, subscription: ExternalSubscription, *, hint: bool = False) -> None:
    coalesce(
        db,
        kind=RECONCILIATION,
        key=key(subscription),
        scope_kind="subscription",
        reference=str(subscription.subscription_id),
        due=as_utc(billing_reconciliation.database_now(db)),
        priority=1,
        payload={},
        hint=hint,
    )


def enroll_batch(factory: SessionFactory, configuration: Settings) -> int:
    """Committed missing set is the progress marker; no offset/cursor or HTTP."""
    if configuration.lbx_configuration_error is not None:
        return 0
    with factory() as db:
        account = connection_account(db, configuration)
        subscriptions = queries.missing_subscriptions(
            db,
            account,
            configuration.instance_tenant_id,
            configuration.instance_region,
            configuration.billing_worker_scan_batch_size,
        )
        for sub in subscriptions:
            enroll_subscription(db, sub)
        db.commit()
        return len(subscriptions)


def repair_paid_deadlines(factory: SessionFactory, configuration: Settings) -> int:
    """Bounded missing set is its own progress marker; no source config or HTTP."""
    with factory() as db:
        users = paid_access.missing_deadline_users(
            db,
            configuration.instance_tenant_id,
            configuration.instance_region,
            configuration.billing_worker_scan_batch_size,
            allow_simulated_metering=configuration.app_env != AppEnv.PRODUCTION,
        )
    repaired = 0
    for identity in users:
        try:
            with factory() as db:
                user = lock_user(db, identity)
                commit_paid_state(
                    db,
                    user,
                    None,
                    as_utc(billing_reconciliation.database_now(db)),
                    allow_simulated_metering=configuration.app_env != AppEnv.PRODUCTION,
                )
                db.commit()
                repaired += 1
        except BillingRefused as error:
            if error.code != "billing_busy":
                raise
    # Retain Step 8 source-trust evidence repair even for non-paid projections.
    with factory() as db:
        deadlines = queries.missing_deadlines(
            db,
            configuration.instance_tenant_id,
            configuration.instance_region,
            configuration.billing_worker_scan_batch_size,
        )
        for sub in deadlines:
            schedule_deadline(db, sub)
        db.commit()
    return max(repaired, len(deadlines))


def ensure_sweep(factory: SessionFactory, configuration: Settings) -> None:
    with factory() as db:
        # Stable deployment/origin key: the first proven storage scope can
        # appear after startup. Sweeps resolve that scope anew on each batch.
        coalesce(
            db,
            kind=SWEEP,
            key=configuration.lbx_external_billing_account_id,
            scope_kind="billing_account",
            reference=configuration.lbx_external_billing_account_id,
            due=as_utc(billing_reconciliation.database_now(db)),
            priority=1,
            payload={},
            hint=True,
        )
        db.commit()


def claim_work(factory: SessionFactory, configuration: Settings, lane: WorkLane) -> WorkClaim | None:
    with factory() as db:
        now = as_utc(billing_reconciliation.database_now(db))
        row = queries.claimable(
            db,
            (SWEEP, EXPIRY, "external_create_deadline")
            if lane == WorkLane.LOCAL
            else (RECONCILIATION, "external_create_recovery", "customer_inventory"),
            now,
            urgent=None if lane == WorkLane.LOCAL else lane == WorkLane.URGENT,
            account=configuration.lbx_external_billing_account_id
            if lane == WorkLane.LOCAL
            else connection_account(db, configuration),
            sweep_key=configuration.lbx_external_billing_account_id,
            local_scope=(configuration.instance_tenant_id, configuration.instance_region)
            if lane == WorkLane.LOCAL
            else None,
            trust_urgent_before=now + URGENT_TRUST_WINDOW,
        )
        if row is None:
            return None
        row.lease_owner = str(uuid4())
        row.lease_expires_at = now + timedelta(seconds=configuration.billing_worker_io_timeout_seconds + 30)
        row.last_attempt_started_at = now
        row.attempt_count += 1
        row.work_state = "running"
        claim = WorkClaim(
            row.work_item_id,
            row.work_kind,
            row.scope_reference,
            row.lease_owner,
            row.enqueue_generation,
            now,
            row.lease_expires_at,
        )
        db.commit()
        # A failed/uncertain commit cannot return ownership or start HTTP.
        return claim


def verify_claim(db: Session, claim: WorkClaim) -> BillingWorkItem:
    row = queries.item(db, claim.id)
    now = as_utc(billing_reconciliation.database_now(db))
    if (
        row is None
        or row.work_state != "running"
        or row.work_kind != claim.kind
        or row.scope_reference != claim.reference
        or row.lease_owner != claim.owner
        or row.lease_expires_at is None
        or as_utc(row.lease_expires_at) <= now
    ):
        raise BillingRefused("billing_work_stale", 409)
    return row


def verify_operation_claim(db: Session, claim: WorkClaim, operation_id: UUID) -> BillingWorkItem:
    if claim.kind != "external_create_recovery" or claim.reference != str(operation_id):
        raise BillingRefused("billing_work_stale", 409)
    return verify_claim(db, claim)


def finish(
    db: Session, row: BillingWorkItem, claim: WorkClaim, *, due: datetime | None, error: str | None = None
) -> None:
    if row.enqueue_generation != claim.generation:
        # A hint committed after claim survives even a successful result.
        row.work_state = "pending"
    else:
        row.work_state = "completed" if due is None else "pending"
        if due is not None:
            row.next_attempt_at = due
    row.last_error_classification = error
    row.lease_owner = None
    row.lease_expires_at = None


def spread_seconds(identity: UUID, interval: int) -> float:
    # Deterministic earlier-only 0..20% jitter; never exceeds max cadence.
    fraction = int.from_bytes(sha256(identity.bytes).digest()[:2], "big") / 65535
    return interval * (0.8 + 0.2 * fraction)


def schedule_reconciliation(
    db: Session,
    sub: ExternalSubscription,
    claim: WorkClaim | None,
    *,
    complete: bool,
    attempt_started_at: datetime | None = None,
) -> None:
    now = as_utc(billing_reconciliation.database_now(db))
    scope = billing_reconciliation.scope(db, sub.user_id, sub.product_id)
    urgent = (
        not complete
        or sub.financial_access_status != Financial.ALLOWED
        or as_utc(sub.projection_valid_until) <= now + URGENT_TRUST_WINDOW
    )
    if claim is not None:
        row = verify_claim(db, claim)
        interval = URGENT_SECONDS if urgent else NORMAL_SECONDS
        if not complete:
            interval = min(URGENT_SECONDS, 30 * 2 ** min(row.attempt_count - 1, 4))
        due = max(now + timedelta(seconds=1), claim.started_at + timedelta(seconds=spread_seconds(claim.id, interval)))
        finish(db, row, claim, due=due, error=None if complete else "source_incomplete")
        row.priority = int(urgent or row.enqueue_generation != claim.generation)
    else:
        # CLI/source applies have no queue claim. Coalesce urgent follow-up
        # without clearing a running owner's lease or its newer generation.
        # A complete normal read must not downgrade an unconsumed urgent hint.
        coalesce(
            db,
            kind=RECONCILIATION,
            key=key(sub),
            scope_kind="subscription",
            reference=str(sub.subscription_id),
            due=max(
                now + timedelta(seconds=1),
                (attempt_started_at or now)
                + timedelta(seconds=spread_seconds(sub.subscription_id, URGENT_SECONDS if urgent else NORMAL_SECONDS)),
            ),
            priority=int(urgent),
            payload={},
            hint=urgent,
        )
    # Source trust and the earliest conservative paid boundary share one row.
    schedule_deadline(db, sub, scope)


def retry_work(
    factory: SessionFactory, claim: WorkClaim, *, invalid: bool = False, error: str = "worker_attempt_failed"
) -> bool:
    """Acknowledge only a committed owned retry/quarantine; DB errors propagate."""
    with factory() as db:
        try:
            row = verify_claim(db, claim)
        except BillingRefused:
            return False
        now = as_utc(billing_reconciliation.database_now(db))
        # Source lease may still be occupied after cancellation: wait until its
        # finite expiry; never promote an old result or extend source trust.
        due = max(now + timedelta(seconds=30), claim.expires_at + timedelta(seconds=1))
        finish(db, row, claim, due=due, error=error)
        if invalid:
            row.work_state = "invalid"
            row.last_error_classification = "subscription_provenance_unproven"
        db.commit()
        return True


def finish_sweep(factory: SessionFactory, claim: WorkClaim, *, more: bool = False) -> None:
    with factory() as db:
        row = verify_claim(db, claim)
        finish(
            db,
            row,
            claim,
            due=as_utc(billing_reconciliation.database_now(db)) + timedelta(seconds=0 if more else SWEEP_SECONDS),
        )
        db.commit()


def expire_trust(factory: SessionFactory, claim: WorkClaim) -> None:
    with factory() as db:
        initial = billing_reconciliation.subscription(db, UUID(claim.reference))
        if initial is None:
            raise BillingRefused("subscription_not_found", 404)
        user = lock_user(db, initial.user_id)
        # Follow the same business lock order as authoritative apply.
        purchase = purchases.owned(db, initial.user_id, initial.purchase_intent_id, lock=True)
        if purchase is None:
            raise BillingRefused("subscription_provenance_unproven", 409)
        purchases.operations(db, purchase.purchase_intent_id, lock=True)
        scope = billing_reconciliation.scope(db, initial.user_id, initial.product_id)
        sub = billing_reconciliation.subscription(db, initial.subscription_id, lock=True)
        now = as_utc(billing_reconciliation.database_now(db))
        cause = None
        if scope is not None and sub.latest_observation_id is not None:
            due = effective_deadline(scope) if scope.primary_subscription_id == sub.subscription_id else None
            deadline = min(as_utc(sub.projection_valid_until), due) if due else as_utc(sub.projection_valid_until)
            if deadline <= now:
                cause = BillingStateObservation(
                    observation_kind=BillingStateObservationKind.DETERMINISTIC_ACCESS_BOUNDARY,
                    external_billing_account_id=sub.external_billing_account_id,
                    user_id=sub.user_id,
                    product_id=sub.product_id,
                    access_scope_id=scope.access_scope_id,
                    subscription_id=sub.subscription_id,
                    basis_observation_id=sub.latest_observation_id,
                    observed_at=now,
                    effective_at=deadline,
                    evidence_schema_version="subscription-trust-expiry:v1",
                    evidence_document={
                        "supporting_observation_id": str(sub.latest_observation_id),
                        "deadline": deadline.isoformat(),
                    },
                    completeness_classification="local_deadline",
                    result_classification="source_trust_expired"
                    if as_utc(sub.projection_valid_until) <= now
                    else "effective_access_deadline",
                )
                db.add(cause)
        # Reduction only: this path never applies source proof or issues allowances.
        commit_paid_state(db, user, cause, now)
        row = verify_claim(db, claim)  # Queue ownership last; stale owner rolls back all writes.
        due = effective_deadline(scope) if scope and scope.primary_subscription_id == sub.subscription_id else None
        future = [value for value in (due, as_utc(sub.projection_valid_until)) if value and value > now]
        finish(db, row, claim, due=min(future) if future else None)

        db.commit()


def inspect_backlog(factory: SessionFactory, configuration: Settings) -> tuple[int, datetime | None, int]:
    with factory() as db:
        try:
            account = connection_account(db, configuration)
        except BillingRefused as error:
            if error.code != "billing_connection_conflict":
                raise
            account = None  # Local queue visibility does not require source admission.
        return queries.backlog(
            db,
            account,
            configuration.instance_tenant_id,
            configuration.instance_region,
            sweep_key=configuration.lbx_external_billing_account_id,
        )
