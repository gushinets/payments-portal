"""Versioned approved material and immutable evidence; no source I/O or approval UI."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from urllib.parse import quote

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_serializer,
    field_validator,
    model_validator,
)

from app.core.errors import AppError
from app.domains.catalog.admission import require_selected_capability
from app.domains.catalog.commercial_offer import (
    CommercialEvidenceBasis,
    CommercialEvidenceMode,
    CommercialFieldSource,
    CommercialObservation,
    CommercialScope,
    CommercialSourceReferences,
    MaterialCommercialTerms,
    SelectedCommercialOffer,
    canonical_document,
    commercial_digest,
)
from app.domains.catalog.contracts import CapabilityManifest, SourceProvenance


MAPPING_SCHEMA = "approved-offer-v1"
Nonempty = Annotated[str, Field(min_length=1, max_length=1024, pattern=r"\S")]
Digest = Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
PositiveInteger = Annotated[int, Field(strict=True, gt=0)]
_MATERIAL_TERMS_ADAPTER = TypeAdapter(MaterialCommercialTerms)


class MappingRefused(AppError):
    """Safe publication/query refusal, distinct from source and database errors."""


class MappingEvidenceMode(StrEnum):
    SIMULATED = "SIMULATED"
    GENUINE = "GENUINE"


class PublicationState(StrEnum):
    SIMULATED = "SIMULATED"
    PUBLISHED_APPROVED_UNVERIFIED_NOW = "PUBLISHED_APPROVED_UNVERIFIED_NOW"


class ApprovalBasis(StrEnum):
    SIMULATED = "SIMULATED"
    VERIFIED = "VERIFIED"


class ImmutableInput(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True, hide_input_in_errors=True)


class TechnicalBinding(ImmutableInput):
    product_id: Nonempty
    metric_key: Nonempty
    unit: Nonempty
    allowance: PositiveInteger
    metric_basis: ApprovalBasis


class ApprovalReference(ImmutableInput):
    reference: Nonempty
    revision: Nonempty
    content_hash: Digest
    basis: ApprovalBasis

    @model_validator(mode="after")
    def visibly_simulated(self) -> ApprovalReference:
        if self.basis == ApprovalBasis.SIMULATED and not self.reference.startswith("SIMULATED:"):
            raise ValueError("simulated approval references must be named SIMULATED:")
        return self


class ApprovalRevisions(ImmutableInput):
    technical: ApprovalReference
    commercial: ApprovalReference
    legal: ApprovalReference

    def is_simulated(self) -> bool:
        return any(item.basis == ApprovalBasis.SIMULATED for item in (self.technical, self.commercial, self.legal))


class MappingMaterial(ImmutableInput):
    scope: CommercialScope
    references: CommercialSourceReferences
    terms: MaterialCommercialTerms
    technical: TechnicalBinding
    digest_scope: Literal["selected_offer"]
    selected_evidence_digest: Digest
    component_classification: Literal["CAPABILITY_BEARING"]
    external_usage_reporting: Literal["none"]

    @property
    def billing_offer_id(self) -> str:
        """Step 5 identity; original Step 4 references retain their source meaning.

        Escape each opaque reference before joining so embedded separators cannot
        alias another tariff/component/period selection. This derived storage key
        is not a new field in approved material or its immutable fingerprints.
        """
        selected = (self.references.offer, self.references.component, self.references.period)
        return "selected-offer:v1:" + ":".join(quote(reference, safe="") for reference in selected)

    @field_validator("terms", mode="before")
    @classmethod
    def exact_money_input(cls, value: object) -> object:
        # JSON numbers must never pass through a binary float en route to Decimal.
        # Internal consumers already own the normalized frozen dataclass.
        if isinstance(value, dict):
            money, quantity = value.get("money"), value.get("quantity")
            if not isinstance(money, dict) or not isinstance(quantity, dict):
                raise ValueError("complete exact terms required")
            amounts = [
                money.get(key)
                for key in ("recurring_unit_amount", "connection_unit_amount", "recurring_amount", "connection_amount")
            ] + [quantity.get("selected")]
            if any(
                not isinstance(item, str) or not re.fullmatch(r"(?:0|[1-9]\d*)(?:\.\d+)?", item) for item in amounts
            ):
                raise ValueError("money and commercial quantity require exact decimal strings")
            # A before-validator materializes JSON objects as Python dicts.
            # Decode through the existing dataclass schema in strict JSON mode
            # so decimal/date strings become exact Decimal/date instances before
            # the enclosing strict field validates them. Keep all other scalar
            # types strict and reject unknown fields throughout the terms tree.
            return _MATERIAL_TERMS_ADAPTER.validate_json(json.dumps(value), strict=True, extra="forbid")
        return value

    @field_serializer("terms", when_used="json")
    def serialize_exact_terms(self, value: MaterialCommercialTerms) -> object:
        # Decimal's own spelling can contain an exponent; persisted/CLI money
        # always uses Step 4's exact canonical decimal-string representation.
        return json.loads(value.canonical_json())

    def canonical_json(self) -> str:
        # Use Step 4 canonical decimals/dates, including when parsed from storage.
        return canonical_document(
            {
                "scope": asdict(self.scope),
                "references": asdict(self.references),
                "terms": asdict(self.terms),
                "technical": self.technical.model_dump(mode="json"),
                "digest_scope": self.digest_scope,
                "selected_evidence_digest": self.selected_evidence_digest,
                "component_classification": self.component_classification,
                "external_usage_reporting": self.external_usage_reporting,
            }
        )


class ApprovedMapping(ImmutableInput):
    """Separately controlled versioned input, never a caller-supplied approved flag.

    References pin independently approved documents; their hashes are content
    references, not signatures or a claim of real provider/Kernel conformance.
    OS/configuration/DB-secret control remains the trusted boundary.
    """

    schema_version: Literal[1]
    material: MappingMaterial
    approved_material_hash: Digest
    revisions: ApprovalRevisions

    @model_validator(mode="after")
    def exact_approval(self) -> ApprovedMapping:
        if self.approved_material_hash != commercial_digest(self.material.canonical_json()):
            raise ValueError("approval material hash mismatch")
        return self


def publication_fingerprint(material: MappingMaterial, revisions: ApprovalRevisions, mode: MappingEvidenceMode) -> str:
    return commercial_digest(
        canonical_document(
            {
                "schema": MAPPING_SCHEMA,
                "material": json.loads(material.canonical_json()),
                "approvals": revisions.model_dump(mode="json"),
                "evidence_mode": mode,
            }
        )
    )


class MappingDocument(ImmutableInput):
    schema_version: Literal["approved-offer-v1"]
    material: MappingMaterial
    approvals: ApprovalRevisions
    approved_material_hash: Digest
    evidence_mode: MappingEvidenceMode
    publication_state: PublicationState
    material_fingerprint: Digest
    manifest_version: Digest
    manifest_generated_at: AwareDatetime
    kernel_provenance: SourceProvenance
    lbx_evidence_mode: CommercialEvidenceMode
    selected_evidence_json: str
    field_sources: tuple[CommercialFieldSource, ...]
    observations: tuple[CommercialObservation, ...]
    evaluated_at: AwareDatetime
    published_at: AwareDatetime
    publisher_principal: Annotated[str, Field(pattern=r"^os-euid:[0-9]+$")]
    reason: Annotated[str, Field(min_length=1, max_length=1024, pattern=r"\S")]

    @model_validator(mode="after")
    def consistent_evidence(self) -> MappingDocument:
        material = self.material
        if self.approved_material_hash != commercial_digest(material.canonical_json()):
            raise ValueError("approved material pin mismatch")
        if (
            material.digest_scope != "selected_offer"
            or commercial_digest(self.selected_evidence_json) != material.selected_evidence_digest
        ):
            raise ValueError("selected evidence digest mismatch")
        try:
            selected = json.loads(self.selected_evidence_json)
        except (ValueError, RecursionError):
            raise ValueError("invalid selected evidence document") from None
        if (
            not isinstance(selected, dict)
            or type(selected.get("schema_version")) is not int
            or selected["schema_version"] != 1
            or selected.get("digest_scope") != "selected_offer"
            or selected.get("scope") != asdict(material.scope)
            or selected.get("references") != asdict(material.references)
            or canonical_document(selected.get("terms")) != material.terms.canonical_json()
            or selected.get("evidence_mode") != self.lbx_evidence_mode
            or canonical_document(selected.get("field_sources"))
            != canonical_document([asdict(item) for item in self.field_sources])
            or not isinstance(selected.get("dependencies"), dict)
        ):
            raise ValueError("selected evidence does not prove mapping material")
        if self.material_fingerprint != publication_fingerprint(material, self.approvals, self.evidence_mode):
            raise ValueError("material fingerprint mismatch")
        simulated = (
            self.kernel_provenance == SourceProvenance.SIMULATED
            or self.lbx_evidence_mode == CommercialEvidenceMode.SIMULATED
            or material.technical.metric_basis == ApprovalBasis.SIMULATED
            or self.approvals.is_simulated()
            or any(item.basis == CommercialEvidenceBasis.SIMULATED for item in self.field_sources)
        )
        if simulated and self.evidence_mode != MappingEvidenceMode.SIMULATED:
            raise ValueError("simulated evidence cannot be promoted")
        expected_state = (
            PublicationState.SIMULATED
            if self.evidence_mode == MappingEvidenceMode.SIMULATED
            else PublicationState.PUBLISHED_APPROVED_UNVERIFIED_NOW
        )
        if self.publication_state != expected_state:
            raise ValueError("invalid publication semantics")
        if not self.observations or any(item.observed_at.utcoffset() is None for item in self.observations):
            raise ValueError("complete aware observations required")
        if not self.field_sources or self.published_at < self.evaluated_at:
            raise ValueError("incomplete publication evidence")
        return self


def evaluate_mapping(
    *,
    manifest: CapabilityManifest,
    offer: SelectedCommercialOffer,
    technical: TechnicalBinding,
    approval: ApprovedMapping,
    scope: CommercialScope,
    principal: str,
    reason: str,
    evaluated_at: datetime,
    allow_simulated: bool,
) -> MappingDocument:
    """One evaluator for dry-run/publish; no amount or allowance inference."""
    if offer.scope != scope or (manifest.tenant_id, manifest.region) != (scope.tenant_id, scope.region):
        raise MappingRefused("mapping_scope_mismatch")
    require_selected_capability(
        manifest, product_id=technical.product_id, metric_units={technical.metric_key: technical.unit}
    )
    material = MappingMaterial(
        scope=scope,
        references=offer.references,
        terms=offer.terms,
        technical=technical,
        digest_scope=offer.digest_scope,
        selected_evidence_digest=offer.selected_evidence_digest,
        component_classification="CAPABILITY_BEARING",
        external_usage_reporting="none",
    )
    if material.canonical_json() != approval.material.canonical_json():
        raise MappingRefused("mapping_approved_material_mismatch")
    # SourceProvenance currently has only SIMULATED. A URL or approval file
    # cannot establish G1-G4; genuine producer composition is a future handoff.
    mode = (
        MappingEvidenceMode.SIMULATED
        if (
            manifest.provenance == SourceProvenance.SIMULATED
            or offer.evidence_mode == CommercialEvidenceMode.SIMULATED
            or technical.metric_basis == ApprovalBasis.SIMULATED
            or approval.revisions.is_simulated()
            or any(item.basis == CommercialEvidenceBasis.SIMULATED for item in offer.field_sources)
        )
        else MappingEvidenceMode.GENUINE
    )
    if mode == MappingEvidenceMode.SIMULATED and not allow_simulated:
        raise MappingRefused("mapping_simulation_forbidden")
    return MappingDocument(
        schema_version=MAPPING_SCHEMA,
        material=material,
        approvals=approval.revisions,
        approved_material_hash=approval.approved_material_hash,
        evidence_mode=mode,
        publication_state=(
            PublicationState.SIMULATED
            if mode == MappingEvidenceMode.SIMULATED
            else PublicationState.PUBLISHED_APPROVED_UNVERIFIED_NOW
        ),
        material_fingerprint=publication_fingerprint(material, approval.revisions, mode),
        manifest_version=manifest.manifest_version,
        manifest_generated_at=manifest.generated_at,
        kernel_provenance=manifest.provenance,
        lbx_evidence_mode=offer.evidence_mode,
        selected_evidence_json=offer.selected_evidence_json,
        field_sources=offer.field_sources,
        observations=offer.observations,
        evaluated_at=evaluated_at,
        published_at=evaluated_at,
        publisher_principal=principal,
        reason=reason,
    )


def require_replacement_approval(previous: MappingDocument, candidate: MappingDocument) -> None:
    """Changed exact meaning cannot be repackaged under the old approval pin."""
    for old, new in zip(
        (previous.approvals.technical, previous.approvals.commercial, previous.approvals.legal),
        (candidate.approvals.technical, candidate.approvals.commercial, candidate.approvals.legal),
        strict=True,
    ):
        if (old.reference, old.revision) == (new.reference, new.revision) and old != new:
            raise MappingRefused("mapping_approval_reference_rewritten")
    old, new = previous.material, candidate.material
    if old.technical != new.technical and previous.approvals.technical == candidate.approvals.technical:
        raise MappingRefused("mapping_technical_reapproval_required")
    commercial_changed = (
        old.scope != new.scope
        or old.references != new.references
        or old.terms != new.terms
        or old.selected_evidence_digest != new.selected_evidence_digest
    )
    if commercial_changed and previous.approvals.commercial == candidate.approvals.commercial:
        raise MappingRefused("mapping_commercial_reapproval_required")
    # Normalized terms pin price, billing period, payment obligations and
    # renewal/cancellation rules. Technical bindings and source evidence alone
    # do not change those terms or require a new legal approval version.
    if old.terms != new.terms and previous.approvals.legal == candidate.approvals.legal:
        raise MappingRefused("mapping_legal_reapproval_required")
