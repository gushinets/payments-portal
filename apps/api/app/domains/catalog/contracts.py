from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SourceProvenance(StrEnum):
    # No configuration flag can assert real producer conformance in this slice.
    SIMULATED = "SIMULATED"


@dataclass(frozen=True)
class CapabilityProduct:
    product_id: str
    enabled: bool


@dataclass(frozen=True)
class CapabilityMetric:
    metric_key: str
    product_id: str
    unit: str
    enabled: bool


@dataclass(frozen=True)
class CapabilityManifest:
    schema_version: int
    tenant_id: str
    region: str
    manifest_version: str
    generated_at: datetime
    products: tuple[CapabilityProduct, ...]
    usage_metrics: tuple[CapabilityMetric, ...]
    provenance: SourceProvenance
