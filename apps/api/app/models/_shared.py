from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from app.core.database import Base
from app.domains.billing.enums import (
    EntitlementSource,
    EntitlementStatus,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    SubscriptionStatus,
)


json_type = JSON().with_variant(JSONB(), "postgresql")
uuid_type = Uuid(as_uuid=True)
ip_type = String(45).with_variant(INET(), "postgresql")
live_subscription_statuses_sql = (
    "status IN (" + ", ".join(f"'{status}'" for status in SubscriptionStatus.live_values()) + ")"
)
product_scope_sql = SubscriptionScopeType.PRODUCT.value
bundle_scope_sql = SubscriptionScopeType.BUNDLE.value
all_access_scope_sql = SubscriptionScopeType.ALL_ACCESS.value


__all__ = [
    "Base",
    "Boolean",
    "CheckConstraint",
    "DateTime",
    "Decimal",
    "EntitlementSource",
    "EntitlementStatus",
    "ForeignKey",
    "Index",
    "Integer",
    "JSON",
    "JSONB",
    "Mapped",
    "Numeric",
    "String",
    "SubscriptionRenewalMode",
    "SubscriptionScopeType",
    "SubscriptionStatus",
    "Text",
    "UniqueConstraint",
    "Uuid",
    "all_access_scope_sql",
    "bundle_scope_sql",
    "datetime",
    "func",
    "ip_type",
    "json_type",
    "live_subscription_statuses_sql",
    "mapped_column",
    "product_scope_sql",
    "text",
    "uuid",
    "uuid_type",
]
