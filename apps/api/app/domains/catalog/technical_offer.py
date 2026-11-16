"""Exact purchased technical meaning, independent of LBX commercial quantity."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.domains.catalog.mapping_evidence import Nonempty

# Exact in JavaScript/JSON and within PostgreSQL BIGINT.
TechnicalQuantity = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class TechnicalOffer(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    product_id: Nonempty
    metric_key: Nonempty
    unit: Nonempty
    quantity: TechnicalQuantity
    quantity_mode: Literal["fixed_per_cycle"]
