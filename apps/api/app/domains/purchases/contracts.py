"""Transport-neutral immutable purchase evidence and preparation snapshots."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domains.billing.contracts import BillingRefused
from app.domains.catalog.product_link import CurrentOffer, ProductLinkRequest
from app.domains.catalog.mapping_evidence import Digest
from app.domains.purchases.technical_terms import AcceptedTechnicalTerms
from app.domains.catalog.technical_source import LEGACY_KERNEL_OWNERSHIP, TechnicalOwnership
from app.models import ExternalCreateOperationKind, ExternalCreateOperationState, PurchaseIntentState

type FinancialRequestDocument = dict[str, str | int | bool | list[dict[str, int]]]
type FinancialFailureFacts = dict[str, str | int | None]
MAX_PURCHASE_LEGAL_DOCUMENTS = 20


@dataclass(frozen=True)
class EffectiveServiceEvidence:
    tariff_service_id: int
    quantity: str
    effective_unit_amount: str


@dataclass(frozen=True)
class PreparedSubscriptionObservation:
    subscription_id: str
    agreement_id: str
    state: int | None
    current_blocking: int | None
    accepted_fingerprint: str
    period_id: int
    period_type: int
    period_length: int
    currency: str
    effective_recurring_amount: str
    services: tuple[EffectiveServiceEvidence, ...]
    calendar: dict[str, str | None]
    paid_verified: Literal[False] = False


class PurchaseRefused(BillingRefused):
    pass


class PurchaseInventoryIncomplete(PurchaseRefused):
    """Absence of complete inventory proof permits a later read, never a send."""

    def __init__(self) -> None:
        super().__init__("purchase_inventory_incomplete", 409)


class LegalSelection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    document_version_id: UUID
    acceptance_text_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class LegalEvidence(LegalSelection):
    doc_type: str
    version: str
    content_hash: str
    title: str
    url_path: str
    acceptance_text: str


class PurchaseMeaning(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product_id: str
    revision_id: UUID
    expected_fingerprint: str
    expected_technical_terms_digest: Digest | None = None
    documents: tuple[LegalSelection, ...]


class AcceptedPurchase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal[
        "accepted-purchase:v1", "accepted-purchase:v2", "accepted-purchase:v3", "accepted-purchase:v4"
    ] = "accepted-purchase:v1"
    meaning: PurchaseMeaning
    selection: ProductLinkRequest
    offer: CurrentOffer
    documents: tuple[LegalEvidence, ...]
    provider_origin: str
    seller_id: int
    technical_terms: AcceptedTechnicalTerms | None = None

    @property
    def ownership(self) -> TechnicalOwnership:
        return self.technical_terms.ownership if self.technical_terms else LEGACY_KERNEL_OWNERSHIP

    @model_validator(mode="after")
    def verify_technical_meaning(self) -> AcceptedPurchase:
        terms = self.technical_terms
        if self.schema_version == "accepted-purchase:v1" and (terms or self.meaning.expected_technical_terms_digest):
            raise ValueError("legacy purchase has no technical evidence")
        if self.schema_version in ("accepted-purchase:v3", "accepted-purchase:v4"):
            expected = (
                "purchased-technical-terms:v3"
                if self.schema_version == "accepted-purchase:v4"
                else "purchased-technical-terms:v2"
            )
            if terms is None or terms.schema_version != expected:
                raise ValueError("configured purchase requires published technical terms")
        elif terms is not None and terms.schema_version != "purchased-technical-terms:v1":
            raise ValueError("historical purchase cannot acquire configured technical terms")
        # Existing v2 history pinned the whole-source digest. New confirmations
        # pin selected meaning; both retain the independently verified audit hash.
        digests = (
            {terms.confirmation_digest()}
            if self.schema_version in ("accepted-purchase:v3", "accepted-purchase:v4")
            else {terms.digest, terms.confirmation_digest()}
            if terms
            else {None}
        )
        if self.meaning.expected_technical_terms_digest not in digests:
            raise ValueError("technical acceptance mismatch")
        if terms and (
            terms.revision_id != self.meaning.revision_id
            or terms.selection != self.selection
            or terms.offer.product_id != self.meaning.product_id
            or terms.commercial_fingerprint != self.offer.fingerprint
        ):
            raise ValueError("technical binding mismatch")
        return self


@dataclass(frozen=True)
class FinancialOperation:
    id: UUID
    kind: ExternalCreateOperationKind
    state: ExternalCreateOperationState
    key: str
    fence: UUID | None
    bound_id: str | None
    candidate_id: str | None
    # Active send's recovery window; first-send history remains on the DB operation.
    deadline: datetime | None
    may_send: bool = False
    last_failure: tuple[int | None, int | None, str] | None = None
    last_failure_code: str | None = None
    agreement_create_date: date | None = None
    agreement_closed: bool = False

    def admission_snapshot(self) -> FinancialOperation:
        """Keep every admission field except mutable failure observations."""
        return replace(self, last_failure=None, last_failure_code=None)


@dataclass(frozen=True)
class Purchase:
    id: UUID
    user_id: UUID
    customer_id: UUID
    account_id: str
    state: PurchaseIntentState
    accepted: AcceptedPurchase
    created_at: datetime
    held: bool
    operations: tuple[FinancialOperation, ...]
    reason: str | None = None
