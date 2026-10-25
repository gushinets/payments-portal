"""Authenticated provider-neutral purchase HTTP projection."""

from __future__ import annotations

from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
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
from app.domains.purchases.widget import WidgetPrincipal
from app.http.dependencies import get_current_session
from app.models import PurchaseIntentState


router = APIRouter(prefix="/api/purchases", tags=["purchases"])
billing_router = APIRouter(prefix="/api/billing", tags=["purchases"])


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
    next_action: Literal["wait", "continue", "manage", "manual_review"]
    continue_available: bool
    accepted_at: str
    accepted_terms: PurchaseReviewResponse


class ProductPurchaseStatusResponse(BaseModel):
    state: Literal["not_ready", "preparing", "recovery_pending", "occupied", "manual_review", "manage"]
    purchase_intent_id: UUID | None


class WidgetBootstrapRequest(BaseModel):
    model_config = {"extra": "forbid", "hide_input_in_errors": True}

    product_id: Annotated[str, Field(min_length=1, max_length=256, pattern=r"\S")]
    purchase_intent_id: UUID | None = None


class WidgetBootstrapResponse(BaseModel):
    mode: Literal["SIMULATED", "LOCAL_043"]
    credential: str = Field(repr=False)
    sdk: Literal["isolated_stub", "lbxwidget"] = "isolated_stub"
    widget_origin: Literal["self", "https://043.lbxbilling.ru"] = "self"
    serviceBaseUrl: Literal["https://043.lbxbilling.ru/api/rest/v1/client"] | None = None
    disableCreateSubscription: Literal[True] = True
    disableEditSubscription: Literal[True] = True
    disableStopSubscription: Literal[True] = True
    disableAutopayments: Literal[True] = True
    disablePayments: Literal[True] = True
    disableInvoiceGeneration: Literal[True] = True


def widget_principal(
    db: Annotated[Session, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> WidgetPrincipal:
    try:
        user, session = get_current_session(db, authorization)
        return WidgetPrincipal(user.id, session.id)
    except HTTPException as error:
        raise HTTPException(status_code=error.status_code, detail={"code": str(error.detail)}) from None
    finally:
        db.close()


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
    resumable = value.state in (
        PurchaseIntentState.CREATED,
        PurchaseIntentState.PREPARING,
        PurchaseIntentState.AWAITING_EXTERNAL_RESULT,
    )
    return PurchaseResponse(
        purchase_intent_id=value.purchase_intent_id,
        state=PurchaseIntentState(value.state),
        next_action=(
            "manual_review"
            if value.state == PurchaseIntentState.MANUAL_REVIEW
            else "manage"
            if value.state == PurchaseIntentState.LINKED
            else "continue"
            if resumable
            else "wait"
        ),
        continue_available=resumable,
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


@router.post("/{purchase_intent_id}/continue", response_model=PurchaseResponse, status_code=202)
async def continue_purchase(
    purchase_intent_id: UUID,
    user_id: Annotated[UUID, Depends(purchase_user)],
    use_case: Annotated[PurchaseApplication, Depends(application)],
) -> PurchaseResponse:
    try:
        return present_purchase(await use_case.continue_purchase(user_id, purchase_intent_id))
    except AppError as error:
        raise safe_error(error) from None


@billing_router.get("/products/{product_id}/status", response_model=ProductPurchaseStatusResponse)
def product_purchase_status(
    product_id: str,
    user_id: Annotated[UUID, Depends(purchase_user)],
    use_case: Annotated[PurchaseApplication, Depends(application)],
) -> ProductPurchaseStatusResponse:
    state, intent_id = use_case.product_status(user_id, product_id)
    return ProductPurchaseStatusResponse(state=state, purchase_intent_id=intent_id)


@billing_router.post("/widget-bootstrap", response_model=WidgetBootstrapResponse)
async def widget_bootstrap(
    payload: WidgetBootstrapRequest,
    principal: Annotated[WidgetPrincipal, Depends(widget_principal)],
    use_case: Annotated[PurchaseApplication, Depends(application)],
) -> WidgetBootstrapResponse:
    try:
        if use_case.widget is None:
            raise PurchaseRefused("billing_not_ready", 503)
        result = await use_case.widget.bootstrap(principal, payload.product_id, payload.purchase_intent_id)
        return WidgetBootstrapResponse(
            mode=result.mode,
            credential=result.credential,
            sdk="lbxwidget" if result.mode == "LOCAL_043" else "isolated_stub",
            widget_origin="https://043.lbxbilling.ru" if result.mode == "LOCAL_043" else "self",
            serviceBaseUrl="https://043.lbxbilling.ru/api/rest/v1/client" if result.mode == "LOCAL_043" else None,
        )
    except AppError as error:
        if isinstance(error, PurchaseRefused):
            raise safe_error(error) from None
        raise HTTPException(status_code=503, detail={"code": "billing_not_ready"}) from None
