"""Cabinet usage DTOs. Missing observations never acquire counters."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.domains.billing.paid_usage import UsageClassification


class PaidUsageStatus(StrEnum):
    OBSERVED = "observed"
    UNOBSERVED = "unobserved"
    UNAVAILABLE = "unavailable"


class PaidUsageAllowance(BaseModel):
    allowance_id: str
    product_id: str
    metric_key: str
    unit: str
    quantity: int = Field(ge=0, le=2**53 - 1)
    classification: UsageClassification


class ObservedPaidUsage(PaidUsageAllowance):
    status: Literal[PaidUsageStatus.OBSERVED]
    successful_used: int = Field(ge=0)
    reserved: int = Field(ge=0)
    remaining: int = Field(ge=0)
    available: int = Field(ge=0)
    read_at: datetime


class UnobservedPaidUsage(PaidUsageAllowance):
    status: Literal[PaidUsageStatus.UNOBSERVED]


class UnavailablePaidUsage(PaidUsageAllowance):
    status: Literal[PaidUsageStatus.UNAVAILABLE]


PaidUsageItem = Annotated[ObservedPaidUsage | UnobservedPaidUsage | UnavailablePaidUsage, Field(discriminator="status")]


class PaidUsageResponse(BaseModel):
    access_revision: int = Field(ge=0)
    items: list[PaidUsageItem]


class PaidUsageErrorDetail(BaseModel):
    code: str
    request_id: str | None


class PaidUsageErrorResponse(BaseModel):
    detail: PaidUsageErrorDetail
