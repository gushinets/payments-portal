"""Independent, test-only ANY-766 wire oracle; never imported by application code."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, StrictInt, StringConstraints, model_validator

MAX_QUANTITY = 2**53 - 1
Quantity = Annotated[StrictInt, Field(ge=0, le=MAX_QUANTITY)]
Revision = Annotated[StrictInt, Field(ge=0)]
Identifier = Annotated[str, StringConstraints(min_length=1)]
CanonicalUUID = Annotated[
    str,
    StringConstraints(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"),
]
Code = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{43}$")]
Verifier = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9._~-]{43,128}$")]
SecretToken = Annotated[str, StringConstraints(min_length=43, max_length=512)]
UTC_TIMESTAMP_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|\+00:00)$"


def parse_utc_timestamp(value: object) -> datetime:
    # Pydantic otherwise also converts epoch strings to UTC datetimes in strict JSON mode.
    if not isinstance(value, str) or re.fullmatch(UTC_TIMESTAMP_PATTERN, value) is None:
        raise ValueError("UTC RFC3339 timestamp required")
    return datetime.fromisoformat(value)


UTCTimestamp = Annotated[
    datetime,
    BeforeValidator(parse_utc_timestamp),
    Field(json_schema_extra={"pattern": UTC_TIMESTAMP_PATTERN}),
]


class WireModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Owner(WireModel):
    tenant_id: Identifier
    region: Identifier
    user_id: CanonicalUUID


class Grant(WireModel):
    product_id: Identifier
    valid_until: UTCTimestamp | None


class Allowance(WireModel):
    allowance_id: CanonicalUUID
    product_id: Identifier
    metric_key: Identifier
    unit: Identifier
    quantity: Quantity


class Snapshot(Owner):
    schema_version: Literal[2]
    access_revision: Revision
    refresh_after: UTCTimestamp
    expires_at: UTCTimestamp
    grants: list[Grant]
    allowances: list[Allowance]

    @model_validator(mode="after")
    def effective_set(self) -> Self:
        if self.refresh_after > self.expires_at:
            raise ValueError("refresh after expiry")
        products = [grant.product_id for grant in self.grants]
        ids = [row.allowance_id for row in self.allowances]
        if len(set(products)) != len(products) or len(set(ids)) != len(ids):
            raise ValueError("duplicate identity")
        if any(row.product_id not in products for row in self.allowances):
            raise ValueError("allowance without product grant")
        if self.access_revision == 0 and (self.grants or self.allowances):
            raise ValueError("nonempty revision zero")
        if any(g.valid_until is not None and self.expires_at > g.valid_until for g in self.grants):
            raise ValueError("snapshot exceeds grant deadline")
        return self


class Invalidation(Owner):
    schema_version: Literal[1]
    access_revision: Revision


class CodeRequest(WireModel):
    code_challenge: Code
    code_challenge_method: Literal["S256"]


class CodeResponse(WireModel):
    code: Code
    expires_at: UTCTimestamp


class ExchangeRequest(WireModel):
    code: Code
    code_verifier: Verifier


class ExchangeResponse(Owner):
    schema_version: Literal[1]
    access_token: SecretToken
    token_type: Literal["Bearer"]
    expires_at: UTCTimestamp


class IntrospectionRequest(WireModel):
    access_token: SecretToken


class IntrospectionResponse(Owner):
    schema_version: Literal[1]
    valid_until: UTCTimestamp


class UsageQuery(Owner):
    allowance_ids: Annotated[list[CanonicalUUID], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def distinct_ids(self) -> Self:
        if len(set(self.allowance_ids)) != len(self.allowance_ids):
            raise ValueError("repeated allowance ID")
        return self


class Counters(WireModel):
    successful_used: Quantity
    reserved: Quantity
    remaining: Quantity
    available: Quantity
    read_at: UTCTimestamp


class ObservedUsage(Allowance, Counters):
    status: Literal["observed"]

    @model_validator(mode="after")
    def arithmetic(self) -> Self:
        if self.remaining != max(self.quantity - self.successful_used, 0):
            raise ValueError("invalid remaining")
        if self.available != max(self.quantity - self.successful_used - self.reserved, 0):
            raise ValueError("invalid available")
        if self.successful_used + self.reserved > self.quantity:
            raise ValueError("overdrawn allowance")
        return self


class UnobservedUsage(WireModel):
    allowance_id: CanonicalUUID
    status: Literal["unobserved"]


class UsageResponse(Owner):
    schema_version: Literal[1]
    items: Annotated[list[ObservedUsage | UnobservedUsage], Field(min_length=1, max_length=100)]

    @model_validator(mode="after")
    def distinct_ids(self) -> Self:
        ids = [row.allowance_id for row in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("repeated usage item")
        return self


class Exhaustion(Owner, Allowance):
    schema_version: Literal[1]
    event_type: Literal["allowance_exhausted"]
    occurred_at: UTCTimestamp


class CabinetObserved(ObservedUsage):
    classification: Literal["current", "historical"]


class CabinetUnknown(Allowance):
    classification: Literal["current", "historical"]
    status: Literal["unobserved", "unavailable"]


class CabinetResponse(Owner):
    schema_version: Literal[1]
    access_revision: Revision
    items: list[CabinetObserved | CabinetUnknown]

    @model_validator(mode="after")
    def distinct_ids(self) -> Self:
        ids = [row.allowance_id for row in self.items]
        if len(set(ids)) != len(ids):
            raise ValueError("repeated cabinet item")
        return self


MODELS: dict[str, type[WireModel]] = {
    "snapshot-v2": Snapshot,
    "invalidation-v1": Invalidation,
    "code-request-v1": CodeRequest,
    "code-response-v1": CodeResponse,
    "exchange-request-v1": ExchangeRequest,
    "exchange-response-v1": ExchangeResponse,
    "introspection-request-v1": IntrospectionRequest,
    "introspection-response-v1": IntrospectionResponse,
    "usage-query-v1": UsageQuery,
    "usage-response-v1": UsageResponse,
    "exhaustion-v1": Exhaustion,
    "cabinet-usage-v1": CabinetResponse,
}


def validate_contract(contract: str, encoded: str) -> WireModel:
    # Literal[1] alone accepts True/1.0 in Pydantic: keep protocol integers strict.
    import json

    payload = json.loads(encoded)
    if isinstance(payload, dict) and "schema_version" in payload:
        if type(payload["schema_version"]) is not int:
            raise ValueError("integer schema version required")
    return MODELS[contract].model_validate_json(encoded)


def correlate_usage(response: UsageResponse, query: UsageQuery) -> None:
    if any(getattr(response, name) != getattr(query, name) for name in Owner.model_fields):
        raise ValueError("usage owner mismatch")
    if [row.allowance_id for row in response.items] != query.allowance_ids:
        raise ValueError("usage order or completeness mismatch")
