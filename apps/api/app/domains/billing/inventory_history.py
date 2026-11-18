"""Read retained point implications without creating another source authority."""

from dataclasses import replace
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictBool, ValidationError, model_validator
from sqlalchemy.orm import Session

from app.domains.billing.reconciliation_contracts import (
    RECONCILIATION_READ_SCHEMAS,
    IdentityProof,
    ReadInterval,
    ReconciliationSubject,
    SubscriptionProof,
    SubscriptionRelationship,
)
from app.domains.catalog.publication import SessionFactory
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.reconciliation_validation import lock_source_claim
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.inventory_facts import implicated_products
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete
from app.domains.purchases.inventory_contracts import InventoryPointHistory, InventoryResult, InventoryStale
from app.infrastructure.queries import billing_reconciliation, billing_work, purchases
from app.models import (
    BillingStateObservation,
    BillingStateObservationKind,
    BillingWorkItem,
    ExternalCreateOperationKind as Kind,
    ExternalSubscription,
)

LEGACY_INVENTORY_RELATIONSHIP_SCHEMA = "inventory-subscription-relationship:v1"
INVENTORY_RELATIONSHIP_SCHEMA = "inventory-subscription-relationship:v2"


class RetainedPointEvidence(BaseModel):
    """Consumed subset of canonical and supplemental relationship evidence."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    identity: IdentityProof
    complete: StrictBool
    point_relationship: SubscriptionRelationship | None = None
    read_started_at: AwareDatetime | None = None
    read_finished_at: AwareDatetime | None = None

    @model_validator(mode="after")
    def validate_interval(self) -> "RetainedPointEvidence":
        if (self.read_started_at is None) != (self.read_finished_at is None):
            raise ValueError("partial source interval")
        if self.read_started_at is not None and self.read_finished_at < self.read_started_at:
            raise ValueError("reversed source interval")
        return self


class RelationshipProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    purchase_intent_id: UUID
    mapping_revision_id: UUID
    accepted_fingerprint: str
    provider_origin: str
    provider_subscription_id: str
    agreement_id: str
    fence: int


class InventoryRelationshipEvidence(RetainedPointEvidence):
    point_relationship: SubscriptionRelationship
    provenance: RelationshipProvenance
    read_started_at: AwareDatetime
    read_finished_at: AwareDatetime


class DeferredRelationship(BaseModel):
    """A restrictive point waiting for the existing user-serialized writer."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    purchase_id: UUID
    subscription_id: UUID
    fence: int
    point_relationship: SubscriptionRelationship
    read_started_at: AwareDatetime
    read_finished_at: AwareDatetime


class InventoryWorkPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    deferred_relationships: tuple[DeferredRelationship, ...] = ()


def _inventory_job(db: Session, account_id: str, customer_id: UUID) -> BillingWorkItem | None:
    from app.domains.billing.background_recovery import INVENTORY

    return billing_work.by_key(db, INVENTORY, f"{account_id}:{customer_id}", lock=True)


def _inventory_payload(job: BillingWorkItem) -> InventoryWorkPayload:
    try:
        return InventoryWorkPayload.model_validate(job.payload_document)
    except ValidationError:
        raise PurchaseInventoryIncomplete() from None


