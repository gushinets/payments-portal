"""Bounded inventory evidence and primary decisions over already committed facts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.domains.billing.customers import lock_user
from app.domains.billing.paid_access import apply_paid_source
from app.domains.billing.paid_policy import CandidateConclusion, PrimaryCandidate, first_primary
from app.domains.billing.reconciliation_contracts import RECONCILIATION_SCHEMA, ReconciliationResult
from app.domains.billing.work import verify_claim
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.contracts import Purchase
from app.infrastructure.queries import billing_reconciliation, paid_access
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalSubscription,
    ManualReviewCase,
    PurchaseIntentState,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
)

if TYPE_CHECKING:
    from app.domains.purchases.inventory_contracts import InventoryResult

DISCOVERY_SCHEMA = "target-product-discovery:v3"


class DiscoveredCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    identity: str
    agreement_id: str
    conclusion: CandidateConclusion
    purchase_id: UUID | None = None
    subscription_id: UUID | None = None
    observation_id: UUID | None = None
    fence: int | None = None


class ProductDiscovery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product_id: str
    read_started_at: datetime
    read_finished_at: datetime
    primary_subscription_id: UUID | None = None
    primary_retired_at: datetime | None = None
    complete: bool
    # Up to twenty known bindings plus twenty discovered relevant objects.
    candidates: tuple[DiscoveredCandidate, ...] = Field(max_length=40)


def scope_versions(factory: SessionFactory, purchase: Purchase) -> dict[str, tuple[UUID | None, datetime | None]]:
    with factory() as db:
        lock_user(db, purchase.user_id)
        return {
            scope.product_id: (scope.primary_subscription_id, scope.primary_retired_at)
            for scope in paid_access.scopes(db, purchase.user_id)
        }


def persist_discoveries(factory: SessionFactory, claim: WorkClaim, result: InventoryResult) -> InventoryResult:
    """Persist evidence before the final decision; it never applies source facts."""
    from app.domains.purchases.inventory import validate_inventory

    with factory() as db:
        if not result.purchases:
            return result
        lock_user(db, result.purchases[0].user_id)
        validate_inventory(db, result)
        identities = []
        for product in result.products:
            purchase = next(
                item for item in result.purchases if item.accepted.selection.product_id == product.product_id
            )
            scope = billing_reconciliation.scope(db, purchase.user_id, product.product_id)
            if scope is None:
                scope = BillingProductAccessScope(user_id=purchase.user_id, product_id=product.product_id)
                db.add(scope)
                db.flush()
            observation = BillingStateObservation(
                observation_kind=BillingStateObservationKind.TARGET_PRODUCT_DISCOVERY,
                external_billing_account_id=purchase.account_id,
                user_id=purchase.user_id,
                product_id=product.product_id,
                access_scope_id=scope.access_scope_id,
                work_item_id=claim.id,
                observed_at=product.read_finished_at,
                evidence_schema_version=DISCOVERY_SCHEMA,
                evidence_document={
                    **product.model_dump(mode="json"),
                    "generation": claim.generation,
                    "customer_id": str(result.customer.customer_id),
                },
                completeness_classification="complete" if product.complete else "incomplete",
                result_classification="candidate_proof",
            )
            db.add(observation)
            db.flush()
            identities.append(observation.observation_id)
        verify_claim(db, claim)  # Queue ownership last; evidence is harmless until selection.
        db.commit()
        return replace(result, discovery_ids=tuple(identities))


def _source_current(db: Session, source: ReconciliationResult, sub: ExternalSubscription) -> bool:
    observation = paid_access.observation(db, source.observation_id)
    document = source.proof.document()
    document.update(reads=list(source.proof.reads), reasons=list(source.proof.reasons))
    return (
        sub.latest_observation_id == source.observation_id
        and sub.reconciliation_fencing_token == source.subject.fence
        and sub.external_subscription_id == source.subject.provider_subscription_id
        and sub.external_agreement_id == source.subject.agreement_id
        and sub.purchase_intent_id == source.purchase.id
        and observation is not None
        and observation.evidence_schema_version == RECONCILIATION_SCHEMA
        and observation.subscription_id == sub.subscription_id
        and observation.user_id == source.purchase.user_id
        and observation.product_id == sub.product_id
        and observation.external_billing_account_id == source.purchase.account_id
        and all(observation.evidence_document.get(key) == value for key, value in document.items())
    )


def primary_review(db: Session, subscription: ExternalSubscription) -> None:
    if paid_access.metric_review(db, str(subscription.subscription_id), "subscription") is None:
        db.add(
            ManualReviewCase(
                reason_code="primary_selection_required",
                scope_kind="subscription",
                scope_reference=str(subscription.subscription_id),
                evidence_schema_version=DISCOVERY_SCHEMA,
                evidence_document={"supporting_observation_id": str(subscription.latest_observation_id)},
                case_state="open",
            )
        )


def select_primaries(
    db: Session,
    result: InventoryResult,
    claim: WorkClaim,
    now: datetime,
    *,
    clock_skew_seconds: int | None,
    allow_simulated_metering: bool,
) -> tuple[BillingStateObservation, ...]:
    """Caller holds user/purchase locks. Reuse committed receipts, never reapply facts."""
    from app.domains.purchases.inventory_contracts import InventoryStale

    causes = []
    for identity, product in zip(result.discovery_ids, result.products, strict=True):
        cause = paid_access.observation(db, identity)
        if cause is None or (
            cause.evidence_schema_version != DISCOVERY_SCHEMA
            or cause.work_item_id != claim.id
            or cause.evidence_document
            != {
                **product.model_dump(mode="json"),
                "generation": claim.generation,
                "customer_id": str(result.customer.customer_id),
            }
            or not claim.started_at <= product.read_started_at <= product.read_finished_at <= now
            or product.read_finished_at >= claim.expires_at
        ):
            raise InventoryStale()
        scope = billing_reconciliation.scope(db, cause.user_id, product.product_id)
        local = paid_access.subscriptions(db, cause.user_id, product.product_id)
        if (scope.primary_subscription_id, scope.primary_retired_at) != (
            product.primary_subscription_id,
            product.primary_retired_at,
        ):
            continue  # A concurrent choice/retirement cannot become first admission.
        if not product.complete:
            continue
        sources = {
            source.subject.subscription_id: source
            for source in result.sources
            if source.purchase.accepted.selection.product_id == product.product_id
        }
        candidates = {item.identity: PrimaryCandidate(item.identity, item.conclusion) for item in product.candidates}
        for sub in local:
            source = sources.get(sub.subscription_id)
            if source is not None:
                candidate = next(
                    (item for item in product.candidates if item.subscription_id == sub.subscription_id), None
                )
                if candidate is None or (
                    (candidate.observation_id, candidate.fence, candidate.purchase_id)
                    != (source.observation_id, source.subject.fence, source.purchase.id)
                    or not _source_current(db, source, sub)
                ):
                    raise InventoryStale()
            if sub.lifecycle_status != Lifecycle.ENDED and source is None:
                candidates[sub.external_subscription_id] = PrimaryCandidate(
                    sub.external_subscription_id, CandidateConclusion.INCOMPLETE
                )
        eligible = [
            sub
            for sub in local
            if sub.subscription_id in sources
            and candidates.get(sub.external_subscription_id)
            == PrimaryCandidate(sub.external_subscription_id, CandidateConclusion.ELIGIBLE)
        ]
        if scope.primary_subscription_id is not None:
            for sub in eligible:
                if sub.subscription_id != scope.primary_subscription_id:
                    primary_review(db, sub)
            continue
        for sub in eligible:
            purchase = sources[sub.subscription_id].purchase
            if scope.primary_retired_at is not None and as_utc(purchase.created_at) <= as_utc(scope.primary_retired_at):
                primary_review(db, sub)
                continue
            if not first_primary(sub.external_subscription_id, tuple(candidates.values()), complete=True):
                if len(eligible) > 1:
                    primary_review(db, sub)
                continue
            if (
                clock_skew_seconds is None
                or purchase.state == PurchaseIntentState.MANUAL_REVIEW
                or sub.commercial_access_status != Commercial.ELIGIBLE
                or sub.financial_access_status != Financial.ALLOWED
                or sub.lifecycle_status != Lifecycle.ACTIVE
                or billing_reconciliation.open_reviews(db, sub.subscription_id)
                or as_utc(sub.projection_valid_until) <= now
            ):
                continue
            selected = BillingStateObservation(
                observation_kind=BillingStateObservationKind.PRIMARY_SELECTION,
                external_billing_account_id=purchase.account_id,
                user_id=purchase.user_id,
                product_id=product.product_id,
                access_scope_id=scope.access_scope_id,
                subscription_id=sub.subscription_id,
                basis_observation_id=cause.observation_id,
                work_item_id=claim.id,
                observed_at=now,
                evidence_schema_version="primary-selection:v1",
                evidence_document={
                    "source_observation_id": str(sub.latest_observation_id),
                    "fence": sub.reconciliation_fencing_token,
                },
                completeness_classification="complete",
                result_classification="primary_selected",
            )
            db.add(selected)
            db.flush()
            scope.primary_subscription_id = sub.subscription_id
            source = sources[sub.subscription_id]
            apply_paid_source(
                db,
                scope,
                sub,
                purchase,
                source.proof,
                selected,
                now,
                skew_seconds=clock_skew_seconds,
                allow_simulated_metering=allow_simulated_metering,
            )
            causes.append(selected)
    return tuple(causes)
