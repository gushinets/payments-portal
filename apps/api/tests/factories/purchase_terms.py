"""Typed test metering inputs; quantities remain explicitly simulated."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.domains.catalog.contracts import CapabilityManifest, CapabilityMetric, CapabilityProduct, SourceProvenance
from app.domains.purchases.contracts import LegalEvidence, LegalSelection, PurchaseMeaning
from app.domains.purchases.technical_terms import AcceptedTechnicalTerms, TestTermsSource

SOURCE_PATH = Path(__file__).resolve().parents[4] / "config/development/paid-access-test-terms.json"


def test_terms_source() -> TestTermsSource:
    return TestTermsSource.model_validate_json(SOURCE_PATH.read_text(encoding="utf-8"))


def technical_manifest() -> CapabilityManifest:
    return CapabilityManifest(
        1,
        "anytoolai",
        "ru",
        "sha256:a39bac9f210a6ac67e97e117f8481a5954dc3f36bdaab2fd54c7522b27d6ec29",
        datetime(2026, 10, 15, tzinfo=UTC),
        (CapabilityProduct("proposal_ai", True), CapabilityProduct("brief_decoder", True)),
        (
            CapabilityMetric("proposal_ai.test_generations", "proposal_ai", "generation", True),
            CapabilityMetric("brief_decoder.test_analyses", "brief_decoder", "analysis", True),
        ),
        SourceProvenance.SIMULATED,
    )


def reviewed_meaning(
    product_id: str,
    revision_id: UUID,
    fingerprint: str,
    documents: tuple[LegalEvidence, ...],
    terms: AcceptedTechnicalTerms | None,
) -> PurchaseMeaning:
    return PurchaseMeaning(
        product_id=product_id,
        revision_id=revision_id,
        expected_fingerprint=fingerprint,
        expected_technical_terms_digest=terms.digest if terms else None,
        documents=tuple(
            LegalSelection(document_version_id=d.document_version_id, acceptance_text_hash=d.acceptance_text_hash)
            for d in documents
        ),
    )
