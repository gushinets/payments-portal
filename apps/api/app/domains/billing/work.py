"""Billing queue Application transitions. All units own short local transactions."""

from datetime import datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import lock_user
from app.domains.billing.work_contracts import WorkClaim, WorkLane
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import service
from app.infrastructure.persistence.billing_work import coalesce
from app.infrastructure.queries import billing_reconciliation, billing_work as queries, purchases
from app.models import (
    BillingStateObservation,
    BillingStateObservationKind,
    BillingWorkItem,
    ExternalSubscription,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalCreateOperationKind as OperationKind,
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
    with factory() as db:
        ids = queries.missing_subscriptions(
            db,
            configuration.lbx_external_billing_account_id,
            configuration.instance_tenant_id,
            configuration.instance_region,
            configuration.billing_worker_scan_batch_size,
        )
        for identity in ids:
            subject = queries.enrollment_subject(db, identity)
            if subject is None:
                continue
            sub, purchase, customer, customer_op = subject
            operations = purchases.operations(db, purchase.purchase_intent_id)
            held = purchases.hold(db, sub.user_id, sub.product_id)
            try:
                evidence = service.accepted(purchase)
                service._verify_original_consent(db, purchase, evidence)
                valid = (
                    (
                        purchase.user_id,
                        purchase.product_id,
                        purchase.customer_id,
                        purchase.mapping_revision_id,
                        purchase.external_billing_account_id,
                    )
                    == (
                        sub.user_id,
                        sub.product_id,
                        sub.customer_id,
                        sub.mapping_revision_id,
                        sub.external_billing_account_id,
                    )
                    and customer.user_id == sub.user_id
                    and customer.external_billing_account_id == sub.external_billing_account_id
                    and customer.provider_customer_id is not None
                    and customer_op is not None
                    and customer_op.bound_external_object_id == customer.provider_customer_id
                    and customer_op.request_correlation_key == customer.billing_customer_key
                    and customer.provider_origin == evidence.provider_origin == configuration.lbx_provider_origin
                    and held is not None
                    and held.purchase_intent_id == purchase.purchase_intent_id
                    and all(
                        any(op.operation_kind == kind and op.bound_external_object_id == binding for op in operations)
                        for kind, binding in (
                            (OperationKind.AGREEMENT, sub.external_agreement_id),
                            (OperationKind.SUBSCRIPTION, sub.external_subscription_id),
                        )
                    )
                )
            except (ValueError, service.PurchaseRefused):
                valid = False
            enroll_subscription(db, sub)
            if not valid:
                # Quarantine one malformed historical subject; it leaves the missing
                # set and cannot turn a bad first batch into a hot loop.
                row = queries.by_key(db, RECONCILIATION, key(sub))
                row.work_state = "invalid"
                row.last_error_classification = "subscription_provenance_unproven"
        deadlines = queries.missing_deadlines(
            db, configuration.lbx_external_billing_account_id, configuration.billing_worker_scan_batch_size
        )
        for sub in deadlines:
            schedule_reconciliation(db, sub, None, complete=False)
        db.commit()
        return max(len(ids), len(deadlines))


def ensure_sweep(factory: SessionFactory, configuration: Settings) -> None:
    with factory() as db:
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
            account=configuration.lbx_external_billing_account_id,
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
    # Renewed trust and its deterministic deadline are committed together.
    if (
        sub.latest_observation_id is not None
        and sub.reconciliation_fencing_token
        and as_utc(sub.projection_valid_until) > as_utc(sub.last_authoritative_read_at)
    ):
        # Preparation has a zero-length trust window and an unscoped observation.
        # An incomplete first attempt cannot turn that into expiry provenance.
        coalesce(
            db,
            kind=EXPIRY,
            key=key(sub),
            scope_kind="subscription",
            reference=str(sub.subscription_id),
            due=as_utc(sub.projection_valid_until),
            priority=1,
            payload={
                "supporting_observation_id": str(sub.latest_observation_id),
                "deadline": as_utc(sub.projection_valid_until).isoformat(),
            },
            replace_deadline=True,
        )


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
        lock_user(db, initial.user_id)
        # Follow the same business lock order as authoritative apply.
        purchase = purchases.owned(db, initial.user_id, initial.purchase_intent_id, lock=True)
        if purchase is None:
            raise BillingRefused("subscription_provenance_unproven", 409)
        purchases.operations(db, purchase.purchase_intent_id, lock=True)
        scope = billing_reconciliation.scope(db, initial.user_id, initial.product_id)
        sub = billing_reconciliation.subscription(db, initial.subscription_id, lock=True)
        row = verify_claim(db, claim)  # Queue lock last, never while acquiring business locks.
        now = as_utc(billing_reconciliation.database_now(db))
        if row.enqueue_generation != claim.generation or as_utc(sub.projection_valid_until) > now:
            finish(db, row, claim, due=as_utc(sub.projection_valid_until))
        else:
            if scope is not None and sub.latest_observation_id is not None:
                db.add(
                    BillingStateObservation(
                        observation_kind=BillingStateObservationKind.DETERMINISTIC_ACCESS_BOUNDARY,
                        external_billing_account_id=sub.external_billing_account_id,
                        user_id=sub.user_id,
                        product_id=sub.product_id,
                        access_scope_id=scope.access_scope_id,
                        subscription_id=sub.subscription_id,
                        basis_observation_id=sub.latest_observation_id,
                        observed_at=now,
                        effective_at=sub.projection_valid_until,
                        evidence_schema_version="subscription-trust-expiry:v1",
                        evidence_document={
                            "supporting_observation_id": str(sub.latest_observation_id),
                            "deadline": as_utc(sub.projection_valid_until).isoformat(),
                        },
                        completeness_classification="local_deadline",
                        result_classification="source_trust_expired",
                        resulting_access_revision=None,
                    )
                )
            # Source timestamps/lifecycle/support stay intact: expiry is not a
            # new provider block. Step 9 consumes this local deadline evidence.
            finish(db, row, claim, due=None)
        db.commit()


def inspect_backlog(factory: SessionFactory, configuration: Settings) -> tuple[int, datetime | None, int]:
    with factory() as db:
        return queries.backlog(db, configuration.lbx_external_billing_account_id)
