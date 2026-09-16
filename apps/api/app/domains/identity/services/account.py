from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domains.billing.enums import ProductAccessStatus
from app.domains.identity.services.auth import normalize_email, normalize_region, normalize_tenant_id
from app.infrastructure.queries.identity import get_user_by_normalized_email
from app.infrastructure.queries.orders import (
    get_latest_order_for_user_entrypoint,
    get_order_by_id,
    get_order_by_user_and_provider_invoice_id,
    get_order_item,
)
from app.infrastructure.queries.payments import (
    get_latest_payment_for_order,
    get_latest_payment_for_order_with_statuses,
)
from app.infrastructure.queries.plans import get_plan_by_id
from app.infrastructure.queries.products import (
    get_bundle_by_code,
    get_bundle_by_id,
    get_product_by_code,
    get_product_by_id,
)
from app.infrastructure.queries.subscriptions import get_active_entitlement_for_scope
from app.models import (
    Order,
    OrderItemType,
    OrderStatus,
    Payment,
    PaymentStatus,
    SubscriptionScopeType,
    User,
)


PRODUCT_DEFAULTS = {
    "document-summary": {
        "plan_code": "document-summary-pro",
        "plan_name": "Document Summary Pro",
        "price_amount_minor": 99000,
        "trial_days": 7,
    },
    "prompt-optimizer": {
        "plan_code": "prompt-optimizer-pro",
        "plan_name": "Prompt Optimizer Pro",
        "price_amount_minor": 99000,
        "trial_days": 7,
    },
}


@dataclass(frozen=True)
class ProductStateResult:
    product_code: str
    plan_code: str | None
    plan_name: str | None
    invoice_id: str | None
    transaction_id: str | None
    status: ProductAccessStatus
    starts_at: datetime | None
    expires_at: datetime | None


@dataclass(frozen=True)
class AccountSessionResult:
    tenant_id: str
    region: str
    user_id: uuid.UUID
    email: str
    product_state: ProductStateResult | None


@dataclass(frozen=True)
class PaymentStatusOrderResult:
    order_id: uuid.UUID
    order_number: str
    status: OrderStatus
    amount_minor: int
    currency: str
    paid_at: datetime | None
    failed_at: datetime | None


@dataclass(frozen=True)
class PaymentStatusPaymentResult:
    payment_id: uuid.UUID
    status: PaymentStatus
    provider_payment_id: str | None
    amount_minor: int
    currency: str
    captured_at: datetime | None
    failed_at: datetime | None
    refunded_amount_minor: int


@dataclass(frozen=True)
class PaymentStatusResult:
    tenant_id: str
    region: str
    user_id: uuid.UUID
    email: str
    product_state: ProductStateResult
    order: PaymentStatusOrderResult
    payment: PaymentStatusPaymentResult | None


def load_account_session(
    db: Session,
    *,
    user: User,
    product_code: str | None,
) -> AccountSessionResult:
    return AccountSessionResult(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        email=user.email,
        product_state=(_load_product_state(db, user=user, product_code=product_code) if product_code else None),
    )


def load_payment_status(
    db: Session,
    *,
    invoice_id: str,
    email: str,
    tenant_id: str,
    region: str,
) -> PaymentStatusResult | None:
    normalized_email = normalize_email(email)
    user = get_user_by_normalized_email(
        db,
        tenant_id=normalize_tenant_id(tenant_id),
        region=normalize_region(region),
        email_normalized=normalized_email,
    )
    if user is None:
        return None

    order = get_order_by_user_and_provider_invoice_id(
        db,
        user_id=user.id,
        provider_invoice_id=invoice_id,
    )
    if order is None:
        return None

    payment = None
    if order.status == OrderStatus.CANCELED:
        payment = get_latest_payment_for_order_with_statuses(
            db,
            order_id=order.id,
            statuses=(
                PaymentStatus.SUCCEEDED,
                PaymentStatus.PARTIALLY_REFUNDED,
                PaymentStatus.REFUNDED,
            ),
        )
    payment = payment or get_latest_payment_for_order(db, order.id)

    order_item = get_order_item(db, order.id)
    product_code = order_item.product_code_snapshot if order_item else None
    if product_code is None and order_item is not None and order_item.product_id is not None:
        product = get_product_by_id(db, order_item.product_id)
        product_code = product.code if product is not None else None
    elif product_code is None and order_item is not None and order_item.bundle_id is not None:
        bundle = get_bundle_by_id(db, order_item.bundle_id)
        product_code = bundle.code if bundle is not None else None
    elif product_code is None and order_item is not None and order_item.item_type == OrderItemType.ALL_ACCESS_PLAN:
        product_code = "all-access"
    if product_code is None:
        return None

    return PaymentStatusResult(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        email=normalized_email,
        product_state=_load_product_state(
            db,
            user=user,
            product_code=product_code,
            order=order,
            payment=payment,
        ),
        order=_payment_status_order_result(order),
        payment=_payment_status_payment_result(payment) if payment is not None else None,
    )