def defer_inventory_relationship(
    factory: SessionFactory,
    purchase: Purchase,
    subscription_id: UUID,
    fence: int,
    relationship: SubscriptionRelationship,
    interval: ReadInterval,
    claim: WorkClaim | None,
) -> None:
    """Keep the original negative fact when the user lock is unavailable."""
    permanent = SubscriptionRelationship(
        next(op.bound_id for op in purchase.operations if op.kind == Kind.AGREEMENT),
        purchase.accepted.selection.tariff_id,
    )
    if relationship == permanent:
        return
    with factory() as db:
        job = _inventory_job(db, purchase.account_id, purchase.customer_id)
        if job is None:
            from app.domains.billing.background_recovery import INVENTORY
            from app.infrastructure.persistence.billing_work import coalesce

            coalesce(
                db,
                kind=INVENTORY,
                key=f"{purchase.account_id}:{purchase.customer_id}",
                scope_kind="customer",
                reference=str(purchase.customer_id),
                due=as_utc(billing_reconciliation.database_now(db)),
                priority=1,
                payload=None,
            )
            job = _inventory_job(db, purchase.account_id, purchase.customer_id)
            if job is None:
                raise InventoryStale()
        pending = _inventory_payload(job).deferred_relationships
        evidence = DeferredRelationship(
            purchase_id=purchase.id,
            subscription_id=subscription_id,
            fence=fence,
            point_relationship=relationship,
            read_started_at=interval.started_at,
            read_finished_at=interval.finished_at,
        )
        # Only the latest finish of the same permanent-source pair is needed
        # for restrictive evidence. The original read interval stays intact.
        repeats = tuple(
            item
            for item in pending
            if item.subscription_id == subscription_id and item.point_relationship == relationship
        )
        if repeats and max(item.read_finished_at for item in repeats) >= evidence.read_finished_at:
            return
        job.payload_document = InventoryWorkPayload(
            deferred_relationships=(*[item for item in pending if item not in repeats], evidence),
        ).model_dump(mode="json")
        if claim is None or job.work_item_id != claim.id or job.lease_owner != claim.owner:
            # Wake the recurring job without changing a current owner's lease.
            job.enqueue_generation += 1
            job.priority = 1
            job.next_attempt_at = min(as_utc(job.next_attempt_at), as_utc(billing_reconciliation.database_now(db)))
            if job.work_state == "completed":
                job.work_state = "pending"
        db.commit()


def replay_deferred_relationships(
    db: Session, account_id: str, customer_id: UUID, purchases_in_scope: tuple[Purchase, ...]
) -> bool:
    """Caller holds the user lock. Publish the facts and clear the queue atomically."""
    job = _inventory_job(db, account_id, customer_id)
    if job is None or not (pending := _inventory_payload(job).deferred_relationships):
        return False
    by_purchase = {purchase.id: purchase for purchase in purchases_in_scope}
    for evidence in pending:
        purchase = by_purchase.get(evidence.purchase_id)
        if purchase is None:
            continue  # A released hold is no longer eligible for this customer's inventory.
        sub = _bound_subscription(db, purchase)
        _append_inventory_relationship(
            db,
            purchase,
            sub,
            evidence.subscription_id,
            evidence.fence,
            evidence.point_relationship,
            ReadInterval(evidence.read_started_at, evidence.read_finished_at),
            None,
        )
    job.payload_document = {}
    return True


def complete_owned_point(proof: SubscriptionProof | RetainedPointEvidence) -> bool:
    return proof.complete and proof.identity == IdentityProof.MATCH and proof.point_relationship is not None


def retain_candidate_relationship(
    factory: SessionFactory,
    purchase: Purchase,
    history: InventoryPointHistory,
    relationship: SubscriptionRelationship,
    interval: ReadInterval,
    *,
    work_claim: WorkClaim | None = None,
) -> InventoryPointHistory:
    """Persist a new restriction and advance only this attempt's known facts."""
    try:
        retain_inventory_relationship(
            factory, purchase, history.subscription_id, history.fence, relationship, interval=interval
        )
    except BillingRefused as error:
        if error.code == "billing_busy":
            defer_inventory_relationship(
                factory, purchase, history.subscription_id, history.fence, relationship, interval, work_claim
            )
        raise
    return replace(
        history,
        relationships=tuple(
            sorted({*history.relationships, relationship}, key=lambda item: (item.agreement_id, item.tariff_id))
        ),
    )


def retain_inventory_relationship(
    factory: SessionFactory,
    purchase: Purchase,
    subscription_id: UUID,
    fence: int,
    relationship: SubscriptionRelationship,
    *,
    interval: ReadInterval,
    proof: SubscriptionProof | None = None,
    subject: ReconciliationSubject | None = None,
) -> None:
    """Keep timely restrictions even if later inventory/operator work aborts.

    This is inventory evidence, never a source receipt, rebind or paid-access
    write. The actual read interval orders delayed writes independently of
    claim generation or arrival time.
    """
    expected_agreement = next(op.bound_id for op in purchase.operations if op.kind == Kind.AGREEMENT)
    if subject is None and relationship == SubscriptionRelationship(
        expected_agreement, purchase.accepted.selection.tariff_id
    ):
        return  # Already permanently implicated; no new restriction or resolving claim.
    with factory() as db:
        sub = _bound_subscription(db, purchase)
        _append_inventory_relationship(
            db, purchase, sub, subscription_id, fence, relationship, interval, proof, subject
        )
        db.commit()


