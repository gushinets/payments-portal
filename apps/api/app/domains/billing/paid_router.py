"""Authenticated customer paid-state contract, separate from the Kernel wire."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, Field

from app.core.observability import request_id_context
from app.core.settings import settings
from app.composition.paid_reads import PaidReadResources
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.paid_read import PaidRead, ProductPaidStatus
from app.domains.catalog.contracts import SourceProvenance
from app.http.dependencies import get_paid_read_resources

router = APIRouter(prefix="/api", tags=["paid-access"])


class PaidAccessGrantResponse(BaseModel):
    product_id: str
    valid_until: str | None


class PaidAccessAllowanceResponse(BaseModel):
    allowance_id: str
    product_id: str
    metric_key: str
    unit: str
    quantity: int = Field(strict=True, ge=0)
    provenance: SourceProvenance


class PaidAccessProductResponse(BaseModel):
    product_id: str
    status: ProductPaidStatus
    observed_at: datetime | None
    effective_until: datetime | None


class PaidAccessResponse(BaseModel):
    access_revision: int = Field(ge=0)
    grants: list[PaidAccessGrantResponse]
    allowances: list[PaidAccessAllowanceResponse]
    products: list[PaidAccessProductResponse] = Field(max_length=100)
    evidence_complete: bool
    committed_at: datetime | None
    read_at: datetime
    effective_until: datetime | None


def present_paid_access(result: PaidRead) -> PaidAccessResponse:
    return PaidAccessResponse(
        access_revision=result.revision,
        grants=[
            PaidAccessGrantResponse(product_id=item.product_id, valid_until=item.valid_until)
            for item in result.document.grants
        ],
        allowances=[
            PaidAccessAllowanceResponse(
                allowance_id=item.allowance_id,
                product_id=item.product_id,
                metric_key=item.metric_key,
                unit=item.unit,
                quantity=item.quantity,
                provenance=result.provenance[item.allowance_id],
            )
            for item in result.document.allowances
        ],
        products=[
            PaidAccessProductResponse(
                product_id=item.product_id,
                status=item.status,
                observed_at=item.observed_at,
                effective_until=item.effective_until,
            )
            for item in result.products
        ],
        evidence_complete=result.evidence_complete,
        committed_at=result.committed_at,
        read_at=result.read_at,
        effective_until=result.effective_until,
    )


@router.get("/paid-access", response_model=PaidAccessResponse)
async def paid_access(
    response: Response,
    reads: Annotated[PaidReadResources, Depends(get_paid_read_resources)],
    authorization: Annotated[str | None, Header()] = None,
) -> PaidAccessResponse:
    response.headers["Cache-Control"] = "no-store"
    try:
        if not authorization or not authorization.startswith("Bearer ") or not authorization[7:].strip():
            raise BillingRefused("billing_session_required", 401)
        return present_paid_access(await reads.read(settings, authorization[7:].strip()))
    except BillingRefused as error:
        raise HTTPException(
            status_code=error.status,
            detail={"code": error.code, "request_id": request_id_context.get()},
            headers={"Cache-Control": "no-store"},
        ) from None
