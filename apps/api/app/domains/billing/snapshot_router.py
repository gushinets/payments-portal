"""Service-authenticated B10 V3 snapshots of each consumer's committed paid set."""

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
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [
                {
                    "schema_version": 3,
                    "consumer_id": "platform-kernel",
                    "consumer_policy_revision": 1,
                    "tenant_id": "anytoolai",
                    "region": "ru",
                    "user_id": "00000000-0000-4000-8000-000000000001",
                    "access_revision": 0,
                    "refresh_after": "2026-11-11T04:01:00Z",
                    "expires_at": "2026-11-11T04:04:55Z",
                    "grants": [],
                    "allowances": [],
                }
            ]
        },
    )
    schema_version: Literal[3]
    consumer_id: str = Field(pattern=r"^[a-z][a-z0-9-]{0,63}$")
    consumer_policy_revision: int = Field(strict=True, ge=1, le=2**53 - 1)
    tenant_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    user_id: UUID
    access_revision: int = Field(strict=True, ge=0)
    refresh_after: datetime
    expires_at: datetime
    grants: list[AccessSnapshotGrant]
    allowances: list[AccessSnapshotAllowance]


@router.get(
    "/{user_id}",
    summary="Read this consumer's committed paid authority (V3)",
    description="Requires BackendServiceBearer with access-snapshot:read. The credential selects consumer, "
    "products and current policy P; tenant_id/region can only narrow its scope. R is the whole-user paid revision. "
    "Included allowances must retain this consumer's technical source and backend ownership; policy changes "
    "cannot transfer existing allowances or usage. Only included products and their supporting facts bound "
    "completeness and expiry. Read-only local GET: "
    "no backend/LBX calls or usage writes. Known empty users return R0. All responses are no-store; browser "
    "Origin is refused. 401: service credential; 403: scope/permission/browser; 404: unknown scoped user; "
    "422: malformed or missing scope; 503: retained allowance owner conflict, overdue included facts, stale policy, "
    "storage/capacity/clock unavailable. "
    "Quantity is the purchased ceiling. Backends must bind consumer/scope/P/R, preserve durable floors, "
    "and atomically reserve/finalize/release in their own usage storage; this read alone cannot admit execution.",
)
async def access_snapshot(
    user_id: UUID,
    principal: Annotated[BackendPrincipal, Depends(authorize_snapshot)],
    reads: Annotated[PaidReadResources, Depends(get_paid_read_resources)],
    tenant_id: Annotated[str, Query(min_length=1)],
    region: Annotated[str, Query(min_length=1)],
) -> AccessSnapshotResponse:
    try:
        result = await reads.snapshot(settings, user_id, principal.consumer)
        return AccessSnapshotResponse(
            schema_version=3,
            consumer_id=principal.consumer.consumer_id,
            consumer_policy_revision=principal.consumer.consumer_policy_revision,
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
