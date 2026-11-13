"""Read retained point implications without creating another source authority."""

from dataclasses import replace
from datetime import datetime
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
from app.domains.billing.reconciliation_validation import lock_source_claim
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.inventory_facts import implicated_products
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete
from app.domains.purchases.inventory_contracts import InventoryPointHistory, InventoryResult, InventoryStale
from app.infrastructure.queries import billing_reconciliation, purchases
from app.models import (
    BillingStateObservation,
    BillingStateObservationKind,
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


def complete_owned_point(proof: SubscriptionProof | RetainedPointEvidence) -> bool:
    return proof.complete and proof.identity == IdentityProof.MATCH and proof.point_relationship is not None


def retain_candidate_relationship(
    factory: SessionFactory,
    purchase: Purchase,
    history: InventoryPointHistory,
    relationship: SubscriptionRelationship,
    interval: ReadInterval,
) -> InventoryPointHistory:
    """Persist a new restriction and advance only this attempt's known facts."""
    retain_inventory_relationship(
        factory, purchase, history.subscription_id, history.fence, relationship, interval=interval
    )
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
        db.commit()


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
    history = billing_reconciliation.subscription_point_history(
        db,
        sub,
        schemas=RECONCILIATION_READ_SCHEMAS,
        inventory_schema=INVENTORY_RELATIONSHIP_SCHEMA,
        legacy_inventory_schema=LEGACY_INVENTORY_RELATIONSHIP_SCHEMA,
        provider_origin=purchase.accepted.provider_origin,
        accepted_fingerprint=purchase.accepted.offer.fingerprint,
    )
    # Permanent accepted relationships are always implicated, including for
    # legacy observations without the optional point relationship field.
    retained = {SubscriptionRelationship(sub.external_agreement_id, purchase.accepted.selection.tariff_id)}
    cutoff: datetime | None = None
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


def verify_inventory_point_history(db: Session, result: InventoryResult, *, product_id: str | None = None) -> None:
    """Caller holds the user lock through the decision; source writers use it too."""
    # Other products need unchanged relationship implications, not unchanged
    # polling receipts. Strict admission and product apply validate their source
    # receipts separately through reconciliation_validation.source_receipt_current.
    for history in result.point_history:
        purchase = next(item for item in result.purchases if item.id == history.purchase_id)
        sub = purchases.linked_subscription(db, purchase.id)
        if sub is None or sub.subscription_id != history.subscription_id:
            raise InventoryStale()
        current = _retained_relationships(db, sub, purchase)
        expected = history.relationships
        if product_id is not None:

            def affects(relationship: SubscriptionRelationship) -> bool:
                return product_id in implicated_products(
                    result.purchases, sub.external_subscription_id, relationship.agreement_id, relationship.tariff_id
                )

            current = tuple(filter(affects, current))
            expected = tuple(filter(affects, expected))
        if current != expected:
            raise InventoryStale()
