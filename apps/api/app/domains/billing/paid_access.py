"""Shared caller-transaction writer: source decisions and whole-user semantic commit."""

from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session

from app.domains.billing.discovery import DISCOVERY_SCHEMA, ProductDiscovery
from app.domains.billing.paid_allowances import materialize_allowance
from app.domains.billing.paid_contracts import EFFECTIVE_SCHEMA, EffectiveState, PaidGrant, canonical_state
from app.domains.billing.paid_policy import (
    CandidateConclusion,
    PaidDecision,
    PrimaryCandidate,
    first_primary,
    paid_decision,
)
from app.domains.billing.reconciliation_contracts import SubscriptionProof
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.contracts import Purchase
from app.infrastructure.queries import paid_access as queries
from app.models import (
    AccessInvalidationOutbox,
    BillingProductAccessScope,
    BillingStateObservation,
    BillingStateObservationKind,
    ExternalSubscription,
    PaidAccessState,
    User,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)


def _select_primary(
    db: Session,
    scope: BillingProductAccessScope,
    subscription: ExternalSubscription,
    purchase: Purchase,
    discovery_id: UUID | None,
    now: datetime,
    *,
    fence: int | None,
    generation: int | None,
    proof: SubscriptionProof,
) -> bool:
    if scope.primary_subscription_id is not None:
        return scope.primary_subscription_id == subscription.subscription_id
    if scope.primary_retired_at is not None and as_utc(purchase.created_at) <= as_utc(scope.primary_retired_at):
        return False
    observation = queries.discovery(db, discovery_id) if discovery_id else None
    if observation is None or (
        observation.evidence_schema_version != DISCOVERY_SCHEMA
        or observation.user_id != purchase.user_id
        or observation.purchase_intent_id != purchase.id
        or observation.product_id != subscription.product_id
        or observation.external_billing_account_id != purchase.account_id
    ):
        return False
    evidence = observation.evidence_document
    if (
        evidence.get("fence") != fence
        or evidence.get("generation") != generation
        or evidence.get("accepted_fingerprint") != purchase.accepted.offer.fingerprint
        or evidence.get("provider_origin") != purchase.accepted.provider_origin
        or evidence.get("operations") != [[str(op.id), str(op.fence), op.bound_id] for op in purchase.operations]
    ):
        return False
    # The observation is an immutable checked internal document, never source JSON.
    observed = ProductDiscovery.model_validate({key: evidence[key] for key in ProductDiscovery.model_fields})
    if observed.read_finished_at > now or observed.read_started_at + timedelta(hours=6) <= now:
        return False
    candidates = {item.identity: PrimaryCandidate(item.identity, item.conclusion) for item in observed.candidates}
    own = next((item for item in observed.candidates if item.identity == subscription.external_subscription_id), None)
    if own is None or (own.purchase_id, own.agreement_id, own.accepted_fingerprint) != (
        purchase.id,
        subscription.external_agreement_id,
        purchase.accepted.offer.fingerprint,
    ):
        return False
    if own.calendar != proof.calendar:
        return False
    for local in queries.subscriptions(db, purchase.user_id, subscription.product_id):
        if local.lifecycle_status == Lifecycle.ENDED:
            continue
        identity = local.external_subscription_id or str(local.subscription_id)
        if identity not in candidates:
            # A locally known source hidden by the list remains relevant.
            candidates[identity] = PrimaryCandidate(identity, CandidateConclusion.INCOMPLETE)
        elif local.subscription_id != subscription.subscription_id:
            candidate = next(item for item in observed.candidates if item.identity == identity)
            latest = queries.discovery(db, local.latest_observation_id) if local.latest_observation_id else None
            if candidate.purchase_id != local.purchase_intent_id or (
                latest is not None and as_utc(latest.observed_at) > observed.read_started_at
            ):
                candidates[identity] = PrimaryCandidate(identity, CandidateConclusion.INCOMPLETE)
    if not first_primary(subscription.external_subscription_id, tuple(candidates.values()), complete=observed.complete):
        return False
    scope.primary_subscription_id = subscription.subscription_id
    return True


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
    discovery_id: UUID | None = None,
    review: bool = False,
    fence: int | None = None,
    generation: int | None = None,
) -> None:
    """Caller holds user first, then original purchase/scope/source locks."""
    decision = paid_decision(proof, review=review)
    primary = scope.primary_subscription_id == subscription.subscription_id
    if decision == PaidDecision.GRANT and skew_seconds is not None:
        primary = _select_primary(
            db, scope, subscription, purchase, discovery_id, now, fence=fence, generation=generation, proof=proof
        )
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
        value = proof.calendar.get("subscription_end_date")
        if value and len(value) > 10:
            parsed = datetime.fromisoformat(value)
            if parsed.utcoffset() is not None:
                grant_end = as_utc(parsed) - timedelta(seconds=skew_seconds)
                deadline = min(deadline, grant_end)
        if deadline <= now:
            scope.effective_access_document = None
            scope.effective_access_until = deadline
            return
        allowance = materialize_allowance(db, subscription, purchase.accepted, proof.cycle, skew_seconds=skew_seconds)
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
) -> BillingStateObservation:
    basis = queries.discovery(db, scope.access_basis_observation_id) if scope.access_basis_observation_id else None
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
        evidence_document={"source_observation_id": str(scope.access_basis_observation_id)},
        completeness_classification="complete",
        result_classification="local_reduction",
    )


def commit_paid_state(
    db: Session,
    user: User,
    cause: BillingStateObservation,
    now: datetime,
    *,
    related_causes: tuple[BillingStateObservation, ...] = (),
) -> int:
    """Canonicalize the complete set under the caller's user lock; never commit."""
    states = []
    reductions = []
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
            or scope.effective_access_until is None
            or as_utc(scope.effective_access_until) <= now
        ):
            if primary is not None:
                reductions.append(
                    _reduction_cause(
                        db,
                        scope,
                        primary,
                        now,
                        min(now, as_utc(scope.effective_access_until)) if scope.effective_access_until else now,
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
        # Independently supported UTC bounds can reduce metering; calendar dates
        # alone never expire or refill it.
        state = state.model_copy(
            update={
                "allowances": tuple(
                    item
                    for item in state.allowances
                    if item.period_end is None or datetime.fromisoformat(item.period_end) > now
                )
            }
        )
        scope.effective_access_document = state.model_dump(mode="json")
        states.append(state)
    effective = canonical_state(states).model_dump(mode="json")
    row = queries.state(db, user.id)
    outbox = queries.outbox(db, user.id)
    if (row.effective_state_document if row else EffectiveState().model_dump(mode="json")) == effective:
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
    return revision
