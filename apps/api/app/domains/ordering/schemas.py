from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class OrderStatusEnum(str, Enum):
    CREATED = "created"
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"
    EXPIRED = "expired"


class CheckoutSessionStatusEnum(str, Enum):
    CREATED = "created"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    EXPIRED = "expired"


class CheckoutIntentRequest(BaseModel):
    product: str
    plan_code: str
    auto_renew: bool = False
    entrypoint_type: str = "product"
    frontend_id: str | None = None
    source_url: str | None = None



class OrderingSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrderItem(OrderingSchema):
    id: UUID
    order_id: UUID
    item_type: str
    product_id: UUID | None = None
    bundle_id: UUID | None = None
    plan_id: UUID | None = None
    product_code_snapshot: str | None = None
    plan_code_snapshot: str | None = None
    title_snapshot: str
    quantity: int = Field(ge=1)
    list_amount_minor: int = Field(ge=0)
    discount_amount_minor: int = Field(ge=0)
    unit_amount_minor: int = Field(ge=0)
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    trial_days_snapshot: int = Field(ge=0)
    pricing_snapshot: dict = Field(default_factory=dict)
    metadata_: dict = Field(default_factory=dict)
    created_at: datetime


class Order(OrderingSchema):
    id: UUID
    tenant_id: str
    region: str
    order_number: str
    user_id: UUID
    checkout_session_id: UUID | None = None
    entrypoint_session_id: UUID | None = None
    plan_id: UUID | None = None
    status: OrderStatusEnum | str
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    tax_amount_minor: int = Field(ge=0)
    discount_amount_minor: int = Field(ge=0)
    provider: str
    provider_account_id: UUID
    merchant_order_id: str
    provider_invoice_id: str | None = None
    billing_country: str | None = None
    region_mismatch_status: str
    paid_at: datetime | None = None
    failed_at: datetime | None = None
    canceled_at: datetime | None = None
    expires_at: datetime | None = None
    metadata_: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    items: list[OrderItem] = Field(default_factory=list)


class CheckoutSession(OrderingSchema):
    id: UUID
    tenant_id: str
    region: str
    user_id: UUID
    entrypoint_session_id: UUID | None = None
    plan_id: UUID | None = None
    status: CheckoutSessionStatusEnum | str
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    expires_at: datetime
    metadata_: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime


class EntrypointSession(OrderingSchema):
    id: UUID
    tenant_id: str
    route_region: str
    resolved_region: str
    ip_country: str | None = None
    declared_country: str | None = None
    browser_language: str | None = None
    region_mismatch_status: str
    entrypoint_type: str
    entrypoint_value: str
    product_id: UUID | None = None
    bundle_id: UUID | None = None
    frontend_id: str | None = None
    platform_guest_id: str | None = None
    platform_user_id: str | None = None
    scenario_session_id: str | None = None
    artifact_id: str | None = None
    user_id: UUID | None = None
    source_url: str | None = None
    acquisition_source: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    metadata_: dict = Field(default_factory=dict)
    created_at: datetime
