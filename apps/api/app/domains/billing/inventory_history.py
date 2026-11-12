"""Read retained point implications without creating another source authority."""

from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError
from sqlalchemy.orm import Session

from app.domains.billing.reconciliation_contracts import (
    RECONCILIATION_SCHEMA,
    IdentityProof,
    SubscriptionProof,
    SubscriptionRelationship,
)
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase, PurchaseInventoryIncomplete
from app.domains.purchases.inventory_contracts import InventoryPointHistory, InventoryResult, InventoryStale
from app.infrastructure.queries import billing_reconciliation, purchases


class RetainedPointEvidence(BaseModel):
    """Only the consumed subset of the existing reconciliation document."""

    model_config = ConfigDict(extra="ignore", frozen=True)
    identity: IdentityProof
    complete: StrictBool
    point_relationship: SubscriptionRelationship | None = None


def complete_owned_point(proof: SubscriptionProof | RetainedPointEvidence) -> bool:
    return proof.complete and proof.identity == IdentityProof.MATCH and proof.point_relationship is not None


def retained_subscription_relationships(factory: SessionFactory, purchase: Purchase) -> InventoryPointHistory:
    with factory() as db:
        row = service._locked(db, purchase)
        if service.accepted(row) != purchase.accepted:
            raise InventoryStale()
        sub = purchases.linked_subscription(db, purchase.id)
        if sub is None:
            raise InventoryStale()
        history = billing_reconciliation.subscription_point_history(
            db,
            sub,
            schema=RECONCILIATION_SCHEMA,
            provider_origin=purchase.accepted.provider_origin,
            accepted_fingerprint=purchase.accepted.offer.fingerprint,
        )
        retained: set[SubscriptionRelationship] = set()
        point_observation_id = None
        try:
            for observation in history:
                if point_observation_id is None:
                    point_observation_id = observation.observation_id
                proof = RetainedPointEvidence.model_validate(observation.evidence_document)
                if proof.point_relationship is None:
                    continue  # Legacy/absent point evidence cannot erase an earlier relationship.
                retained.add(proof.point_relationship)
                if complete_owned_point(proof):
                    break  # This complete owned point supersedes only earlier observations.
        except ValidationError:
            raise PurchaseInventoryIncomplete() from None
        finally:
            history.close()
        return InventoryPointHistory(
            purchase.id,
            sub.subscription_id,
            point_observation_id,
            tuple(sorted(retained, key=lambda item: (item.agreement_id, item.tariff_id))),
        )


def verify_inventory_point_history(db: Session, result: InventoryResult) -> None:
    """Caller holds the user lock through the decision; source writers use it too."""
    # Complete canonical reads need no history scan, but their claim can become
    # stale after apply. Check every product's receipt, not only the selected one.
    for source in result.sources:
        if not complete_owned_point(source.proof):
            continue
        sub = purchases.linked_subscription(db, source.purchase.id)
        if sub is None or (
            sub.subscription_id != source.subject.subscription_id
            or sub.reconciliation_fencing_token != source.subject.fence
            or sub.latest_observation_id != source.observation_id
        ):
            raise InventoryStale()
    for history in result.point_history:
        purchase = next(item for item in result.purchases if item.id == history.purchase_id)
        sub = purchases.linked_subscription(db, purchase.id)
        if sub is None or sub.subscription_id != history.subscription_id:
            raise InventoryStale()
        # A claim may already be in flight when history is read. Its subsequent
        # incomplete point can append evidence without changing either the
        # captured fencing token or latest_observation_id: compare the point head.
        latest = billing_reconciliation.latest_subscription_point_observation(
            db,
            sub,
            schema=RECONCILIATION_SCHEMA,
            provider_origin=purchase.accepted.provider_origin,
            accepted_fingerprint=purchase.accepted.offer.fingerprint,
        )
        if latest != history.point_observation_id:
            raise InventoryStale()
