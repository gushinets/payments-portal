"""Committed paid state for the cabinet; no source I/O or billing writes."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.customers import authenticate
from app.domains.billing.paid_contracts import EffectiveState
from app.domains.billing.paid_deadlines import effective_deadline
from app.domains.billing.reconciliation_contracts import RECONCILIATION_SCHEMA, IdentityProof, CommercialProof
from app.domains.billing.reconciliation import SOURCE_TRUST
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.technical_terms import AcceptedTechnicalTerms
from app.infrastructure.queries import paid_read as queries
from app.infrastructure.queries.billing_reconciliation import database_now
from app.models import (
    BillingStateObservation,
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
    provenance: dict[str, str]
    committed_at: datetime | None
    read_at: datetime
    products: tuple[ProductEvidence, ...]
    evidence_complete: bool
    effective_until: datetime | None


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
        queries.lock_reader(db, user.id, configuration.instance_tenant_id, configuration.instance_region)
        row = queries.state(db, user.id, user.tenant_id, user.region)
        document = EffectiveState.model_validate(row.effective_state_document) if row else EffectiveState()
        scopes = {scope.product_id: scope for scope in queries.scopes(db, user.id)}
        deadlines = [deadline for scope in scopes.values() if (deadline := effective_deadline(scope)) is not None]
        ids = queries.product_ids(db, user.id)
        visible = ids[: queries.MAX_EVIDENCE_PRODUCTS]
        sources = {
            purchase.product_id: (sub, observation)
            for purchase, sub, observation in queries.sources(db, user.id, visible)
        }
        provenance = {
            str(item.allowance_id): AcceptedTechnicalTerms.model_validate(
                item.terms_document["technical_terms"]
            ).provenance
            for item in queries.allowances(db, [UUID(item.allowance_id) for item in document.allowances])
        }
        # Sample database time after the local reads, which may themselves wait.
        # Never omit an overdue tuple while returning its old revision.
        now = as_utc(database_now(db))
        if deadlines and min(deadlines) <= now:
            raise BillingRefused("paid_access_deadline_pending", 503)
        granted = {grant.product_id for grant in document.grants}
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
            row.access_revision if row else 0,
            document,
            provenance,
            as_utc(row.committed_at) if row else None,
            now,
            tuple(products),
            len(ids) <= queries.MAX_EVIDENCE_PRODUCTS,
            min(deadlines) if deadlines else None,
        )
