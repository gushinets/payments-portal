from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.core.client_info import ClientInfo
from app.core.money import minor_to_decimal
from app.domains.billing.models import ProductAccessState
from app.domains.billing.schemas import PlanScopeType
from app.domains.identity.models import User
from app.models import Plan
from app.payment_providers.contracts import CheckoutAction


class CheckoutIntentRequest(BaseModel):
    product: str
    plan_code: str
    auto_renew: bool = False
    entrypoint_type: str = "product"
    frontend_id: str | None = None
    source_url: str | None = None


class ResolveSellablePlanInput(BaseModel):
    tenant_id: str
    region: str
    entrypoint_code: str
    plan_code: str


class OrderingSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")


class OrderStatusEnum(str, Enum):
    CREATED = "created"
    REQUIRES_CONSENTS = "requires_consents"
    PENDING_PAYMENT = "pending_payment"
    PAID = "paid"
    PAYMENT_FAILED = "payment_failed"
    CANCELED = "canceled"
    EXPIRED = "expired"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"
    REGION_MISMATCH = "region_mismatch"


class CheckoutSessionStatusEnum(str, Enum):
    CREATED = "created"
    ORDER_CREATED = "order_created"
    EXPIRED = "expired"


class ProductAccessStateStatusEnum(str, Enum):
    INACTIVE = "inactive"
    PENDING = "pending"


class CreateEntrypointSessionInput(OrderingSchema):
    tenant_id: str
    route_region: str
    resolved_region: str
    ip_country: str | None = None
    declared_country: str | None = None
    browser_language: str | None = None
    region_mismatch_status: str = "none"
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

    @classmethod
    def create(
        cls,
        *,
        payload: CheckoutIntentRequest,
        user: User,
        client_info: ClientInfo,
        sellable_plan: "SellablePlan",
    ) -> "CreateEntrypointSessionInput":
        return cls(
            tenant_id=user.tenant_id,
            route_region=user.region,
            resolved_region=user.region,
            entrypoint_type=payload.entrypoint_type,
            entrypoint_value=sellable_plan.entrypoint_value,
            product_id=sellable_plan.product_id,
            bundle_id=sellable_plan.bundle_id,
            frontend_id=payload.frontend_id or "web_checkout",
            user_id=user.id,
            source_url=payload.source_url,
            ip=client_info.ip,
            user_agent=client_info.user_agent,
            metadata_={
                "plan_code": payload.plan_code,
                "auto_renew": payload.auto_renew,
            },
        )


class CreateCheckoutSessionInput(OrderingSchema):
    tenant_id: str
    region: str
    user_id: UUID
    entrypoint_session_id: UUID | None = None
    plan_id: UUID | None = None
    status: CheckoutSessionStatusEnum = CheckoutSessionStatusEnum.CREATED
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    expires_at: datetime
    metadata_: dict = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        payload: CheckoutIntentRequest,
        user: User,
        sellable_plan: "SellablePlan",
        entrypoint_session_id: UUID,
        expires_at: datetime,
    ) -> "CreateCheckoutSessionInput":
        return cls(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            entrypoint_session_id=entrypoint_session_id,
            plan_id=sellable_plan.id,
            status=CheckoutSessionStatusEnum.ORDER_CREATED,
            amount_minor=sellable_plan.price_amount_minor,
            currency=sellable_plan.currency,
            expires_at=expires_at,
            metadata_={
                "product_code": payload.product,
                "plan_code": sellable_plan.code,
                "scope_type": sellable_plan.scope_type,
                "auto_renew": payload.auto_renew,
            },
        )


class CreateOrderInput(OrderingSchema):
    tenant_id: str
    region: str
    order_number: str
    user_id: UUID
    checkout_session_id: UUID | None = None
    entrypoint_session_id: UUID | None = None
    plan_id: UUID | None = None
    status: OrderStatusEnum = OrderStatusEnum.CREATED
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    tax_amount_minor: int = Field(default=0, ge=0)
    discount_amount_minor: int = Field(default=0, ge=0)
    provider: str
    provider_account_id: UUID
    merchant_order_id: str
    provider_invoice_id: str | None = None
    billing_country: str | None = None
    region_mismatch_status: str = "none"
    expires_at: datetime | None = None
    metadata_: dict = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        payload: CheckoutIntentRequest,
        user: User,
        sellable_plan: "SellablePlan",
        provider_account_id: UUID,
        provider: str,
        order_number: str,
        merchant_order_id: str,
        checkout_session_id: UUID,
        entrypoint_session_id: UUID,
        expires_at: datetime,
    ) -> "CreateOrderInput":
        return cls(
            tenant_id=user.tenant_id,
            region=user.region,
            order_number=order_number,
            user_id=user.id,
            checkout_session_id=checkout_session_id,
            entrypoint_session_id=entrypoint_session_id,
            plan_id=sellable_plan.id,
            status=OrderStatusEnum.PENDING_PAYMENT,
            amount_minor=sellable_plan.price_amount_minor,
            currency=sellable_plan.currency,
            provider=provider,
            provider_account_id=provider_account_id,
            merchant_order_id=merchant_order_id,
            provider_invoice_id=merchant_order_id,
            expires_at=expires_at,
            metadata_={
                "product_code": payload.product,
                "plan_code": sellable_plan.code,
                "scope_type": sellable_plan.scope_type,
                "auto_renew": payload.auto_renew,
            },
        )


