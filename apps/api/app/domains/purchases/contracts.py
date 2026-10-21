"""Immutable purchase meaning and private accepted evidence, independent of HTTP."""

from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.core.errors import AppError
from app.domains.catalog.commercial_offer import canonical_document
from app.domains.catalog.mapping_evidence import MappingDocument


class PurchaseRefused(AppError):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.status = status


class PurchaseInput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class DocumentSelection(PurchaseInput):
    document_version_id: UUID
    acceptance_text_hash: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class PurchaseRequest(PurchaseInput):
    product_id: Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]
    revision_id: UUID
    expected_fingerprint: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    commercial_confirmation: Annotated[bool, Field(strict=True)]
    recurring_confirmation: Annotated[bool, Field(strict=True)]
    documents: Annotated[tuple[DocumentSelection, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def unique_documents(self) -> PurchaseRequest:
        if len({item.document_version_id for item in self.documents}) != len(self.documents):
            raise ValueError("duplicate document selection")
        return self

    def canonical_meaning(self) -> str:
        value = self.model_dump(mode="json")
        value["documents"] = sorted(value["documents"], key=lambda item: item["document_version_id"])
        return canonical_document(value)


class SellerEvidence(PurchaseInput):
    # Explicit local fixture, never an inferred live seller or customer profile.
    evidence_mode: Literal["SIMULATED"]
    organization_id: Annotated[int, Field(strict=True, gt=0)]
    reference: Annotated[str, Field(pattern=r"^SIMULATED:.+")]
    revision: Annotated[str, Field(min_length=1)]


class PinnedDocument(PurchaseInput):
    document_version_id: UUID
    legal_entity_id: UUID
    doc_type: str
    version: str
    title: str
    url_path: str
    content_hash: str
    acceptance_text: str
    acceptance_text_hash: str


class PurchaseReview(PurchaseInput):
    revision_id: UUID
    revision_number: int
    mapping: MappingDocument
    fingerprint: str
    seller: SellerEvidence
    seller_name: str
    initial_amount: str
    recurring_required: bool
    documents: tuple[PinnedDocument, ...]


class PurchaseSourceEvidence(PurchaseInput):
    mapping: MappingDocument
    effective_on: date
    timezone: str


class PurchaseAdmissionProof(PurchaseSourceEvidence):
    deadline: float


class AcceptedPurchase(PurchaseInput):
    schema_version: Literal["v1"] = "v1"
    tenant_id: str
    region: str
    external_billing_account_id: str
    user_id: UUID
    request: PurchaseRequest
    review: PurchaseReview
    admission: PurchaseSourceEvidence
    accepted_at: AwareDatetime


class PersistedPurchase(PurchaseInput):
    purchase_intent_id: UUID
    state: str
    accepted: AcceptedPurchase
    state_updated_at: datetime
