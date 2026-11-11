"""Consumer-side V1 usage boundary, shared by configured backend owners."""

from datetime import datetime
from enum import StrEnum
import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

WireId = Annotated[str, Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")]
Counter = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class UsageStatus(StrEnum):
    OBSERVED = "observed"
    UNOBSERVED = "unobserved"


def _read_time(value: object) -> datetime:
    if (
        not isinstance(value, str)
        or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)", value) is None
    ):
        raise ValueError("Expected RFC3339 UTC timestamp")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


class UnobservedUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    allowance_id: WireId
    status: Literal[UsageStatus.UNOBSERVED]


class ObservedUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    allowance_id: WireId
    status: Literal[UsageStatus.OBSERVED]
    product_id: str = Field(min_length=1)
    metric_key: str = Field(min_length=1)
    unit: str = Field(min_length=1)
    quantity: Counter
    successful_used: Counter
    reserved: Counter
    remaining: Counter
    available: Counter
    read_at: Annotated[datetime, BeforeValidator(_read_time)]

    @model_validator(mode="after")
    def counters_match(self) -> "ObservedUsage":
        if self.remaining != max(self.quantity - self.successful_used, 0) or self.available != max(
            self.quantity - self.successful_used - self.reserved, 0
        ):
            raise ValueError("Inconsistent usage counters")
        return self


class UsageResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Annotated[int, Field(ge=1, le=1)]
    tenant_id: str = Field(min_length=1)
    region: str = Field(min_length=1)
    user_id: WireId
    items: list[Annotated[ObservedUsage | UnobservedUsage, Field(discriminator="status")]] = Field(
        min_length=1, max_length=100
    )
