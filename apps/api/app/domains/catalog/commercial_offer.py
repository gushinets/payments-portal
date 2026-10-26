"""Request-local commercial evidence, not a catalog, approval or paid grant."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum

from app.core.errors import AppError


class OfferRefusalKind(StrEnum):
    INCOMPLETE = "INCOMPLETE"
    NOT_SELLABLE = "NOT_SELLABLE"


class SelectedOfferRefused(AppError):
    def __init__(self, kind: OfferRefusalKind, reason: str) -> None:
        super().__init__("selected_offer_" + reason)
        self.kind = kind
        self.reason = reason


class SelectedOfferSourceFailed(SelectedOfferRefused):
    """A selected read failed or drifted, rather than describing an invalid offer."""

    def __init__(self, reason: str) -> None:
        super().__init__(OfferRefusalKind.INCOMPLETE, reason)


class CommercialEvidenceBasis(StrEnum):
    DOCUMENTED = "DOCUMENTED"
    ACCOUNT_EVIDENCE = "ACCOUNT_EVIDENCE"
    SIMULATED = "SIMULATED"


class CommercialEvidenceMode(StrEnum):
    # CONFIGURED_SOURCE is provenance, never production approval/conformance.
    CONFIGURED_SOURCE = "CONFIGURED_SOURCE"
    SIMULATED = "SIMULATED"


def canonical_decimal(value: Decimal) -> str:
    """No context-dependent normalize(), exponent spelling or negative zero."""
    if not value.is_finite():
        raise ValueError("finite decimal required")
    if not value:
        return "0"
    rendered = format(value, "f")
    return rendered.rstrip("0").rstrip(".") if "." in rendered else rendered


def _canonical_scalar(value: object) -> str:
    if isinstance(value, Decimal):
        return canonical_decimal(value)
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError("unsupported commercial evidence value")


def canonical_document(value: object) -> str:
    return json.dumps(value, default=_canonical_scalar, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def commercial_digest(document: str) -> str:
    return "sha256:" + hashlib.sha256(document.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CommercialScope:
    tenant_id: str
    region: str
    external_billing_account_id: str


@dataclass(frozen=True)
class CommercialSourceReferences:
    offer: str
    component: str
    period: str
    period_membership: str
    effective_price: str


@dataclass(frozen=True)
class CommercialMoney:
    currency: str
    decimal_places: int
    recurring_unit_amount: Decimal
    connection_unit_amount: Decimal
    recurring_amount: Decimal
    connection_amount: Decimal


@dataclass(frozen=True)
class CommercialPeriod:
    unit: str
    length: int
    anchor: str
    # Calendar applicability only. These are NOT subscription/UTC cycle bounds.
    price_effective_from: date
    price_effective_until: date | None


@dataclass(frozen=True)
class CommercialQuantity:
    unit: str
    selected: Decimal
    minimum: int
    maximum: int


@dataclass(frozen=True)
class CommercialPolicy:
    tax_treatment: str
    discounts: str
    proration: str
    demo_days: int
    prepaid: bool
    insufficient_funds_block: bool
    block_to_close_days: int
    full_funding_required: bool
    customer_service_management: bool
    customer_quantity_management: bool
    connection_charge_basis: str
    renewal_terms: str
    cancellation_terms: str
    historical_applicability: str


@dataclass(frozen=True)
class MaterialCommercialTerms:
    money: CommercialMoney
    period: CommercialPeriod
    quantity: CommercialQuantity
    policy: CommercialPolicy

    def canonical_json(self) -> str:
        return canonical_document(asdict(self))


@dataclass(frozen=True)
class CommercialFieldSource:
    field: str
    reference: str
    revision: str
    basis: CommercialEvidenceBasis


@dataclass(frozen=True)
class CommercialObservation:
    reference: str
    observed_at: datetime


@dataclass(frozen=True)
class SelectedCommercialOffer:
    scope: CommercialScope
    references: CommercialSourceReferences
    terms: MaterialCommercialTerms
    evidence_mode: CommercialEvidenceMode
    digest_scope: str
    selected_evidence_digest: str
    # Canonical selected dependencies permit independent digest reproduction.
    selected_evidence_json: str
    field_sources: tuple[CommercialFieldSource, ...]
    observations: tuple[CommercialObservation, ...]
