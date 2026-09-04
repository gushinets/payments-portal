from __future__ import annotations

import secrets
import uuid
from datetime import datetime
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.core.observability import record_checkout
from app.core.time import utc_now
from app.domains.legal.service import get_active_required_documents, present_required_document
from app.infrastructure.queries.plans import get_current_sellable_plan
from app.models import (
    BillingPeriod,
    Bundle,
    BundleStatus,
    Product,
    ProductStatus,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    User,
)
from app.payment_providers.contracts import CheckoutAction


class CheckoutIntentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    auto_renew: bool = False
    recurring_consent_acceptance_id: uuid.UUID | None = None
    entrypoint_type: str
    entrypoint_value: str
    frontend_id: str | None = None
    source_url: str | None = None


class ResolvedCheckoutPlan(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: uuid.UUID
    code: str
    name: str
    scope_type: SubscriptionScopeType
    product_id: uuid.UUID | None
    bundle_id: uuid.UUID | None
    product_code: str | None
    price_amount_minor: int
    currency: str
    trial_days: int
    billing_period: BillingPeriod
    renewal_mode: SubscriptionRenewalMode
    pricing_snapshot: dict


class CheckoutPurchaseResponse(BaseModel):
    order_id: uuid.UUID
    plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    scope_type: SubscriptionScopeType
    product_id: uuid.UUID | None
    bundle_id: uuid.UUID | None
    invoice_id: str


class CheckoutPaymentResponse(BaseModel):
    amount_minor: int
    amount: float
    currency: str
    action: CheckoutAction


class CheckoutIntentResponse(BaseModel):
    status: Literal["pending"] = "pending"
    purchase: CheckoutPurchaseResponse
    checkout: CheckoutPaymentResponse


def make_invoice_id() -> str:
    return uuid.uuid4().hex


def make_order_number(region: str) -> str:
    return f"{region.upper()}-{utc_now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"


def get_sellable_plan(db: Session, *, user: User, plan_id: uuid.UUID, now: datetime) -> ResolvedCheckoutPlan:
    plan = get_current_sellable_plan(
        db,
        plan_id=plan_id,
        tenant_id=user.tenant_id,
        region=user.region,
        now=now,
    )
    if plan is None:
        raise HTTPException(status_code=400, detail="unknown_product_plan")

    scope_type = plan.scope_type

    product_code = None
    if scope_type is SubscriptionScopeType.PRODUCT:
        if plan.product_id is None or plan.bundle_id is not None:
            raise HTTPException(status_code=400, detail="unknown_product_plan")
        product = (
            db.query(Product)
            .filter(
                Product.id == plan.product_id,
                Product.tenant_id == user.tenant_id,
                Product.status == ProductStatus.ACTIVE,
            )
            .first()
        )
        if product is None:
            raise HTTPException(status_code=400, detail="unknown_product_plan")
        product_code = product.code
    elif scope_type is SubscriptionScopeType.BUNDLE:
        if plan.product_id is not None or plan.bundle_id is None:
            raise HTTPException(status_code=400, detail="unknown_product_plan")
        bundle = (
            db.query(Bundle)
            .filter(
                Bundle.id == plan.bundle_id,
                Bundle.tenant_id == user.tenant_id,
                Bundle.status == BundleStatus.ACTIVE,
            )
            .first()
        )
        if bundle is None:
            raise HTTPException(status_code=400, detail="unknown_product_plan")
    elif plan.product_id is not None or plan.bundle_id is not None:
        raise HTTPException(status_code=400, detail="unknown_product_plan")

    return ResolvedCheckoutPlan(
        id=plan.id,
        code=plan.code,
        name=plan.name,
        scope_type=scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        product_code=product_code,
        price_amount_minor=plan.price_amount_minor,
        currency=plan.currency,
        trial_days=plan.trial_days,
        billing_period=plan.billing_period,
        renewal_mode=plan.renewal_mode,
        pricing_snapshot={
            "price_amount_minor": plan.price_amount_minor,
            "currency": plan.currency,
            "billing_period": plan.billing_period,
            "scope_type": scope_type.value,
        },
    )


def raise_missing_recurring_consent(db: Session, *, user: User, now: datetime) -> None:
    recurring_documents = [
        document
        for document in get_active_required_documents(
            db,
            tenant_id=user.tenant_id,
            region=user.region,
            now=now,
        )
        if document.doc_type == "recurring_consent"
    ]
    if recurring_documents:
        record_checkout("missing_required_documents")
        raise HTTPException(
            status_code=409,
            detail={
                "code": "missing_required_documents",
                "documents": [present_required_document(document) for document in recurring_documents],
            },
        )
    raise HTTPException(status_code=409, detail={"code": "recurring_consent_required"})
