"""Portal purchase HTTP contracts. Browser values select/compare, never authorize money."""

from __future__ import annotations

from typing import Annotated, Awaitable, Literal, TypeVar
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from app.composition.purchases import advance_purchase, confirm_purchase, review_purchase
from app.core.errors import AppError
from app.core.observability import request_id_context
from app.core.settings import settings
from app.domains.billing.contracts import BillingAccountFailure, BillingRefused
from app.infrastructure.sentry import FailureCategory, Operation, report_exception
from app.domains.catalog.commercial_offer import canonical_decimal
from app.domains.catalog.contracts import MAX_PRODUCT_ID_LENGTH
from app.domains.catalog.product_link import CurrentOffer
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import (
    MAX_PURCHASE_LEGAL_DOCUMENTS,
    LegalEvidence,
    LegalSelection,
    Purchase,
    PurchaseMeaning,
)
from app.domains.purchases import service
from app.domains.purchases.account import list_account_purchases
from app.http.dependencies import get_session_factory
from app.models import PurchaseIntentState

router = APIRouter(prefix="/api", tags=["purchases"])
T = TypeVar("T")
PurchaseAmount = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]*)(\.[0-9]+)?$")]


class PurchaseReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1, max_length=MAX_PRODUCT_ID_LENGTH)


class PurchaseConfirmRequest(PurchaseReviewRequest):
    revision_id: UUID
    expected_fingerprint: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    documents: list[LegalSelection] = Field(min_length=1, max_length=MAX_PURCHASE_LEGAL_DOCUMENTS)

    @model_validator(mode="after")
    def unique_documents(self) -> PurchaseConfirmRequest:
        if len({doc.document_version_id for doc in self.documents}) != len(self.documents):
            raise ValueError("duplicate legal selection")
        return self

    def meaning(self) -> PurchaseMeaning:
        # Canonical set order prevents same-key conflicts caused by UI order alone.
        return PurchaseMeaning(
            product_id=self.product_id,
            revision_id=self.revision_id,
            expected_fingerprint=self.expected_fingerprint,
            documents=tuple(sorted(self.documents, key=lambda doc: str(doc.document_version_id))),
        )


class PurchaseTermsResponse(BaseModel):
    recurring_unit_amount: PurchaseAmount
    recurring_amount: PurchaseAmount
    connection_unit_amount: PurchaseAmount
    connection_amount: PurchaseAmount
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    decimal_places: int = Field(strict=True, ge=0, le=36)
    units: Literal["major"] = "major"
    commercial_quantity: str = Field(pattern=r"^[1-9][0-9]*$")
    period_unit: Literal["day", "week", "month", "year"]
    period_length: int = Field(strict=True, gt=0)
    period_anchor: Literal["calendar_month", "instance_start", "first_instance_start"]
    prepaid: bool
    full_funding_required: bool


class PurchaseReviewResponse(BaseModel):
    product_id: str
    revision_id: UUID
    expected_fingerprint: str
    terms: PurchaseTermsResponse
    documents: list[LegalEvidence]
    legal_status: Literal["draft"] = "draft"


class PurchaseIntentResponse(BaseModel):
    purchase_intent_id: UUID
    product_id: str
    state: PurchaseIntentState
    reason: str | None
    scope_held: bool
    accepted: PurchaseReviewResponse
    paid_access_granted: Literal[False] = False


class CurrentPurchaseResponse(BaseModel):
    purchase: PurchaseIntentResponse | None


class AccountPurchaseResponse(BaseModel):
    purchase_intent_id: UUID
    product_id: str
    state: PurchaseIntentState
    created_at: datetime


class AccountPurchasesResponse(BaseModel):
    purchases: list[AccountPurchaseResponse]
    next_cursor: UUID | None


def present_review(
    product_id: str, revision_id: UUID, offer: CurrentOffer, documents: tuple[LegalEvidence, ...]
) -> PurchaseReviewResponse:
    money = offer.money
    return PurchaseReviewResponse(
        product_id=product_id,
        revision_id=revision_id,
        expected_fingerprint=offer.fingerprint,
        terms=PurchaseTermsResponse(
            recurring_unit_amount=canonical_decimal(money.recurring_unit_amount),
            recurring_amount=canonical_decimal(money.recurring_amount),
            connection_unit_amount=canonical_decimal(money.connection_unit_amount),
            connection_amount=canonical_decimal(money.connection_amount),
            currency=money.currency,
            decimal_places=money.decimal_places,
            commercial_quantity=canonical_decimal(offer.quantity.selected),
            period_unit=offer.period.unit,
            period_length=offer.period.length,
            period_anchor=offer.period.anchor,
            prepaid=offer.prepaid,
            full_funding_required=offer.full_funding_required,
        ),
        documents=list(documents),
    )


def present_purchase(purchase: Purchase) -> PurchaseIntentResponse:
    return PurchaseIntentResponse(
        purchase_intent_id=purchase.id,
        product_id=purchase.accepted.meaning.product_id,
        state=purchase.state,
        reason=purchase.reason,
        scope_held=purchase.held,
        accepted=present_review(
            purchase.accepted.meaning.product_id,
            purchase.accepted.meaning.revision_id,
            purchase.accepted.offer,
            purchase.accepted.documents,
        ),
    )


