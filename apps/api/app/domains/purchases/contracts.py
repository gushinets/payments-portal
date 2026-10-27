"""Transport-neutral immutable purchase evidence and preparation snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.domains.billing.contracts import BillingRefused
from app.domains.catalog.product_link import CurrentOffer, ProductLinkRequest
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
    state: int
    current_blocking: int
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
    documents: tuple[LegalSelection, ...]


class AcceptedPurchase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    schema_version: Literal["accepted-purchase:v1"] = "accepted-purchase:v1"
    meaning: PurchaseMeaning
    selection: ProductLinkRequest
    offer: CurrentOffer
    documents: tuple[LegalEvidence, ...]
    provider_origin: str
    seller_id: int


@dataclass(frozen=True)
class FinancialOperation:
    id: UUID
    kind: ExternalCreateOperationKind
    state: ExternalCreateOperationState
    key: str
    fence: UUID | None
    bound_id: str | None
    candidate_id: str | None
    deadline: datetime | None
    may_send: bool = False
    last_failure: tuple[int | None, int | None, str] | None = None
    last_failure_code: str | None = None
    agreement_create_date: date | None = None


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