class CreateOrderItemInput(OrderingSchema):
    order_id: UUID
    item_type: str
    product_id: UUID | None = None
    bundle_id: UUID | None = None
    plan_id: UUID | None = None
    product_code_snapshot: str | None = None
    plan_code_snapshot: str | None = None
    title_snapshot: str
    quantity: int = Field(default=1, ge=1)
    list_amount_minor: int = Field(ge=0)
    discount_amount_minor: int = Field(default=0, ge=0)
    unit_amount_minor: int = Field(ge=0)
    amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    trial_days_snapshot: int = Field(default=0, ge=0)
    pricing_snapshot: dict = Field(default_factory=dict)
    metadata_: dict = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        payload: CheckoutIntentRequest,
        sellable_plan: "SellablePlan",
        order_id: UUID,
    ) -> "CreateOrderItemInput":
        return cls(
            order_id=order_id,
            item_type=f"{sellable_plan.scope_type}_plan",
            product_id=sellable_plan.product_id,
            bundle_id=sellable_plan.bundle_id,
            plan_id=sellable_plan.id,
            product_code_snapshot=(
                payload.product if sellable_plan.scope_type == PlanScopeType.PRODUCT.value else None
            ),
            plan_code_snapshot=sellable_plan.code,
            title_snapshot=sellable_plan.name,
            quantity=1,
            list_amount_minor=sellable_plan.price_amount_minor,
            discount_amount_minor=0,
            unit_amount_minor=sellable_plan.price_amount_minor,
            amount_minor=sellable_plan.price_amount_minor,
            currency=sellable_plan.currency,
            trial_days_snapshot=sellable_plan.trial_days,
            pricing_snapshot=sellable_plan.pricing_snapshot,
        )


class SellablePlan(OrderingSchema):
    id: UUID
    entrypoint_value: str
    product_id: UUID | None = None
    bundle_id: UUID | None = None
    scope_type: PlanScopeType | str
    code: str
    name: str
    price_amount_minor: int = Field(ge=0)
    currency: str = Field(min_length=3, max_length=3)
    trial_days: int = Field(ge=0)
    billing_period: str
    pricing_snapshot: dict = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        plan: Plan,
        entrypoint_value: str,
    ) -> "SellablePlan":
        return cls(
            id=plan.id,
            entrypoint_value=entrypoint_value,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            scope_type=plan.scope_type,
            code=plan.code,
            name=plan.name,
            price_amount_minor=plan.price_amount_minor,
            currency=plan.currency,
            trial_days=plan.trial_days,
            billing_period=plan.billing_period,
            pricing_snapshot={
                "price_amount_minor": plan.price_amount_minor,
                "currency": plan.currency,
                "billing_period": plan.billing_period,
                "scope_type": plan.scope_type,
            },
        )


class CheckoutIntentProductStateResponse(OrderingSchema):
    product_code: str
    plan_code: str | None = None
    plan_name: str | None = None
    invoice_id: str | None = None
    transaction_id: str | None = None
    status: ProductAccessStateStatusEnum
    starts_at: str | None = None
    expires_at: str | None = None

    @classmethod
    def create(
        cls,
        *,
        state: ProductAccessState,
        product_code: str,
        plan_name: str,
    ) -> "CheckoutIntentProductStateResponse":
        return cls(
            product_code=product_code,
            plan_code=state.plan_code,
            plan_name=plan_name,
            invoice_id=state.last_invoice_id,
            transaction_id=state.last_transaction_id,
            status=state.status,
            starts_at=state.starts_at.isoformat() if state.starts_at else None,
            expires_at=state.expires_at.isoformat() if state.expires_at else None,
        )


class CheckoutIntentCheckoutResponse(OrderingSchema):
    amount_minor: int = Field(ge=0)
    amount: float
    currency: str = Field(min_length=3, max_length=3)
    action: CheckoutAction

    @classmethod
    def create(
        cls,
        *,
        amount_minor: int,
        currency: str,
        action: CheckoutAction,
    ) -> "CheckoutIntentCheckoutResponse":
        return cls(
            amount_minor=amount_minor,
            amount=minor_to_decimal(amount_minor),
            currency=currency,
            action=action,
        )


class CheckoutIntentResponse(OrderingSchema):
    status: str = "pending"
    product_state: CheckoutIntentProductStateResponse
    checkout: CheckoutIntentCheckoutResponse

    @classmethod
    def create(
        cls,
        *,
        product_code: str,
        plan_name: str,
        product_state: ProductAccessState,
        amount_minor: int,
        currency: str,
        checkout_action: CheckoutAction,
    ) -> "CheckoutIntentResponse":
        return cls(
            product_state=CheckoutIntentProductStateResponse.create(
                state=product_state,
                product_code=product_code,
                plan_name=plan_name,
            ),
            checkout=CheckoutIntentCheckoutResponse.create(
                amount_minor=amount_minor,
                currency=currency,
                action=checkout_action,
            ),
        )
