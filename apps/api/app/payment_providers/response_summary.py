from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PaymentsApiClientModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PaymentsApiJsonType(StrEnum):
    OBJECT = "object"
    ARRAY = "array"
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"
    NULL = "null"
    INVALID = "invalid"
    UNKNOWN = "unknown"


class PaymentsApiResponseSummary(PaymentsApiClientModel):
    json_type: PaymentsApiJsonType
    body_byte_length: int | None = Field(default=None, ge=0)
    field_count: int | None = Field(default=None, ge=0)
    item_count: int | None = Field(default=None, ge=0)

    @classmethod
    def invalid_json(cls, *, body_byte_length: int) -> PaymentsApiResponseSummary:
        return cls(json_type=PaymentsApiJsonType.INVALID, body_byte_length=body_byte_length)

    @classmethod
    def from_payload(cls, payload: Any) -> PaymentsApiResponseSummary:
        json_type = cls._json_type(payload)
        if isinstance(payload, Mapping):
            return cls(json_type=json_type, field_count=len(payload))
        if isinstance(payload, list):
            return cls(json_type=json_type, item_count=len(payload))
        return cls(json_type=json_type)

    @staticmethod
    def _json_type(value: Any) -> PaymentsApiJsonType:
        if isinstance(value, Mapping):
            return PaymentsApiJsonType.OBJECT
        if isinstance(value, list):
            return PaymentsApiJsonType.ARRAY
        if value is None:
            return PaymentsApiJsonType.NULL
        if isinstance(value, bool):
            return PaymentsApiJsonType.BOOLEAN
        if isinstance(value, (int, float)):
            return PaymentsApiJsonType.NUMBER
        if isinstance(value, str):
            return PaymentsApiJsonType.STRING
        return PaymentsApiJsonType.UNKNOWN
