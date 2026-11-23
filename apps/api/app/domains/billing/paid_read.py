"""Committed paid state for the cabinet; no source I/O or billing writes."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ValidationError
from sqlalchemy.orm import Session

from app.core.backend_consumers import BackendConsumer
from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import authenticate
from app.domains.billing.paid_contracts import EffectiveState
from app.domains.billing.paid_deadlines import effective_deadline
from app.domains.billing.paid_policy import MeteringPolicy
from app.domains.billing.reconciliation import SOURCE_TRUST
from app.domains.billing.reconciliation_contracts import (
    RECONCILIATION_READ_SCHEMAS,
    CommercialProof,
    IdentityProof,
    SubscriptionLifecycleReason,
)
from app.domains.billing.work import key
from app.domains.catalog.contracts import SourceProvenance
from app.domains.catalog.publication import SessionFactory
from app.domains.catalog.technical_source import TechnicalOwnership
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.contracts import PurchaseRefused
from app.domains.purchases.evidence import accepted
from app.domains.purchases.technical_terms import AcceptedTechnicalTerms
from app.domains.purchases.widget_activation_window import (
    CLOSING_GRACE,
    HANDOFF_DISPLAY,
    WidgetActivationCompletionReason,
    WidgetActivationWindow,
)
from app.infrastructure.queries import paid_read as queries
from app.infrastructure.queries.backend_policies import BackendPolicyConflict, require_current_policy
from app.infrastructure.queries.billing_reconciliation import database_now, open_review_references, primary_selections
from app.models import (
    BillingProductAccessScope,
    BillingStateObservation,
    BillingWorkItem,
    ExternalBillingCustomerBindingState as Binding,
    ExternalSubscriptionCommercialAccessStatus as Commercial,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
    PurchaseIntentState,
)


class ProductPaidStatus(StrEnum):
    CONFIRMED = "confirmed"
    ABSENT = "no_paid_access"
    UNAVAILABLE = "unavailable"


class ActivationCheckStatus(StrEnum):
    CHECKING = "checking"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True)
class ProductEvidence:
    product_id: str
    status: ProductPaidStatus
    observed_at: datetime | None = None
    effective_until: datetime | None = None
    activation_check: ActivationCheckStatus | None = None


@dataclass(frozen=True)
class PaidRead:
    revision: int
    document: EffectiveState
    provenance: dict[str, SourceProvenance]
    committed_at: datetime | None
    read_at: datetime
    products: tuple[ProductEvidence, ...]
    evidence_complete: bool
    effective_until: datetime | None


@dataclass(frozen=True)
class SnapshotRead:
    revision: int
    document: EffectiveState
    refresh_after: datetime
    expires_at: datetime


@dataclass(frozen=True)
class CommittedPaidState:
    revision: int
    document: EffectiveState
    provenance: dict[str, SourceProvenance]
    committed_at: datetime | None
    scopes: dict[str, BillingProductAccessScope]

    @property
    def effective_until(self) -> datetime | None:
        deadlines = [deadline for scope in self.scopes.values() if (deadline := effective_deadline(scope)) is not None]
        return min(deadlines) if deadlines else None

    def require_current(self, now: datetime, policy: MeteringPolicy) -> None:
        if self.effective_until is not None and self.effective_until <= now:
            raise BillingRefused("paid_access_deadline_pending", 503)
        # Refuse the whole old revision. A GET cannot silently filter its tuples
        # or repair an uncommitted provenance/start-boundary reduction.
        if any(
            not policy.permits(self.provenance.get(item.allowance_id))
            or (item.period_start is not None and datetime.fromisoformat(item.period_start) > now)
            for item in self.document.allowances
        ):
            raise BillingRefused("paid_access_state_pending", 503)


def read_committed_state(
    db: Session, user_id: UUID, tenant: str, region: str, *, consumer: BackendConsumer | None = None
) -> CommittedPaidState:
    if not queries.lock_reader(db, user_id, tenant, region):
        raise BillingRefused("paid_access_user_not_found", 404)
    row = queries.state(db, user_id, tenant, region)
    document = EffectiveState.model_validate(row.effective_state_document) if row else EffectiveState()
    # Select relevance before provenance validation or deadline/completeness checks.
    # The cabinet and writer retain the whole-user view (consumer=None).
    products = consumer.allowed_products if consumer is not None else None
    if products is not None:
        document = EffectiveState(
            grants=tuple(item for item in document.grants if item.product_id in products),
            allowances=tuple(item for item in document.allowances if item.product_id in products),
        )
    ownership = TechnicalOwnership(consumer.technical_source_id, consumer.consumer_id) if consumer is not None else None
    if ownership is not None and document.grants:
        purchases = queries.grant_purchases(db, user_id, [grant.product_id for grant in document.grants])
        for grant in document.grants:
            purchase = purchases.get(grant.product_id)
            if purchase is None:
                raise BillingRefused("paid_access_state_pending", 503)
            try:
                saved_owner = accepted(purchase).ownership
            except PurchaseRefused:
                raise BillingRefused("paid_access_state_pending", 503) from None
            if saved_owner != ownership:
                raise BillingRefused("paid_access_owner_conflict", 503)
    provenance: dict[str, SourceProvenance] = {}
    for item in queries.allowances(db, [UUID(item.allowance_id) for item in document.allowances]):
        terms = AcceptedTechnicalTerms.model_validate(item.terms_document["technical_terms"])
        # Policy scope cannot transfer an issued allowance away from its usage owner.
        if ownership is not None and terms.ownership != ownership:
            raise BillingRefused("paid_access_owner_conflict", 503)
        provenance[str(item.allowance_id)] = terms.provenance
    return CommittedPaidState(
        row.access_revision if row else 0,
        document,
        provenance,
        as_utc(row.committed_at) if row else None,
        {
            scope.product_id: scope
            for scope in queries.scopes(db, user_id)
            if products is None or scope.product_id in products
        },
    )


def read_access_snapshot(
    factory: SessionFactory, configuration: Settings, user_id: UUID, consumer: BackendConsumer
) -> SnapshotRead:
    budget = configuration.paid_access_clock_skew_seconds
    if budget is None:
        raise BillingRefused("paid_access_clock_unavailable", 503)
    with factory() as db:
        try:
            require_current_policy(db, consumer)
        except BackendPolicyConflict:
            raise BillingRefused("paid_access_policy_unavailable", 503) from None
        state = read_committed_state(db, user_id, consumer.tenant_id, consumer.region, consumer=consumer)
        # Wall time is sampled after every possibly waiting read under the
        # shared user lock. No last_seen bookkeeping or commit occurs here.
        now = as_utc(database_now(db))
        state.require_current(now, MeteringPolicy.for_environment(configuration.app_env))
        bounds = [now + timedelta(seconds=300)]
        if state.effective_until is not None:
            bounds.append(state.effective_until)
        expires = min(bounds) - timedelta(seconds=budget)
        if expires <= now:
            raise BillingRefused("paid_access_deadline_pending", 503)
        return SnapshotRead(state.revision, state.document, min(now + timedelta(seconds=60), expires), expires)


class _RetainedProof(BaseModel):
    read_started_at: datetime
    identity: IdentityProof
    commercial: CommercialProof
    financial: Financial | None
    lifecycle: Lifecycle | None
    reasons: tuple[str, ...] = ()

    def fresh_match(self, now: datetime) -> bool:
        return self.identity == IdentityProof.MATCH and as_utc(self.read_started_at) + SOURCE_TRUST > now


def _retained_proof(observation: BillingStateObservation | None) -> _RetainedProof | None:
    if observation is None or observation.evidence_schema_version not in RECONCILIATION_READ_SCHEMAS:
        return None
    try:
        return _RetainedProof.model_validate(observation.evidence_document)
    except ValidationError:
        return None


def _negative(proof: _RetainedProof | None, now: datetime) -> bool:
    return (
        proof is not None
        and proof.fresh_match(now)
        and (
            proof.commercial == CommercialProof.MISMATCH
            or proof.financial == Financial.BLOCKED
            or proof.lifecycle in (Lifecycle.INACTIVE, Lifecycle.ENDED)
        )
    )


def _activation_status(
    job: BillingWorkItem | None, purchase_id: UUID, proof: _RetainedProof | None, now: datetime
) -> ActivationCheckStatus | None:
    if job is not None:
        try:
            window = WidgetActivationWindow.from_work(job)
        except ValueError:
            window = None
        if window is not None and window.purchase_id == purchase_id:
            completion = window.completion
            if completion is None:
                if now < window.deadline_at + CLOSING_GRACE:
                    return ActivationCheckStatus.CHECKING
            elif completion.reason == WidgetActivationCompletionReason.PURCHASE_INELIGIBLE:
                return None
            elif (
                completion.reason == WidgetActivationCompletionReason.ACTIVATION_DETECTED
                and now < completion.at + HANDOFF_DISPLAY
            ):
                return ActivationCheckStatus.CHECKING
            return ActivationCheckStatus.UNCONFIRMED
    if (
        proof is not None
        and proof.fresh_match(now)
        and proof.commercial == CommercialProof.MATCH
        and proof.lifecycle == Lifecycle.INACTIVE
        and proof.financial == Financial.BLOCKED
        and SubscriptionLifecycleReason.WAITING in proof.reasons
    ):
        return ActivationCheckStatus.UNCONFIRMED
    return None


def read_paid_access(factory: SessionFactory, configuration: Settings, token: str) -> PaidRead:
    with factory() as db:
        # Identity owns last_seen bookkeeping/commit before the paid read boundary.
        user = authenticate(db, configuration, token)
        state = read_committed_state(db, user.id, user.tenant_id, user.region)
        scopes = state.scopes
        ids = queries.product_ids(db, user.id)
        visible = ids[: queries.MAX_EVIDENCE_PRODUCTS]
        sources = {
            purchase.product_id: (purchase, sub, observation, binding)
            for purchase, sub, observation, binding in queries.sources(db, user.id, visible)
        }
        granted = {grant.product_id for grant in state.document.grants}
        candidates = {
            product: (purchase.purchase_intent_id, sub)
            for product, (purchase, sub, _, binding) in sources.items()
            if product not in granted
            and purchase.state == PurchaseIntentState.LINKED
            and binding == Binding.BOUND
            and sub is not None
            and sub.commercial_access_status == Commercial.ELIGIBLE
            and sub.lifecycle_status != Lifecycle.ENDED
            and not (sub.lifecycle_status == Lifecycle.ACTIVE and sub.financial_access_status == Financial.BLOCKED)
            and product in scopes
            and scopes[product].primary_subscription_id is None
        }
        subscription_ids = {sub.subscription_id for _, sub in candidates.values()}
        selected = primary_selections(db, subscription_ids) if subscription_ids else set()
        reviews = open_review_references(db, subscription_ids) if subscription_ids else set()
        job_keys = {key(sub) for _, sub in candidates.values()}
        jobs = queries.activation_jobs(db, job_keys) if job_keys else {}
        # Sample database time after the local reads, which may themselves wait.
        # Never omit an overdue tuple while returning its old revision.
        now = as_utc(database_now(db))
        state.require_current(now, MeteringPolicy.for_environment(configuration.app_env))
        products = []
        for product in visible:
            _, sub, observation, _ = sources.get(product, (None, None, None, None))
            scope = scopes.get(product)
            proof = _retained_proof(observation)
            if product in granted:
                status = ProductPaidStatus.CONFIRMED
            elif _negative(proof, now):
                status = ProductPaidStatus.ABSENT
            else:
                status = ProductPaidStatus.UNAVAILABLE
            activation_check = None
            if candidate := candidates.get(product):
                purchase_id, pending = candidate
                if pending.subscription_id not in selected and str(pending.subscription_id) not in reviews:
                    activation_check = _activation_status(jobs.get(key(pending)), purchase_id, proof, now)
            products.append(
                ProductEvidence(
                    product,
                    status,
                    as_utc(observation.observed_at)
                    if status == ProductPaidStatus.ABSENT and observation
                    else (
                        as_utc(sub.last_authoritative_read_at)
                        if sub and sub.projection_valid_until > sub.last_authoritative_read_at
                        else None
                    ),
                    effective_deadline(scope) if scope else None,
                    activation_check,
                )
            )
        return PaidRead(
            state.revision,
            state.document,
            state.provenance,
            state.committed_at,
            now,
            tuple(products),
            len(ids) <= queries.MAX_EVIDENCE_PRODUCTS,
            state.effective_until,
        )
