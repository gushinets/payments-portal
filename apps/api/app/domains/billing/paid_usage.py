"""Select immutable purchased usage identities, independently of remote readback."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from pydantic import ValidationError

from app.core.settings import Settings
from app.domains.billing.customers import authenticate
from app.domains.billing.paid_policy import MeteringPolicy
from app.domains.billing.paid_read import read_committed_state
from app.domains.billing.reconciliation_contracts import RECONCILIATION_SCHEMA, CommercialProof, IdentityProof
from app.domains.catalog.contracts import SourceProvenance
from app.domains.catalog.publication import SessionFactory
from app.domains.catalog.technical_source import TechnicalOwnership
from app.domains.identity.services.auth import as_utc
from app.domains.purchases.technical_terms import AcceptedTechnicalTerms
from app.infrastructure.queries.billing_reconciliation import database_now
from app.infrastructure.queries import paid_usage as queries
from app.models import PurchasedAllowance


class UsageClassification(StrEnum):
    CURRENT = "current"
    HISTORICAL = "historical"


@dataclass(frozen=True)
class UsageAllowance:
    allowance_id: UUID
    product_id: str
    metric_key: str
    unit: str
    quantity: int
    ownership: TechnicalOwnership
    classification: UsageClassification


@dataclass(frozen=True)
class UsageSelection:
    user_id: UUID
    revision: int
    items: tuple[UsageAllowance, ...]


def _compatible_terms(row: PurchasedAllowance) -> AcceptedTechnicalTerms | None:
    # Legacy and simulated rows retain their original storage/meaning. They
    # cannot supply missing terms, an invented tuple or a backend request.
    if row.unit is None or row.terms_document is None:
        return None
    try:
        terms = AcceptedTechnicalTerms.model_validate(row.terms_document["technical_terms"])
    except (ValidationError, KeyError, TypeError):
        return None
    offer = terms.offer
    if terms.provenance != SourceProvenance.CONFIGURED_SOURCE or (
        offer.product_id, offer.metric_key, offer.unit, offer.quantity
    ) != (row.product_id, row.metric_key, row.unit, row.quantity):
        return None
    return terms


def select_paid_usage(factory: SessionFactory, configuration: Settings, token: str) -> UsageSelection:
    with factory() as db:
        user = authenticate(db, configuration, token)
        state = read_committed_state(db, user.id, user.tenant_id, user.region)
        state.require_current(as_utc(database_now(db)), MeteringPolicy.for_environment(configuration.app_env))
        current = {item.allowance_id for item in state.document.allowances}
        current_products = {item.product_id for item in state.document.allowances}
        selected: list[UsageAllowance] = []
        historical_products: set[str] = set()
        for row in queries.allowances(db, user.id):
            classification = UsageClassification.CURRENT if str(row.allowance_id) in current else UsageClassification.HISTORICAL
            if classification == UsageClassification.HISTORICAL and (
                row.product_id in current_products or row.product_id in historical_products
            ):
                continue
            terms = _compatible_terms(row)
            if terms is None:
                continue
            # Only timestamp allowances can be issued before activation. Reuse
            # retained authoritative cycle evidence, never the current clock.
            if classification == UsageClassification.HISTORICAL and row.period_start is not None:
                if not queries.activated(
                    db, row, schema=RECONCILIATION_SCHEMA, selection_schema="primary-selection:v1",
                    identity=IdentityProof.MATCH, commercial=CommercialProof.MATCH,
                ):
                    continue
            selected.append(UsageAllowance(
                row.allowance_id, row.product_id, row.metric_key, row.unit,
                row.quantity, terms.ownership, classification,
            ))
            if classification == UsageClassification.HISTORICAL:
                historical_products.add(row.product_id)
        return UsageSelection(user.id, state.revision, tuple(selected))
