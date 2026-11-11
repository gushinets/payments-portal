"""Paid projection reads and locks; caller owns the user lock and transaction."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, SQLColumnExpression, Select, BigInteger, case, exists, func, or_, select, Text, cast
from sqlalchemy.orm import Session

from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    ExternalBillingCustomer,
    ExternalCreateOperation,
    ExternalSubscription,
    ManualReviewCase,
    PaidAccessState,
    PurchasedAllowance,
    PurchaseIntent,
    BillingWorkItem,
    User,
)


def allowances(db: Session, subscription_id: UUID, component: str, metric: str) -> list[PurchasedAllowance]:
    return list(
        db.scalars(
            select(PurchasedAllowance)
            .where(
                PurchasedAllowance.subscription_id == subscription_id,
                PurchasedAllowance.source_component_id == component,
                PurchasedAllowance.metric_key == metric,
            )
            .order_by(PurchasedAllowance.created_at, PurchasedAllowance.allowance_id)
        )
    )


def metric_review(db: Session, reference: str, kind: str = "subscription_metric") -> ManualReviewCase | None:
    return db.scalar(
        select(ManualReviewCase).where(
            ManualReviewCase.scope_kind == kind,
            ManualReviewCase.scope_reference == reference,
            ManualReviewCase.case_state == "open",
        )
    )


def metric_cycle_allowances(
    db: Session, subscription_id: UUID, metric: str, cycle_key: str
) -> list[PurchasedAllowance]:
    return list(
        db.scalars(
            select(PurchasedAllowance).where(
                PurchasedAllowance.subscription_id == subscription_id,
                PurchasedAllowance.metric_key == metric,
                PurchasedAllowance.provider_cycle_key == cycle_key,
            )
        )
    )


def scopes(db: Session, user_id: UUID) -> list[BillingProductAccessScope]:
    return list(
        db.scalars(
            select(BillingProductAccessScope)
            .where(BillingProductAccessScope.user_id == user_id)
            .order_by(BillingProductAccessScope.product_id)
            .with_for_update()
        )
    )


def subscriptions(db: Session, user_id: UUID, product_id: str) -> list[ExternalSubscription]:
    return list(
        db.scalars(
            select(ExternalSubscription)
            .where(ExternalSubscription.user_id == user_id, ExternalSubscription.product_id == product_id)
            .order_by(ExternalSubscription.subscription_id)
            .with_for_update()
        )
    )


def state(db: Session, user_id: UUID) -> PaidAccessState | None:
    return db.scalar(select(PaidAccessState).where(PaidAccessState.user_id == user_id).with_for_update())


def outbox(db: Session, user_id: UUID) -> AccessInvalidationOutbox | None:
    return db.scalar(
        select(AccessInvalidationOutbox).where(AccessInvalidationOutbox.user_id == user_id).with_for_update()
    )


def observation(db: Session, identity: UUID) -> BillingStateObservation | None:
    return db.get(BillingStateObservation, identity)


def access_end_observation(db: Session, sub: ExternalSubscription) -> BillingStateObservation | None:
    """Latest accepted finite end for this permanent source, including after revocation."""
    evidence = BillingStateObservation.evidence_document
    provenance = evidence["provenance"]
    return db.scalar(
        select(BillingStateObservation)
        .where(
            BillingStateObservation.subscription_id == sub.subscription_id,
            BillingStateObservation.external_billing_account_id == sub.external_billing_account_id,
            BillingStateObservation.user_id == sub.user_id,
            BillingStateObservation.product_id == sub.product_id,
            BillingStateObservation.evidence_schema_version == "subscription-reconciliation:v1",
            BillingStateObservation.completeness_classification == "complete",
            BillingStateObservation.result_classification == "COMPLETE_MATCH",
            evidence["access_end_at"].as_string().is_not(None),
            provenance["purchase_intent_id"].as_string() == str(sub.purchase_intent_id),
            provenance["mapping_revision_id"].as_string() == str(sub.mapping_revision_id),
            provenance["provider_subscription_id"].as_string() == sub.external_subscription_id,
            provenance["agreement_id"].as_string() == sub.external_agreement_id,
        )
        .order_by(BillingStateObservation.observed_at.desc(), provenance["fence"].as_string().cast(BigInteger).desc())
        .limit(1)
    )


def dependencies(
    db: Session, sub: ExternalSubscription
) -> tuple[ExternalBillingCustomer | None, PurchaseIntent | None, list[ExternalCreateOperation]]:
    customer = db.get(ExternalBillingCustomer, sub.customer_id)
    purchase = db.get(PurchaseIntent, sub.purchase_intent_id) if sub.purchase_intent_id else None
    operations = list(
        db.scalars(
            select(ExternalCreateOperation)
            .where(
                ExternalCreateOperation.customer_id == sub.customer_id,
                or_(
                    ExternalCreateOperation.purchase_intent_id == sub.purchase_intent_id,
                    ExternalCreateOperation.purchase_intent_id.is_(None),
                ),
            )
            .order_by(ExternalCreateOperation.create_operation_id)
        )
    )
    return customer, purchase, operations


def latest_paid_allowance_end(subscription_id: UUID | SQLColumnExpression[UUID]) -> Select[tuple[datetime | None]]:
    """Keep the latest issued cycle relevant after effective metering expires.

    Match issuance ordering. Calendar-only cycles return no UTC bound, while
    legacy UTC rows without proven calendar meaning never establish urgency.
    """
    return (
        select(PurchasedAllowance.period_end)
        .where(
            PurchasedAllowance.subscription_id == subscription_id,
            PurchasedAllowance.cycle_schema_version.in_(("calendar:v1", "timestamp:v1")),
        )
        .order_by(PurchasedAllowance.created_at.desc(), PurchasedAllowance.allowance_id.desc())
        .limit(1)
    )


def latest_paid_allowance_start(db: Session, subscription_id: UUID) -> datetime | None:
    return db.scalar(
        select(PurchasedAllowance.period_start)
        .where(
            PurchasedAllowance.subscription_id == subscription_id,
            PurchasedAllowance.cycle_schema_version == "timestamp:v1",
        )
        .order_by(PurchasedAllowance.created_at.desc(), PurchasedAllowance.allowance_id.desc())
        .limit(1)
    )


def missing_deadline_users(
    db: Session,
    tenant: str,
    region: str,
    limit: int,
    *,
    permitted_provenances: tuple[str, ...] | None = None,
) -> list[UUID]:
    """Persisted scope/identity, independent of today's source account setting."""
    allowance_end = (
        latest_paid_allowance_end(BillingProductAccessScope.primary_subscription_id)
        .correlate(BillingProductAccessScope)
        .scalar_subquery()
    )
    metering_deadline = case(
        (
            BillingProductAccessScope.effective_access_document["allowances"] != [],
            func.coalesce(allowance_end, BillingProductAccessScope.effective_access_until),
        ),
        else_=BillingProductAccessScope.effective_access_until,
    )
    scheduled = exists().where(
        BillingWorkItem.work_kind == "subscription_trust_expiry",
        BillingWorkItem.scope_reference == cast(BillingProductAccessScope.primary_subscription_id, Text),
        BillingWorkItem.work_state.in_(("pending", "running")),
        BillingWorkItem.next_attempt_at <= BillingProductAccessScope.effective_access_until,
        BillingWorkItem.next_attempt_at <= metering_deadline,
    )
    needs_repair = ~scheduled
    # Application supplies this optional storage filter; persistence does not
    # interpret provenance vocabularies or decide environment policy.
    if permitted_provenances is not None:
        unpermitted = exists().where(
            ExternalSubscription.subscription_id == BillingProductAccessScope.primary_subscription_id,
            ExternalSubscription.purchase_intent_id == PurchaseIntent.purchase_intent_id,
            func.coalesce(PurchaseIntent.accepted_snapshot["technical_terms"]["provenance"].as_string(), "").not_in(
                permitted_provenances
            ),
        )
        needs_repair = or_(
            needs_repair, unpermitted & (BillingProductAccessScope.effective_access_document["allowances"] != [])
        )
    return list(
        db.scalars(
            select(BillingProductAccessScope.user_id)
            .join(User, User.id == BillingProductAccessScope.user_id)
            .where(
                User.tenant_id == tenant,
                User.region == region,
                BillingProductAccessScope.effective_access_document.is_not(None),
                BillingProductAccessScope.effective_access_document != JSON.NULL,
                needs_repair,
            )
            .distinct()
            .order_by(BillingProductAccessScope.user_id)
            .limit(limit)
        )
    )
