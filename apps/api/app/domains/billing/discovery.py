"""Persist bounded discovery observations before the final product decision lock."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.paid_policy import CandidateConclusion
from app.domains.billing.reconciliation_contracts import SubscriptionProof
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import Purchase
from app.models import BillingStateObservation, BillingStateObservationKind
from app.infrastructure.queries import paid_access as queries

DISCOVERY_SCHEMA = "target-product-discovery:v2"


class DiscoveredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    identity: str
    agreement_id: str
    purchase_id: UUID | None = None
    accepted_fingerprint: str | None = None
    conclusion: CandidateConclusion
    reads: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    calendar: dict[str, str | None] = {}


class ProductDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    read_started_at: datetime
    read_finished_at: datetime
    complete: bool
    candidates: tuple[DiscoveredCandidate, ...]
    linked_proof: SubscriptionProof | None = None


def persist_discovery(
    factory: SessionFactory,
    purchase: Purchase,
    customer: CustomerOpen,
    evidence: ProductDiscovery,
    *,
    fence: int | None = None,
    work_id: UUID | None = None,
    generation: int | None = None,
) -> UUID:
    # Evidence alone cannot grant access. Provenance/fences are checked again by
    # the serialized apply transaction. No product lock or provider I/O here.
    document = evidence.model_dump(mode="json")
    document.update(
        {
            "purchase_id": str(purchase.id),
            "customer_id": str(customer.customer_id),
            "customer_fence": str(customer.fence),
            "provider_customer_id": customer.provider_id,
            "provider_origin": purchase.accepted.provider_origin,
            "accepted_fingerprint": purchase.accepted.offer.fingerprint,
            "operations": [[str(op.id), str(op.fence), op.bound_id] for op in purchase.operations],
            "fence": fence,
            "generation": generation,
        }
    )
    with factory() as db:
        scope_id = queries.scope_id(db, purchase.user_id, purchase.accepted.selection.product_id)
        observation = BillingStateObservation(
            observation_kind=BillingStateObservationKind.TARGET_PRODUCT_DISCOVERY,
            external_billing_account_id=purchase.account_id,
            user_id=purchase.user_id,
            product_id=purchase.accepted.selection.product_id,
            purchase_intent_id=purchase.id,
            access_scope_id=scope_id,
            work_item_id=work_id,
            observed_at=evidence.read_finished_at,
            evidence_schema_version=DISCOVERY_SCHEMA,
            evidence_document=document,
            completeness_classification="complete" if evidence.complete else "incomplete",
            result_classification="candidate_proof",
        )
        db.add(observation)
        db.flush()
        identity = observation.observation_id
        db.commit()
        return identity
