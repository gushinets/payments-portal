"""Committed paid state for the cabinet; no source I/O or billing writes."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import authenticate
from app.domains.billing.paid_contracts import EffectiveState
from app.domains.billing.paid_deadlines import effective_deadline
from app.domains.billing.paid_policy import MeteringPolicy
from app.domains.billing.reconciliation_contracts import RECONCILIATION_SCHEMA, IdentityProof, CommercialProof
from app.domains.billing.reconciliation import SOURCE_TRUST
from app.domains.catalog.publication import SessionFactory
from app.domains.catalog.contracts import SourceProvenance
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.technical_terms import AcceptedTechnicalTerms
from app.infrastructure.queries import paid_read as queries
from app.infrastructure.queries.billing_reconciliation import database_now
from app.models import (
    BillingStateObservation,
    BillingProductAccessScope,
    ExternalSubscriptionFinancialAccessStatus as Financial,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)


class ProductPaidStatus(StrEnum):
    CONFIRMED = "confirmed"
    ABSENT = "no_paid_access"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ProductEvidence:
    product_id: str
    status: ProductPaidStatus
    observed_at: datetime | None = None
    effective_until: datetime | None = None


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


def read_committed_state(db: Session, user_id: UUID, tenant: str, region: str) -> CommittedPaidState:
    if not queries.lock_reader(db, user_id, tenant, region):
        raise BillingRefused("paid_access_user_not_found", 404)
    row = queries.state(db, user_id, tenant, region)
    document = EffectiveState.model_validate(row.effective_state_document) if row else EffectiveState()
    provenance = {
        str(item.allowance_id): AcceptedTechnicalTerms.model_validate(item.terms_document["technical_terms"]).provenance
        for item in queries.allowances(db, [UUID(item.allowance_id) for item in document.allowances])
    }
    return CommittedPaidState(
        row.access_revision if row else 0,
        document,
        provenance,
        as_utc(row.committed_at) if row else None,
        {scope.product_id: scope for scope in queries.scopes(db, user_id)},
    )


def read_access_snapshot(factory: SessionFactory, configuration: Settings, user_id: UUID) -> SnapshotRead:
    budget = configuration.paid_access_clock_skew_seconds
    if budget is None:
        raise BillingRefused("paid_access_clock_unavailable", 503)
    with factory() as db:
        state = read_committed_state(db, user_id, configuration.instance_tenant_id, configuration.instance_region)
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


def _negative(observation: BillingStateObservation | None, now: datetime) -> bool:
    if observation is None or observation.evidence_schema_version != RECONCILIATION_SCHEMA:
        return False
    proof = observation.evidence_document
    return (
        as_utc(datetime.fromisoformat(proof["read_started_at"])) + SOURCE_TRUST > now
        and proof["identity"] == IdentityProof.MATCH
        and (
            proof["commercial"] == CommercialProof.MISMATCH
            or proof["financial"] == Financial.BLOCKED
            or proof["lifecycle"] in (Lifecycle.INACTIVE, Lifecycle.ENDED)
        )
    )


def read_paid_access(factory: SessionFactory, configuration: Settings, token: str) -> PaidRead:
    with factory() as db:
        # Identity owns last_seen bookkeeping/commit before the paid read boundary.
        user = authenticate(db, configuration, token)
        state = read_committed_state(db, user.id, user.tenant_id, user.region)
        scopes = state.scopes
        ids = queries.product_ids(db, user.id)
        visible = ids[: queries.MAX_EVIDENCE_PRODUCTS]
        sources = {
            purchase.product_id: (sub, observation)
            for purchase, sub, observation in queries.sources(db, user.id, visible)
        }
        # Sample database time after the local reads, which may themselves wait.
        # Never omit an overdue tuple while returning its old revision.
        now = as_utc(database_now(db))
        state.require_current(now, MeteringPolicy.for_environment(configuration.app_env))
        granted = {grant.product_id for grant in state.document.grants}
        products = []
        for product in visible:
            sub, observation = sources.get(product, (None, None))
            scope = scopes.get(product)
            if product in granted:
                status = ProductPaidStatus.CONFIRMED
            elif _negative(observation, now):
                status = ProductPaidStatus.ABSENT
            else:
                status = ProductPaidStatus.UNAVAILABLE
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