def _append_inventory_relationship(
    db: Session,
    purchase: Purchase,
    sub: ExternalSubscription,
    subscription_id: UUID,
    fence: int,
    relationship: SubscriptionRelationship,
    interval: ReadInterval,
    proof: SubscriptionProof | None,
    subject: ReconciliationSubject | None = None,
) -> None:
    if sub.subscription_id != subscription_id or sub.reconciliation_fencing_token < fence:
        raise InventoryStale()
    scope = billing_reconciliation.scope(db, purchase.user_id, sub.product_id)
    if scope is None:
        raise InventoryStale()
    now = as_utc(billing_reconciliation.database_now(db))
    if not interval.started_at <= interval.finished_at <= now:
        raise InventoryStale()
    # Restrictions can survive a stale attempt. Removing older restrictions
    # requires the same timely claimed ownership as authoritative apply.
    cutoff = False
    if proof is not None and subject is not None and complete_owned_point(proof):
        try:
            lock_source_claim(db, subject, proof)
        except BillingRefused:
            pass  # Stale ownership can retain a restriction, never clear one.
        else:
            cutoff = (
                subject.subscription_id == subscription_id
                and subject.purchase == purchase
                and subject.fence == fence
                and proof.point_relationship == relationship
                and interval == ReadInterval(proof.read_started_at, proof.read_finished_at)
            )
    document = InventoryRelationshipEvidence(
        identity=proof.identity if proof is not None else IdentityProof.INCOMPLETE,
        complete=cutoff,
        point_relationship=relationship,
        read_started_at=interval.started_at,
        read_finished_at=interval.finished_at,
        provenance=RelationshipProvenance(
            purchase_intent_id=purchase.id,
            mapping_revision_id=purchase.accepted.meaning.revision_id,
            accepted_fingerprint=purchase.accepted.offer.fingerprint,
            provider_origin=purchase.accepted.provider_origin,
            provider_subscription_id=sub.external_subscription_id,
            agreement_id=sub.external_agreement_id,
            fence=fence,
        ),
    )
    db.add(
        BillingStateObservation(
            observation_kind=BillingStateObservationKind.TARGET_PRODUCT_DISCOVERY,
            external_billing_account_id=purchase.account_id,
            user_id=purchase.user_id,
            product_id=sub.product_id,
            access_scope_id=scope.access_scope_id,
            subscription_id=sub.subscription_id,
            observed_at=interval.finished_at,
            evidence_schema_version=INVENTORY_RELATIONSHIP_SCHEMA,
            evidence_document=document.model_dump(mode="json"),
            completeness_classification="complete" if document.complete else "incomplete",
            result_classification="candidate_proof",
        )
    )


