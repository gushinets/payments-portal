from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any, TypeVar

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON, TypeDecorator

from app.core.database import Base


PersistedEnum = TypeVar("PersistedEnum", bound=StrEnum)


class PersistedEnumType(TypeDecorator[PersistedEnum]):
    """Store a closed ``StrEnum`` vocabulary in an existing text column."""

    impl = Text
    cache_ok = True

    def __init__(self, enum_cls: type[PersistedEnum]) -> None:
        if not isinstance(enum_cls, type) or not issubclass(enum_cls, StrEnum):
            raise TypeError("PersistedEnumType requires a concrete StrEnum class")
        self.enum_cls = enum_cls
        super().__init__()

    def process_bind_param(self, value: Any, dialect: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, self.enum_cls):
            return value.value
        raise TypeError(f"expected {self.enum_cls.__name__} or None, got {type(value).__name__}")

    def process_result_value(self, value: Any, dialect: Any) -> PersistedEnum | None:
        if value is None:
            return None
        return self.enum_cls(value)


json_type = JSON().with_variant(JSONB(), "postgresql")
uuid_type = Uuid(as_uuid=True)
ip_type = String(45).with_variant(INET(), "postgresql")


__all__ = [
    "JSON",
    "JSONB",
    "Base",
    "Boolean",
    "CheckConstraint",
    "DateTime",
    "ForeignKey",
    "ForeignKeyConstraint",
    "Index",
    "Integer",
    "Mapped",
    "PersistedEnumType",
    "String",
    "Text",
    "UniqueConstraint",
    "Uuid",
    "datetime",
    "func",
    "ip_type",
    "json_type",
    "mapped_column",
    "text",
    "uuid",
    "uuid_type",
]
