"""Authenticated provider-neutral purchase HTTP projection."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.composition.purchases import purchase_application
from app.core.database import SessionLocal, get_db
from app.core.errors import AppError
from app.core.settings import settings
from app.domains.catalog.preview import CatalogProductNotFound
from app.domains.catalog.publication import StoredMapping
from app.domains.catalog.presentation import CatalogOffer, present_offer
from app.domains.purchases.contracts import (
    PersistedPurchase,
    PinnedDocument,
    PurchaseRefused,
    PurchaseRequest,
    PurchaseReview,
)
from app.domains.purchases.service import PurchaseApplication
from app.http.dependencies import get_current_session
from app.models import PurchaseIntentState


router = APIRouter(prefix="/api/purchases", tags=["purchases"])


class PurchaseReviewResponse(BaseModel):
    product_id: str
    availability: Literal["APPROVED_UNVERIFIED_NOW", "SIMULATED_PREVIEW"]
    fingerprint: str
    offer: CatalogOffer
    seller_name: str
    initial_amount: str
    recurring_required: bool
    renewal_terms: str
    cancellation_terms: str
    documents: list[PinnedDocument]


class PurchaseResponse(BaseModel):
    purchase_intent_id: UUID
    state: PurchaseIntentState
    next_action: Literal["wait", "manual_review"]
    continue_available: bool
    accepted_at: str
    accepted_terms: PurchaseReviewResponse


def present_review(review: PurchaseReview) -> PurchaseReviewResponse:
    document = review.mapping
    return PurchaseReviewResponse(
        product_id=document.material.technical.product_id,
        availability="SIMULATED_PREVIEW" if document.evidence_mode == "SIMULATED" else "APPROVED_UNVERIFIED_NOW",
        fingerprint=review.fingerprint,
        offer=present_offer(StoredMapping(review.revision_id, review.revision_number, document)),
        seller_name=review.seller_name,
        initial_amount=review.initial_amount,
        recurring_required=review.recurring_required,
        renewal_terms=document.material.terms.policy.renewal_terms,
        cancellation_terms=document.material.terms.policy.cancellation_terms,
        documents=list(review.documents),
    )


def present_purchase(value: PersistedPurchase) -> PurchaseResponse:
    return PurchaseResponse(
        purchase_intent_id=value.purchase_intent_id,
        state=PurchaseIntentState(value.state),
        next_action="manual_review" if value.state == PurchaseIntentState.MANUAL_REVIEW else "wait",
        continue_available=False,
        accepted_at=value.accepted.accepted_at.isoformat(),
        accepted_terms=present_review(value.accepted.review),
    )


def purchase_user(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> UUID:
    try:
        user, _ = get_current_session(db, authorization)
        return user.id
    except HTTPException as error:
        raise HTTPException(status_code=error.status_code, detail={"code": str(error.detail)}) from None
    finally:
        # authenticate_session refreshes rows after commit. Release that read
        # transaction too, before the async fresh-source branch can begin.
        db.close()


def application(request: Request) -> PurchaseApplication:
    return purchase_application(settings, SessionLocal, getattr(request.app.state, "sources", None))


def safe_error(error: AppError) -> HTTPException:
    if isinstance(error, PurchaseRefused):
        return HTTPException(status_code=error.status, detail={"code": error.code})
    if isinstance(error, CatalogProductNotFound):
        return HTTPException(status_code=404, detail={"code": "purchase_product_not_found"})
    if error.code == "mapping_approved_material_mismatch":
        return HTTPException(status_code=409, detail={"code": "commercial_terms_conflict"})
    return HTTPException(status_code=503, detail={"code": "purchase_sources_unavailable"})


@router.get("/review/{product_id}", response_model=PurchaseReviewResponse)
def review_purchase(
    product_id: str,
    _user_id: Annotated[UUID, Depends(purchase_user)],
    use_case: Annotated[PurchaseApplication, Depends(application)],
) -> PurchaseReviewResponse:
    try:
        return present_review(use_case.review(product_id))
    except AppError as error:
        raise safe_error(error) from None


@router.post("", response_model=PurchaseResponse, status_code=202)
async def create_purchase(
    payload: PurchaseRequest,
    user_id: Annotated[UUID, Depends(purchase_user)],
    use_case: Annotated[PurchaseApplication, Depends(application)],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=256, pattern=r"^\S(?:.*\S)?$")],
) -> PurchaseResponse:
    try:
        return present_purchase(await use_case.purchase(user_id, idempotency_key, payload))
    except AppError as error:
        raise safe_error(error) from None


@router.get("/{purchase_intent_id}", response_model=PurchaseResponse)
def get_purchase(
    purchase_intent_id: UUID,
    user_id: Annotated[UUID, Depends(purchase_user)],
    use_case: Annotated[PurchaseApplication, Depends(application)],
) -> PurchaseResponse:
    try:
        return present_purchase(use_case.status(user_id, purchase_intent_id))
    except AppError as error:
        raise safe_error(error) from None
