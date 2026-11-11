"""Service-authenticated B10 V2 snapshots of the complete committed paid set."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.composition.paid_reads import PaidReadResources
from app.core.settings import settings
from app.domains.billing.contracts import BillingRefused
from app.http.dependencies import get_paid_read_resources
from app.http.backend_auth import BackendPrincipal, authorize_snapshot
from app.http.backend_session_policy import BackendErrorResponse

router = APIRouter(
    prefix="/internal/v1/access-snapshots",
    tags=["access-snapshot"],
    responses={status: {"model": BackendErrorResponse} for status in (401, 403, 404, 422, 503)},
)


class AccessSnapshotGrant(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str = Field(min_length=1)
    valid_until: datetime | None


class AccessSnapshotAllowance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    allowance_id: UUID
    product_id: str = Field(min_length=1)
    metric_key: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    quantity: int = Field(strict=True, ge=0, le=2**53 - 1)


class AccessSnapshotResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[2]
    tenant_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    user_id: UUID
    access_revision: int = Field(strict=True, ge=0)
    refresh_after: datetime
    expires_at: datetime
    grants: list[AccessSnapshotGrant]
    allowances: list[AccessSnapshotAllowance]


@router.get("/{user_id}")
async def access_snapshot(
    user_id: UUID,
    principal: Annotated[BackendPrincipal, Depends(authorize_snapshot)],
    reads: Annotated[PaidReadResources, Depends(get_paid_read_resources)],
    tenant_id: Annotated[str, Query(min_length=1)],
    region: Annotated[str, Query(min_length=1)],
) -> AccessSnapshotResponse:
    try:
        result = await reads.snapshot(settings, user_id)
        return AccessSnapshotResponse(
            schema_version=2,
            tenant_id=principal.tenant_id,
            region=principal.region,
            user_id=user_id,
            access_revision=result.revision,
            refresh_after=result.refresh_after,
            expires_at=result.expires_at,
            # These source-conservative bounds are already committed semantic
            # contents. The separate cross-service budget bounds the envelope;
            # GET never rewrites a grant or its revision.
            grants=[AccessSnapshotGrant(**item.model_dump()) for item in result.document.grants],
            allowances=[
                AccessSnapshotAllowance(
                    allowance_id=item.allowance_id,
                    product_id=item.product_id,
                    metric_key=item.metric_key,
                    unit=item.unit,
                    quantity=item.quantity,
                )
                for item in result.document.allowances
            ],
        )
    except BillingRefused as error:
        raise HTTPException(error.status, detail={"code": error.code}) from None