def bearer(authorization: str | None) -> str:
    if (
        not authorization
        or not authorization.startswith("Bearer ")
        or not authorization.removeprefix("Bearer ").strip()
    ):
        raise HTTPException(
            status_code=401, detail={"code": "billing_session_required"}, headers={"Cache-Control": "no-store"}
        )
    return authorization.removeprefix("Bearer ").strip()


async def _boundary(work: Awaitable[T]) -> T:
    try:
        return await work
    except AppError as error:
        if isinstance(error, BillingAccountFailure):
            report_exception(
                error,
                operation=Operation.HTTP_REQUEST,
                failure_category=FailureCategory.INTEGRATION_FAILURE,
                method="POST",
                route="/api/purchase-intents/{purchase_id}/advance",
                error_code=error.code,
            )
        raise HTTPException(
            status_code=error.status if isinstance(error, BillingRefused) else 503,
            detail={"code": error.code, "request_id": request_id_context.get()},
            headers={"Cache-Control": "no-store"},
        ) from None


@router.post("/purchases/review", response_model=PurchaseReviewResponse)
async def review(
    payload: PurchaseReviewRequest,
    request: Request,
    response: Response,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    authorization: Annotated[str | None, Header()] = None,
) -> PurchaseReviewResponse:
    response.headers["Cache-Control"] = "no-store"
    link, offer, documents = await _boundary(
        review_purchase(
            request.app.state.sources,
            settings,
            factory=factory,
            token=bearer(authorization),
            product_id=payload.product_id,
        )
    )
    return present_review(payload.product_id, link.mapping_revision_id, offer, documents)


@router.post("/purchase-intents", response_model=PurchaseIntentResponse)
async def confirm(
    payload: PurchaseConfirmRequest,
    request: Request,
    response: Response,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    idempotency_key: Annotated[str, Header(min_length=1, max_length=128)],
    authorization: Annotated[str | None, Header()] = None,
) -> PurchaseIntentResponse:
    response.headers["Cache-Control"] = "no-store"
    if any(not 33 <= ord(char) <= 126 for char in idempotency_key):
        raise HTTPException(status_code=422, detail={"code": "purchase_idempotency_invalid"})
    return present_purchase(
        await _boundary(
            confirm_purchase(
                request.app.state.sources,
                settings,
                factory=factory,
                token=bearer(authorization),
                key=idempotency_key,
                meaning=payload.meaning(),
            )
        )
    )


@router.get("/purchase-intents/current", response_model=CurrentPurchaseResponse)
async def current(
    response: Response,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    product_id: Annotated[str, Query(min_length=1, max_length=MAX_PRODUCT_ID_LENGTH)],
    authorization: Annotated[str | None, Header()] = None,
) -> CurrentPurchaseResponse:
    response.headers["Cache-Control"] = "no-store"
    purchase = await _boundary(
        run_in_threadpool(service.current_purchase, factory, settings, bearer(authorization), product_id)
    )
    return CurrentPurchaseResponse(purchase=present_purchase(purchase) if purchase else None)


@router.get("/purchase-intents", response_model=AccountPurchasesResponse)
async def account_purchases(
    response: Response,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    after: UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    authorization: Annotated[str | None, Header()] = None,
) -> AccountPurchasesResponse:
    response.headers["Cache-Control"] = "no-store"
    items, next_cursor = await _boundary(
        run_in_threadpool(list_account_purchases, factory, settings, bearer(authorization), after=after, limit=limit)
    )
    return AccountPurchasesResponse(
        purchases=[
            AccountPurchaseResponse(
                purchase_intent_id=item.id, product_id=item.product_id, state=item.state, created_at=item.created_at
            )
            for item in items
        ],
        next_cursor=next_cursor,
    )


@router.get("/purchase-intents/{purchase_id}", response_model=PurchaseIntentResponse)
async def status(
    purchase_id: UUID,
    response: Response,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    authorization: Annotated[str | None, Header()] = None,
) -> PurchaseIntentResponse:
    response.headers["Cache-Control"] = "no-store"
    user_id = await _boundary(run_in_threadpool(service.authenticate_user, factory, settings, bearer(authorization)))
    return present_purchase(await _boundary(run_in_threadpool(service.read_purchase, factory, user_id, purchase_id)))


@router.post("/purchase-intents/{purchase_id}/advance", response_model=PurchaseIntentResponse)
async def advance(
    purchase_id: UUID,
    request: Request,
    response: Response,
    factory: Annotated[SessionFactory, Depends(get_session_factory)],
    authorization: Annotated[str | None, Header()] = None,
) -> PurchaseIntentResponse:
    response.headers["Cache-Control"] = "no-store"
    return present_purchase(
        await _boundary(
            advance_purchase(
                request.app.state.sources,
                settings,
                factory=factory,
                token=bearer(authorization),
                purchase_id=purchase_id,
            )
        )
    )
