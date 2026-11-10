"""Bounded inventory evidence and primary decisions over already committed facts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.domains.billing import work
from app.domains.billing.background_recovery import INVENTORY, INVENTORY_SECONDS
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import lock_user
from app.domains.billing.paid_access import apply_paid_source, resolve_access_end
from app.domains.billing.paid_policy import MeteringPolicy, CandidateConclusion, PrimaryCandidate, first_primary
from app.domains.billing.reconciliation_contracts import RECONCILIATION_SCHEMA, ReconciliationResult
from app.domains.billing.work import verify_claim
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import Purchase
from app.infrastructure.queries import billing_reconciliation, paid_access, purchases, billing_background as queries
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalSubscription,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
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
    metering_policy: MeteringPolicy,
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
            source = sources[sub.subscription_id]
            access_end_at, end_basis = resolve_access_end(db, sub, source.proof)
            selection_evidence: dict[str, object] = {
                "source_observation_id": str(sub.latest_observation_id),
                "fence": sub.reconciliation_fencing_token,
            }
            if end_basis is not None:
                selection_evidence["retained_access_end"] = {
                    "observation_id": str(end_basis),
                    "access_end_at": access_end_at.isoformat(),
                }
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
                evidence_document=selection_evidence,
                completeness_classification="complete",
                result_classification="primary_selected",
            )
            db.add(selected)
            db.flush()
            scope.primary_subscription_id = sub.subscription_id
            apply_paid_source(
                db,
                scope,
                sub,
                purchase,
                source.proof,
                selected,
                now,
                skew_seconds=clock_skew_seconds,
                access_end_at=access_end_at,
                metering_policy=metering_policy,
            )
            causes.append(selected)
    return tuple(causes)


def apply_inventory(
    factory: SessionFactory,
    claim: WorkClaim,
    result: "InventoryResult",
    reason: str | None,
    *,
    clock_skew_seconds: int | None = None,
    metering_policy: MeteringPolicy = MeteringPolicy.NONPRODUCTION,
) -> None:
    """Validate all original versions, then finish the customer job once."""
    from app.domains.purchases.inventory import invalidate_unsent, validate_inventory
    from app.domains.purchases.inventory_contracts import InventoryStale

    with factory() as db:
        customer = queries.customer(db, UUID(claim.reference))
        if claim.kind != INVENTORY or customer is None or customer.customer_id != result.customer.customer_id:
            raise BillingRefused("billing_work_stale", 409)
        user = lock_user(db, customer.user_id)
        validate_inventory(db, result)
        locked = []
        for purchase in sorted(result.purchases, key=lambda item: (item.accepted.selection.product_id, str(item.id))):
            if purchase.id not in result.conflicts:
                continue
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
            target = next(op for op in operations if op.operation_kind == Kind.SUBSCRIPTION)
            locked.append((purchase, row, target, scope, subscription))
        now = as_utc(billing_reconciliation.database_now(db))
        causes = (
            list(
                select_primaries(
                    db,
                    result,
                    claim,
                    now,
                    clock_skew_seconds=clock_skew_seconds,
                    metering_policy=metering_policy,
                )
            )
            if result.discovery_ids
            else []
        )
        for purchase, row, target, scope, subscription in locked:
            unsent = subscription is None and target.operation_state in {State.PENDING, State.PROVEN_NOT_SENT}
            selected_primary = (
                subscription is not None and scope.primary_subscription_id == subscription.subscription_id
            )
            if unsent:
                invalidate_unsent(db, purchase)
            elif selected_primary:
                from app.infrastructure.queries.paid_access import metric_review
                from app.models import ManualReviewCase

                if metric_review(db, str(scope.access_scope_id), "product_competitor") is None:
                    db.add(
                        ManualReviewCase(
                            reason_code="customer_inventory_competitor",
                            scope_kind="product_competitor",
                            scope_reference=str(scope.access_scope_id),
                            evidence_schema_version="customer-inventory:v2",
                            evidence_document={},
                            case_state="open",
                        )
                    )
            else:
                financial._review(db, row, target, "customer_inventory_conflict")
            from app.models import (
                BillingStateObservation,
                BillingStateObservationKind,
                ExternalSubscriptionCommercialAccessStatus as Commercial,
            )

            if subscription is not None and not selected_primary:
                subscription.commercial_access_status = Commercial.INELIGIBLE
            cause = BillingStateObservation(
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
                result_classification="admission_blocked" if unsent else "review_required",
                resulting_access_revision=None,
            )
            db.add(cause)
            db.flush()
            causes.append(cause)
        if causes:
            from app.domains.billing.paid_access import commit_paid_state

            commit_paid_state(
                db,
                user,
                causes[-1],
                now,
                related_causes=tuple(causes[:-1]),
                metering_policy=metering_policy,
            )
        queue = work.verify_claim(db, claim)  # Queue ownership last; stale completion rolls back every decision.
        if queue.coalescing_key != f"{customer.external_billing_account_id}:{customer.customer_id}":
            raise BillingRefused("billing_work_stale", 409)
        if result.discovery_ids and queue.enqueue_generation != claim.generation:
            raise InventoryStale()
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
        queue.priority = int(reason is not None or queue.enqueue_generation != claim.generation)
        db.commit()
