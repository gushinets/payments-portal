"""Shared caller-transaction writer: source decisions and whole-user semantic commit."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.domains.billing.paid_allowances import materialize_allowance
from app.domains.billing.paid_deadlines import schedule_deadline
from app.domains.billing.paid_contracts import EFFECTIVE_SCHEMA, EffectiveState, PaidGrant, canonical_state
from app.domains.billing.paid_policy import MeteringPolicy, PaidDecision, paid_decision
from app.domains.billing.reconciliation_contracts import SubscriptionProof
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.contracts import Purchase
from app.domains.purchases.evidence import accepted
from app.infrastructure.queries import paid_access as queries
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalSubscription,
    PaidAccessState,
    User,
    PurchaseIntent,
    PurchaseIntentState,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperationState as OperationState,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)


def resolve_access_end(
    db: Session, subscription: ExternalSubscription, proof: SubscriptionProof
) -> tuple[datetime | None, UUID | None]:
    """A less precise read cannot erase a previously proven raw source boundary."""
    if proof.access_end_at is not None:
        return proof.access_end_at, None
    basis = queries.access_end_observation(db, subscription)
    if basis is None:
        return None, None
    return as_utc(datetime.fromisoformat(basis.evidence_document["access_end_at"])), basis.observation_id


def apply_paid_source(
    db: Session,
    scope: BillingProductAccessScope,
    subscription: ExternalSubscription,
    purchase: Purchase,
    proof: SubscriptionProof,
    observation: BillingStateObservation,
    now: datetime,
    *,
    skew_seconds: int | None,
    access_end_at: datetime | None,
    review: bool = False,
    metering_policy: MeteringPolicy = MeteringPolicy.NONPRODUCTION,
) -> None:
    """Caller holds user first, then original purchase/scope/source locks."""
    decision = paid_decision(proof, review=review)
    primary = scope.primary_subscription_id == subscription.subscription_id
    if not primary:
        return
    if subscription.lifecycle_status == Lifecycle.ENDED:
        scope.primary_subscription_id = None
        scope.primary_retired_at = now
    if decision == PaidDecision.DENY:
        scope.effective_access_document = None
        scope.effective_access_until = None
        scope.access_basis_observation_id = observation.observation_id
        return
    if decision == PaidDecision.GRANT and skew_seconds is not None:
        deadline = as_utc(subscription.projection_valid_until) - timedelta(seconds=skew_seconds)
        grant_end = None
        if access_end_at is not None:
            grant_end = access_end_at - timedelta(seconds=skew_seconds)
            deadline = min(deadline, grant_end)
        if deadline <= now:
            scope.effective_access_document = None
            scope.effective_access_until = deadline
            return
        terms = purchase.accepted.technical_terms
        allowance = (
            materialize_allowance(db, subscription, purchase.accepted, proof.cycle, skew_seconds=skew_seconds)
            if terms is not None and metering_policy.permits(terms.provenance)
            else None
        )
        if allowance is not None and allowance.period_start and datetime.fromisoformat(allowance.period_start) > now:
            # Issuance freezes history, not authority. Only another source apply
            # at/after the proven start may add this bucket to the committed set.
            allowance = None
        state = EffectiveState(
            grants=(
                PaidGrant(product_id=subscription.product_id, valid_until=grant_end.isoformat() if grant_end else None),
            ),
            allowances=(allowance,) if allowance else (),
        )
        scope.effective_access_document = state.model_dump(mode="json")
        scope.effective_access_until = deadline
        scope.access_basis_observation_id = observation.observation_id
    # Unknown source attempts never refresh the saved access deadline or create
    # a bucket. Complete commercial/lifecycle proof with an ambiguous calendar
    # above still yields independently supported product access.


def _reduction_cause(
    db: Session,
    scope: BillingProductAccessScope,
    subscription: ExternalSubscription,
    now: datetime,
    effective_at: datetime,
    *,
    reason: str = "effective_deadline",
) -> BillingStateObservation:
    basis = queries.observation(db, scope.access_basis_observation_id) if scope.access_basis_observation_id else None
    return BillingStateObservation(
        observation_kind=BillingStateObservationKind.DETERMINISTIC_ACCESS_BOUNDARY,
        external_billing_account_id=subscription.external_billing_account_id,
        user_id=scope.user_id,
        product_id=scope.product_id,
        access_scope_id=scope.access_scope_id,
        subscription_id=subscription.subscription_id,
        basis_observation_id=basis.observation_id if basis and basis.access_scope_id == scope.access_scope_id else None,
        observed_at=now,
        effective_at=effective_at,
        evidence_schema_version="paid-access-reduction:v1",
        evidence_document={"source_observation_id": str(scope.access_basis_observation_id), "reason": reason},
        completeness_classification="complete",
        result_classification="local_reduction",
    )


def commit_paid_state(
    db: Session,
    user: User,
    cause: BillingStateObservation | None,
    now: datetime,
    *,
    related_causes: tuple[BillingStateObservation, ...] = (),
    metering_policy: MeteringPolicy = MeteringPolicy.NONPRODUCTION,
    schedule_deadlines: bool = True,
) -> int:
    """Canonicalize under the user lock; a pre-refresh reduction defers queue writes."""
    states = []
    reductions = []
    deadlines = []
    for scope in queries.scopes(db, user.id):
        if scope.effective_access_document is None:
            continue
        sources = queries.subscriptions(db, user.id, scope.product_id)
        primary = next((row for row in sources if row.subscription_id == scope.primary_subscription_id), None)
        if (
            primary is None
            or primary.financial_access_status != Financial.ALLOWED
            or primary.commercial_access_status != Commercial.ELIGIBLE
            or primary.lifecycle_status != Lifecycle.ACTIVE
            or _dependency_blocked(db, primary)
            or scope.effective_access_until is None
            or as_utc(scope.effective_access_until) <= now
        ):
            source = primary or next(iter(sources), None)
            if source is not None:
                reductions.append(
                    _reduction_cause(
                        db,
                        scope,
                        source,
                        now,
                        min(now, as_utc(scope.effective_access_until)) if scope.effective_access_until else now,
                        reason="effective_deadline"
                        if scope.effective_access_until and as_utc(scope.effective_access_until) <= now
                        else "source_or_dependency_ineligible",
                    )
                )
            scope.effective_access_document = None
            continue
        state = EffectiveState.model_validate(scope.effective_access_document)
        ended_periods = [
            datetime.fromisoformat(item.period_end)
            for item in state.allowances
            if item.period_end and datetime.fromisoformat(item.period_end) <= now
        ]
        if ended_periods:
            reductions.append(_reduction_cause(db, scope, primary, now, min(ended_periods)))
        metering_refused = False
        if state.allowances:
            purchase = db.get(PurchaseIntent, primary.purchase_intent_id) if primary.purchase_intent_id else None
            terms = accepted(purchase).technical_terms if purchase else None
            metering_refused = not metering_policy.permits(terms.provenance if terms else None)
            if metering_refused:
                reductions.append(
                    _reduction_cause(db, scope, primary, now, now, reason="metering_provenance_unavailable")
                )
        # Independently supported UTC bounds can reduce metering; calendar dates
        # alone never expire or refill it.
        state = state.model_copy(
            update={
                "allowances": tuple(
                    item
                    for item in state.allowances
                    if not metering_refused
                    and (item.period_start is None or datetime.fromisoformat(item.period_start) <= now)
                    and (item.period_end is None or datetime.fromisoformat(item.period_end) > now)
                )
            }
        )
        scope.effective_access_document = state.model_dump(mode="json")
        states.append(state)
        deadlines.append((primary, scope))
    effective = canonical_state(states).model_dump(mode="json")
    row = queries.state(db, user.id)
    outbox = queries.outbox(db, user.id)
    if (row.effective_state_document if row else EffectiveState().model_dump(mode="json")) == effective:
        if schedule_deadlines:
            for primary, scope in deadlines:
                schedule_deadline(db, primary, scope, evaluated_at=now)
        return row.access_revision if row else 0
    revision = row.access_revision + 1 if row else 1
    if row is None:
        row = PaidAccessState(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            access_revision=revision,
            effective_state_schema_version=EFFECTIVE_SCHEMA,
            effective_state_document=effective,
            committed_at=now,
        )
        db.add(row)
    else:
        row.access_revision = revision
        row.effective_state_document = effective
        row.committed_at = now
    if cause is None:
        if not reductions:
            raise ValueError("material access change requires causal evidence")
        cause = reductions.pop()
        db.add(cause)
    if cause.resulting_access_revision is not None:
        cause = BillingStateObservation(
            observation_kind=cause.observation_kind,
            external_billing_account_id=cause.external_billing_account_id,
            user_id=user.id,
            product_id=cause.product_id,
            access_scope_id=cause.access_scope_id,
            subscription_id=cause.subscription_id,
            purchase_intent_id=cause.purchase_intent_id,
            basis_observation_id=cause.observation_id,
            observed_at=now,
            effective_at=cause.effective_at,
            evidence_schema_version="paid-access-cause:v1",
            evidence_document={},
            completeness_classification="complete",
            result_classification="material_change",
        )
        db.add(cause)
    cause.resulting_access_revision = revision
    for reduction in reductions:
        reduction.resulting_access_revision = revision
        db.add(reduction)
    for related in related_causes:
        if related.resulting_access_revision is None:
            related.resulting_access_revision = revision
    if outbox is None:
        db.add(
            AccessInvalidationOutbox(
                tenant_id=user.tenant_id,
                region=user.region,
                user_id=user.id,
                pending_revision=revision,
                delivered_revision=0,
                attempt_count=0,
                next_attempt_at=now,
            )
        )
    else:
        outbox.pending_revision = max(outbox.pending_revision, revision)
    db.flush()
    if schedule_deadlines:
        for primary, scope in deadlines:
            schedule_deadline(db, primary, scope, evaluated_at=now)
    return revision


def _dependency_blocked(db: Session, subscription: ExternalSubscription) -> bool:
    customer, purchase, operations = queries.dependencies(db, subscription)
    return (
        customer is None
        or customer.binding_state != Binding.BOUND
        or (purchase is not None and purchase.state == PurchaseIntentState.MANUAL_REVIEW)
        or any(op.operation_state == OperationState.MANUAL_REVIEW for op in operations)
    )


def reduce_paid_access(db: Session, user_id: UUID) -> int:
    """Finish the caller's restrictions once, under its existing user lock."""
    from app.infrastructure.queries.billing_reconciliation import database_now

    return commit_paid_state(db, db.get(User, user_id), None, as_utc(database_now(db)))