def _load_product_state(
    db: Session,
    *,
    user: User,
    product_code: str,
    order: Order | None = None,
    payment: Payment | None = None,
) -> ProductStateResult:
    now = utc_now()
    product = get_product_by_code(db, tenant_id=user.tenant_id, code=product_code)
    bundle = get_bundle_by_code(db, tenant_id=user.tenant_id, code=product_code) if product is None else None
    default_plan = PRODUCT_DEFAULTS.get(product_code, {}) if product is not None else {}
    if product is not None:
        scope_type = SubscriptionScopeType.PRODUCT
    elif bundle is not None:
        scope_type = SubscriptionScopeType.BUNDLE
    elif product_code == "all-access":
        scope_type = SubscriptionScopeType.ALL_ACCESS
    else:
        scope_type = None

    if scope_type is not None and order is None:
        order = get_latest_order_for_user_entrypoint(
            db,
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            product_id=product.id if product is not None else None,
            bundle_id=bundle.id if bundle is not None else None,
            scope_type=scope_type,
            entrypoint_code=product_code,
        )

    entitlement = None
    if scope_type is not None:
        entitlement = get_active_entitlement_for_scope(
            db,
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            scope_type=scope_type,
            product_id=product.id if product is not None else None,
            bundle_id=bundle.id if bundle is not None else None,
            now=now,
        )

    if entitlement is not None:
        if order is None and entitlement.order_id is not None:
            order = get_order_by_id(db, entitlement.order_id)
        payment = payment or (get_latest_payment_for_order(db, order.id) if order is not None else None)
        status = ProductAccessStatus.ACTIVE
        starts_at = entitlement.valid_from
        expires_at = entitlement.valid_until
    else:
        starts_at = order.created_at if order is not None else None
        expires_at = None
        pending_order_statuses = {OrderStatus.CREATED, OrderStatus.PENDING_PAYMENT}
        status = (
            ProductAccessStatus.PENDING
            if order is not None and order.status in pending_order_statuses
            else ProductAccessStatus.INACTIVE
        )

    plan = None
    if entitlement is not None:
        plan = get_plan_by_id(db, entitlement.plan_id)
    elif order is not None and order.plan_id is not None:
        plan = get_plan_by_id(db, order.plan_id)

    return ProductStateResult(
        product_code=product_code,
        plan_code=plan.code if plan is not None else default_plan.get("plan_code"),
        plan_name=plan.name if plan is not None else default_plan.get("plan_name"),
        invoice_id=order.provider_invoice_id if order else None,
        transaction_id=payment.provider_payment_id if payment else None,
        status=status,
        starts_at=starts_at,
        expires_at=expires_at,
    )


def _payment_status_order_result(order: Order) -> PaymentStatusOrderResult:
    return PaymentStatusOrderResult(
        order_id=order.id,
        order_number=order.order_number,
        status=order.status,
        amount_minor=order.amount_minor,
        currency=order.currency,
        paid_at=order.paid_at,
        failed_at=order.failed_at,
    )


def _payment_status_payment_result(payment: Payment) -> PaymentStatusPaymentResult:
    return PaymentStatusPaymentResult(
        payment_id=payment.id,
        status=payment.status,
        provider_payment_id=payment.provider_payment_id,
        amount_minor=payment.amount_minor,
        currency=payment.currency,
        captured_at=payment.captured_at,
        failed_at=payment.failed_at,
        refunded_amount_minor=payment.refunded_amount_minor,
    )
