"""DB-only review and exact purchase-bound legal selections."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from fractions import Fraction

from sqlalchemy.orm import Session

from app.domains.catalog.commercial_offer import CommercialScope, canonical_document, commercial_digest
from app.domains.catalog.preview import get_product_preview
from app.domains.legal.acceptance_text import (
    REGISTRATION_DOCUMENT_TYPES,
    build_acceptance_text,
    expected_acceptance_text_hash,
)
from app.domains.legal.service import get_active_required_documents
from app.domains.purchases.contracts import (
    PinnedDocument,
    PurchaseRefused,
    PurchaseRequest,
    PurchaseReview,
    SellerEvidence,
)
from app.models import LegalEntity, LegalEntityStatus


def purchase_review(
    db: Session,
    *,
    scope: CommercialScope,
    product_id: str,
    allow_simulated: bool,
    seller: SellerEvidence,
    recurring_required: bool,
    now: datetime,
) -> PurchaseReview:
    product = get_product_preview(db, scope=scope, allow_simulated=allow_simulated, product_id=product_id)
    if len(product.offers) != 1:
        raise PurchaseRefused("purchase_offer_ambiguous", 503)
    stored = product.offers[0]
    documents = get_active_required_documents(db, tenant_id=scope.tenant_id, region=scope.region, now=now)
    documents = [doc for doc in documents if recurring_required or doc.doc_type != "recurring_consent"]
    required = set(REGISTRATION_DOCUMENT_TYPES) | ({"recurring_consent"} if recurring_required else set())
    if not required.issubset({doc.doc_type for doc in documents}):
        raise PurchaseRefused("purchase_legal_unavailable", 503)
    sellers = {doc.legal_entity_id for doc in documents}
    if len(sellers) != 1:
        raise PurchaseRefused("purchase_seller_unavailable", 503)
    entity = db.get(LegalEntity, next(iter(sellers)))
    if entity is None or (entity.tenant_id, entity.region, entity.status) != (
        scope.tenant_id,
        scope.region,
        LegalEntityStatus.ACTIVE,
    ):
        raise PurchaseRefused("purchase_seller_unavailable", 503)
    pinned = tuple(
        PinnedDocument(
            document_version_id=doc.id,
            legal_entity_id=doc.legal_entity_id,
            doc_type=doc.doc_type,
            version=doc.version,
            title=doc.title,
            url_path=doc.url_path,
            content_hash=doc.content_hash,
            acceptance_text=build_acceptance_text(doc),
            acceptance_text_hash=expected_acceptance_text_hash(doc),
        )
        for doc in sorted(documents, key=lambda item: str(item.id))
    )
    # Public meaning includes seller and legal pins as well as commercial terms.
    fingerprint = commercial_digest(
        canonical_document(
            {
                "schema": "purchase-review-v1",
                "revision_id": str(stored.mapping_revision_id),
                "material_fingerprint": stored.document.material_fingerprint,
                "seller": seller.model_dump(mode="json"),
                "seller_name": entity.name,
                "recurring_required": recurring_required,
                "documents": [doc.model_dump(mode="json") for doc in pinned],
            }
        )
    )
    return PurchaseReview(
        revision_id=stored.mapping_revision_id,
        revision_number=stored.revision_number,
        mapping=stored.document,
        fingerprint=fingerprint,
        seller=seller,
        seller_name=entity.name,
        initial_amount=initial_amount(
            stored.document.material.terms.money.recurring_amount,
            stored.document.material.terms.money.connection_amount,
            stored.document.material.terms.money.decimal_places,
        ),
        recurring_required=recurring_required,
        documents=pinned,
    )


def initial_amount(recurring: Decimal, connection: Decimal, scale: int) -> str:
    """Add the two already-proven amounts without a Decimal context or float."""
    units = (Fraction(recurring) + Fraction(connection)) * 10**scale
    if units.denominator != 1 or units < 0:
        raise PurchaseRefused("purchase_money_invalid", 503)
    whole, fraction = divmod(units.numerator, 10**scale)
    return str(whole) + ("." + str(fraction).zfill(scale) if scale else "")


def require_exact_consent(payload: PurchaseRequest, review: PurchaseReview) -> None:
    if payload.revision_id != review.revision_id or payload.expected_fingerprint != review.fingerprint:
        raise PurchaseRefused("commercial_terms_conflict", 409)
    if not payload.commercial_confirmation or payload.recurring_confirmation != review.recurring_required:
        raise PurchaseRefused("purchase_confirmation_required", 422)
    selected = {(doc.document_version_id, doc.acceptance_text_hash) for doc in payload.documents}
    expected = {(doc.document_version_id, doc.acceptance_text_hash) for doc in review.documents}
    if selected != expected:
        raise PurchaseRefused("purchase_document_selection_invalid", 422)