def _bound_subscription(db: Session, purchase: Purchase) -> ExternalSubscription:
    row = service._locked(db, purchase)  # Serializes relationship and source writers on the user.
    sub = purchases.linked_subscription(db, purchase.id)
    if sub is None or (
        service.accepted(row) != purchase.accepted
        or sub.mapping_revision_id != purchase.accepted.meaning.revision_id
        or sub.external_billing_account_id != purchase.account_id
        or sub.customer_id != purchase.customer_id
        or sub.user_id != purchase.user_id
        or sub.product_id != purchase.accepted.selection.product_id
        or sub.external_agreement_id != next(op.bound_id for op in purchase.operations if op.kind == Kind.AGREEMENT)
        or sub.external_subscription_id
        != next(op.bound_id for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    ):
        raise InventoryStale()
    return sub


def _retained_relationships(
    db: Session, sub: ExternalSubscription, purchase: Purchase
) -> tuple[SubscriptionRelationship, ...]:
    lookup: billing_reconciliation.PointHistoryLookup = {
        "schemas": RECONCILIATION_READ_SCHEMAS,
        "inventory_schema": INVENTORY_RELATIONSHIP_SCHEMA,
        "legacy_inventory_schema": LEGACY_INVENTORY_RELATIONSHIP_SCHEMA,
        "provider_origin": purchase.accepted.provider_origin,
        "accepted_fingerprint": purchase.accepted.offer.fingerprint,
    }
    # The authoritative pointer supplies a cheap lower bound before PostgreSQL
    # sorts or deduplicates the interval. A later overlapping read can move it.
    latest = billing_reconciliation.latest_subscription_point(db, sub, **lookup)
    cutoff = None
    if latest is not None:
        try:
            proof = RetainedPointEvidence.model_validate(latest.evidence_document)
        except ValidationError:
            pass  # The ordered scan validates it if it still affects the result.
        else:
            if complete_owned_point(proof) and proof.read_finished_at == as_utc(latest.observed_at):
                cutoff = proof.read_started_at
    history = billing_reconciliation.subscription_point_history(db, sub, **lookup, since=cutoff)
    # Permanent accepted relationships are always implicated, including for
    # legacy observations without the optional point relationship field.
    retained = {SubscriptionRelationship(sub.external_agreement_id, purchase.accepted.selection.tariff_id)}
    try:
        for observation in history:
            if cutoff is not None and as_utc(observation.observed_at) < cutoff:
                break  # Every remaining read finished before an owned full read began.
            evidence_type = (
                InventoryRelationshipEvidence
                if observation.evidence_schema_version == INVENTORY_RELATIONSHIP_SCHEMA
                else RetainedPointEvidence
            )
            proof = evidence_type.model_validate(observation.evidence_document)
            if proof.point_relationship is None:
                continue  # Legacy/absent point evidence cannot erase an earlier relationship.
            retained.add(proof.point_relationship)
            if complete_owned_point(proof) and proof.read_started_at is not None:
                cutoff = max(cutoff, proof.read_started_at) if cutoff else proof.read_started_at
    except ValidationError:
        raise PurchaseInventoryIncomplete() from None
    finally:
        history.close()
    return tuple(sorted(retained, key=lambda item: (item.agreement_id, item.tariff_id)))


def retained_subscription_relationships(factory: SessionFactory, purchase: Purchase) -> InventoryPointHistory:
    with factory() as db:
        sub = _bound_subscription(db, purchase)
        return InventoryPointHistory(
            purchase.id,
            sub.subscription_id,
            sub.reconciliation_fencing_token,
            _retained_relationships(db, sub, purchase),
        )


def inventory_point_changes(db: Session, result: InventoryResult) -> frozenset[str]:
    """Collect affected products once while the caller holds the user lock."""
    by_purchase = {purchase.id: purchase for purchase in result.purchases}
    affected: set[str] = set()
    for history in result.point_history:
        purchase = by_purchase[history.purchase_id]
        sub = purchases.linked_subscription(db, purchase.id)
        if sub is None or sub.subscription_id != history.subscription_id:
            raise InventoryStale()
        current = _retained_relationships(db, sub, purchase)
        for relationship in set(current).symmetric_difference(history.relationships):
            affected.update(
                implicated_products(
                    result.purchases, sub.external_subscription_id, relationship.agreement_id, relationship.tariff_id
                )
            )
    if result.purchases:
        # A queue-only writer may have recorded a restriction since collection.
        # Keep the queue locked through the caller's decision.
        job = _inventory_job(db, result.purchases[0].account_id, result.customer.customer_id)
        if job is not None:
            for evidence in _inventory_payload(job).deferred_relationships:
                if (purchase := by_purchase.get(evidence.purchase_id)) is not None:
                    relationship = evidence.point_relationship
                    provider_id = next(op.bound_id for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
                    affected.update(
                        implicated_products(
                            result.purchases, provider_id, relationship.agreement_id, relationship.tariff_id
                        )
                    )
    return frozenset(affected)
