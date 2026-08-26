from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import PaymentProviderConfigurationError
from app.core.observability import record_checkout, traced
from app.domains.identity.passwords import hash_password, verify_password
from app.domains.legal.service import (
    get_current_recurring_consent_acceptance,
    get_missing_required_documents_for_user,
    present_required_document,
)
from app.domains.billing.enums import (
    OrderStatus,
    PaymentStatus,
    ProductAccessStatus,
    SubscriptionScopeType,
    SubscriptionRenewalMode,
)
from app.domains.identity.session import (
    DEFAULT_REGION,
    DEFAULT_TENANT_ID,
    get_current_session,
)
from app.core.time import utc_now
from app.infrastructure.queries.orders import (
    get_order_by_id,
    get_latest_order_for_user_entrypoint,
    get_order_item,
)
from app.infrastructure.queries.payments import get_latest_payment_for_order
from app.infrastructure.queries.plans import get_plan_by_id
from app.infrastructure.queries.products import get_product_by_code
from app.infrastructure.queries.products import (
    get_bundle_by_code,
    get_bundle_by_id,
    get_product_by_id,
)
from app.infrastructure.queries.subscriptions import get_active_entitlement_for_scope
from app.models import (
    AuthSession,
    Bundle,
    CheckoutSession,
    EntrypointSession,
    Order,
    OrderItem,
    Payment,
    Plan,
    Product,
    User,
)
from app.payment_providers.accounts import get_or_create_checkout_provider_account
from app.payment_providers.registry import (
    PaymentProviderRegistry,
    get_payment_provider_registry,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_TTL_DAYS = 30
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


class RegisterRequest(BaseModel):
    tenant_id: str = DEFAULT_TENANT_ID
    region: str = DEFAULT_REGION
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    personal_consent: bool
    offer_consent: bool


class LoginRequest(BaseModel):
    tenant_id: str = DEFAULT_TENANT_ID
    region: str = DEFAULT_REGION
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class CheckoutIntentRequest(BaseModel):
    product: str
    plan_code: str
    auto_renew: bool = False
    recurring_consent_acceptance_id: uuid.UUID | None = None
    entrypoint_type: str = "product"
    frontend_id: str | None = None
    source_url: str | None = None


def make_session_token() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = utc_now() + timedelta(days=SESSION_TTL_DAYS)
    return token, token_hash, expires_at


def normalize_tenant_id(value: str) -> str:
    return value.strip().lower()


def normalize_region(value: str) -> str:
    return value.strip().lower()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def present_user(user: User) -> dict:
    return {
        "tenant_id": user.tenant_id,
        "region": user.region,
        "user_id": str(user.id),
        "email": user.email,
    }


def make_invoice_id(product_code: str) -> str:
    return f"{product_code}-{secrets.token_hex(8)}"


def make_order_number(region: str) -> str:
    return f"{region.upper()}-{utc_now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"


def get_product_defaults(product_code: str, plan_code: str) -> dict:
    defaults = PRODUCT_DEFAULTS.get(product_code)
    if defaults is None or defaults["plan_code"] != plan_code:
        raise HTTPException(status_code=400, detail="unknown_product_plan")
    return defaults


def get_sellable_plan(db: Session, *, user: User, entrypoint_code: str, plan_code: str) -> dict:
    now = utc_now()
    plan = (
        db.query(Plan)
        .filter(
            Plan.tenant_id == user.tenant_id,
            Plan.region == user.region,
            Plan.code == plan_code,
            Plan.status == "active",
            Plan.valid_from <= now,
            or_(Plan.valid_to.is_(None), Plan.valid_to > now),
        )
        .order_by(Plan.valid_from.desc(), Plan.created_at.desc())
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=400, detail="unknown_product_plan")

    product_code = None
    bundle_code = None
    if plan.scope_type == "product":
        product = db.get(Product, plan.product_id) if plan.product_id else None
        product_code = product.code if product else None
        if product_code != entrypoint_code or product.status != "active":
            raise HTTPException(status_code=400, detail="unknown_product_plan")
    elif plan.scope_type == "bundle":
        bundle = db.get(Bundle, plan.bundle_id) if plan.bundle_id else None
        bundle_code = bundle.code if bundle else None
        if bundle_code != entrypoint_code or bundle.status != "active":
            raise HTTPException(status_code=400, detail="unknown_product_plan")
    elif plan.scope_type == "all_access":
        if entrypoint_code not in {"all-access", plan.code}:
            raise HTTPException(status_code=400, detail="unknown_product_plan")
    else:
        raise HTTPException(status_code=400, detail="unknown_product_plan")

    return {
        "plan_id": plan.id,
        "product_id": plan.product_id,
        "bundle_id": plan.bundle_id,
        "scope_type": plan.scope_type,
        "entrypoint_value": product_code or bundle_code or "all-access",
        "plan_code": plan.code,
        "plan_name": plan.name,
        "amount_minor": plan.price_amount_minor,
        "currency": plan.currency,
        "trial_days": plan.trial_days,
        "renewal_mode": plan.renewal_mode,
        "pricing_snapshot": {
            "price_amount_minor": plan.price_amount_minor,
            "currency": plan.currency,
            "billing_period": plan.billing_period,
            "scope_type": plan.scope_type,
        },
    }


def present_product_state(
    db: Session,
    *,
    user: User,
    product_code: str,
    order: Order | None = None,
    payment: Payment | None = None,
) -> dict:
    now = utc_now()
    product = get_product_by_code(db, tenant_id=user.tenant_id, code=product_code)
    bundle = get_bundle_by_code(db, tenant_id=user.tenant_id, code=product_code) if product is None else None
    default_plan = PRODUCT_DEFAULTS.get(product_code, {}) if product is not None else {}
    if product is not None:
        scope_type = SubscriptionScopeType.PRODUCT.value
    elif bundle is not None:
        scope_type = SubscriptionScopeType.BUNDLE.value
    elif product_code == "all-access":
        scope_type = SubscriptionScopeType.ALL_ACCESS.value
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
        status = ProductAccessStatus.ACTIVE.value
        starts_at = entitlement.valid_from
        expires_at = entitlement.valid_until
    else:
        starts_at = order.created_at if order is not None else None
        expires_at = None
        pending_order_statuses = {"created", OrderStatus.PENDING_PAYMENT.value}
        status = (
            ProductAccessStatus.PENDING.value
            if order is not None and order.status in pending_order_statuses
            else ProductAccessStatus.INACTIVE.value
        )
    plan = None
    if entitlement is not None:
        plan = get_plan_by_id(db, entitlement.plan_id)
    elif order is not None and order.plan_id is not None:
        plan = get_plan_by_id(db, order.plan_id)
    return {
        "product_code": product_code,
        "plan_code": plan.code if plan is not None else default_plan.get("plan_code"),
        "plan_name": plan.name if plan is not None else default_plan.get("plan_name"),
        "invoice_id": order.provider_invoice_id if order else None,
        "transaction_id": payment.provider_payment_id if payment else None,
        "status": status,
        "starts_at": starts_at.isoformat() if starts_at else None,
        "expires_at": expires_at.isoformat() if expires_at else None,
    }


@router.post("/register")
def register(
    payload: RegisterRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    if not payload.personal_consent:
        raise HTTPException(status_code=400, detail="missing_personal_consent")
    if not payload.offer_consent:
        raise HTTPException(status_code=400, detail="missing_offer_consent")

    tenant_id = normalize_tenant_id(payload.tenant_id)
    region = normalize_region(payload.region)
    normalized_email = normalize_email(str(payload.email))
    existing = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.region == region,
            User.email_normalized == normalized_email,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="email_already_registered")

    user = User(
        tenant_id=tenant_id,
        region=region,
        email=str(payload.email),
        email_normalized=normalized_email,
        password_hash=hash_password(payload.password),
        email_verified_at=utc_now(),
        status="active",
        last_login_at=utc_now(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token, token_hash, expires_at = make_session_token()
    session = AuthSession(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    db.commit()

    return {
        "status": "registered",
        "token": token,
        "user": present_user(user),
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    tenant_id = normalize_tenant_id(payload.tenant_id)
    region = normalize_region(payload.region)
    normalized_email = normalize_email(str(payload.email))
    user = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.region == region,
            User.email_normalized == normalized_email,
        )
        .first()
    )
    if user is None or user.password_hash is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    user.last_login_at = utc_now()
    db.add(user)
    token, token_hash, expires_at = make_session_token()
    session = AuthSession(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    db.commit()

    return {
        "status": "authenticated",
        "token": token,
        "user": present_user(user),
    }


@router.get("/session")
def get_session(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
    product: str | None = None,
):
    user, _ = current

    product_state = None
    if product:
        product_state = present_product_state(db, user=user, product_code=product)

    return {
        "authenticated": True,
        "user": present_user(user),
        "product_state": product_state,
    }


@router.get("/payment-status")
def get_payment_status(
    invoice_id: Annotated[str, Query(min_length=1)],
    email: Annotated[EmailStr, Query()],
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[str, Query()] = DEFAULT_TENANT_ID,
    region: Annotated[str, Query()] = DEFAULT_REGION,
):
    normalized_email = normalize_email(str(email))
    user = (
        db.query(User)
        .filter(
            User.tenant_id == normalize_tenant_id(tenant_id),
            User.region == normalize_region(region),
            User.email_normalized == normalized_email,
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=404, detail="payment_not_found")

    order = (
        db.query(Order)
        .filter(
            Order.user_id == user.id,
            Order.provider_invoice_id == invoice_id,
        )
        .first()
    )
    if order is None:
        raise HTTPException(status_code=404, detail="payment_not_found")
    payment = None
    payment_query = db.query(Payment).filter(Payment.order_id == order.id)
    if order.status == OrderStatus.CANCELED.value:
        payment = (
            payment_query.filter(
                Payment.status.in_(
                    (
                        PaymentStatus.SUCCEEDED.value,
                        PaymentStatus.PARTIALLY_REFUNDED.value,
                        PaymentStatus.REFUNDED.value,
                    )
                )
            )
            .order_by(Payment.captured_at.desc(), Payment.created_at.desc())
            .first()
        )
    payment = payment or payment_query.order_by(Payment.created_at.desc()).first()

    order_item = get_order_item(db, order.id)
    product_code = order_item.product_code_snapshot if order_item else None
    if product_code is None and order_item is not None and order_item.product_id is not None:
        product = get_product_by_id(db, order_item.product_id)
        product_code = product.code if product is not None else None
    elif product_code is None and order_item is not None and order_item.bundle_id is not None:
        bundle = get_bundle_by_id(db, order_item.bundle_id)
        product_code = bundle.code if bundle is not None else None
    elif (
        product_code is None
        and order_item is not None
        and order_item.item_type == f"{SubscriptionScopeType.ALL_ACCESS.value}_plan"
    ):
        product_code = "all-access"
    if product_code is None:
        raise HTTPException(status_code=404, detail="payment_not_found")

    return {
        "tenant_id": user.tenant_id,
        "region": user.region,
        "user_id": str(user.id),
        "email": normalized_email,
        "product_state": present_product_state(
            db,
            user=user,
            product_code=product_code,
            order=order,
            payment=payment,
        ),
        "order": {
            "order_id": str(order.id),
            "order_number": order.order_number,
            "status": order.status,
            "amount_minor": order.amount_minor,
            "currency": order.currency,
            "paid_at": order.paid_at.isoformat() if order.paid_at else None,
            "failed_at": order.failed_at.isoformat() if order.failed_at else None,
        },
        "payment": {
            "payment_id": str(payment.id),
            "status": payment.status,
            "provider_payment_id": payment.provider_payment_id,
            "amount_minor": payment.amount_minor,
            "currency": payment.currency,
            "captured_at": payment.captured_at.isoformat() if payment.captured_at else None,
            "failed_at": payment.failed_at.isoformat() if payment.failed_at else None,
            "refunded_amount_minor": payment.refunded_amount_minor,
        }
        if payment is not None
        else None,
    }


@router.post("/logout")
def logout(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
):
    _, session = current
    db.delete(session)
    db.commit()
    return {"status": "logged_out"}


@router.post("/checkout-intent")
@traced("billing.checkout_intent.create")
def create_checkout_intent(
    payload: CheckoutIntentRequest,
    request: Request,
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
    providers: Annotated[PaymentProviderRegistry, Depends(get_payment_provider_registry)],
):
    user, _ = current
    sellable_plan = get_sellable_plan(
        db,
        user=user,
        entrypoint_code=payload.product,
        plan_code=payload.plan_code,
    )
    now = utc_now()
    if payload.auto_renew and sellable_plan["renewal_mode"] != SubscriptionRenewalMode.AUTOMATIC.value:
        raise HTTPException(
            status_code=409,
            detail={"code": "automatic_renewal_not_permitted"},
        )
    missing_documents = get_missing_required_documents_for_user(
        db,
        user=user,
        now=now,
        require_recurring_consent=payload.auto_renew,
    )
    if missing_documents:
        record_checkout("missing_required_documents")
        raise HTTPException(
            status_code=409,
            detail={
                "code": "missing_required_documents",
                "documents": [present_required_document(document) for document in missing_documents],
            },
        )

    recurring_consent = None
    if payload.auto_renew and payload.recurring_consent_acceptance_id is None:
        raise HTTPException(status_code=409, detail={"code": "recurring_consent_required"})
    if payload.auto_renew:
        recurring_consent = get_current_recurring_consent_acceptance(
            db,
            acceptance_id=payload.recurring_consent_acceptance_id,
            user=user,
            entrypoint_type=payload.entrypoint_type,
            entrypoint_value=sellable_plan["entrypoint_value"],
            plan_code=sellable_plan["plan_code"],
            now=now,
        )
        if recurring_consent is None:
            raise HTTPException(status_code=409, detail={"code": "recurring_consent_invalid"})

    provider_account, provider_adapter = get_or_create_checkout_provider_account(
        db,
        user=user,
        registry=providers,
    )
    invoice_id = make_invoice_id(sellable_plan["entrypoint_value"])
    amount_minor = int(sellable_plan["amount_minor"])
    currency = str(sellable_plan["currency"])
    if currency != provider_account.default_currency:
        record_checkout("provider_currency_mismatch")
        raise HTTPException(status_code=409, detail="provider_currency_mismatch")
    expires_at = now + timedelta(minutes=30)

    entrypoint_session = EntrypointSession(
        tenant_id=user.tenant_id,
        route_region=user.region,
        resolved_region=user.region,
        entrypoint_type=payload.entrypoint_type,
        entrypoint_value=sellable_plan["entrypoint_value"],
        product_id=sellable_plan["product_id"],
        bundle_id=sellable_plan["bundle_id"],
        frontend_id=payload.frontend_id or "web_checkout",
        user_id=user.id,
        source_url=payload.source_url,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_={"plan_code": payload.plan_code, "auto_renew": payload.auto_renew},
    )
    db.add(entrypoint_session)
    db.flush()

    checkout_session = CheckoutSession(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        entrypoint_session_id=entrypoint_session.id,
        plan_id=sellable_plan["plan_id"],
        status="order_created",
        amount_minor=amount_minor,
        currency=currency,
        expires_at=expires_at,
        metadata_={
            "product_code": payload.product,
            "plan_code": sellable_plan["plan_code"],
            "scope_type": sellable_plan["scope_type"],
            "auto_renew": payload.auto_renew,
            "recurring_consent_acceptance_id": str(recurring_consent.id) if recurring_consent else None,
        },
    )
    db.add(checkout_session)
    db.flush()

    order = Order(
        tenant_id=user.tenant_id,
        region=user.region,
        order_number=make_order_number(user.region),
        user_id=user.id,
        checkout_session_id=checkout_session.id,
        entrypoint_session_id=entrypoint_session.id,
        plan_id=sellable_plan["plan_id"],
        status="pending_payment",
        amount_minor=amount_minor,
        currency=currency,
        provider=provider_account.provider,
        provider_account_id=provider_account.id,
        merchant_order_id=invoice_id,
        provider_invoice_id=invoice_id,
        expires_at=expires_at,
        metadata_={
            "product_code": payload.product,
            "plan_code": sellable_plan["plan_code"],
            "scope_type": sellable_plan["scope_type"],
            "auto_renew": payload.auto_renew,
            "recurring_consent_acceptance_id": str(recurring_consent.id) if recurring_consent else None,
        },
    )
    db.add(order)
    db.flush()
    try:
        checkout_action = provider_adapter.prepare_checkout_action(
            provider_account=provider_account,
            order=order,
            account_id=user.email,
            description=str(sellable_plan["plan_name"]),
            metadata={
                "product_code": payload.product,
                "plan_code": sellable_plan["plan_code"],
            },
        )
        order.metadata_ = {
            **order.metadata_,
            "payment_mode": checkout_action.mode,
        }
        db.add(order)
    except PaymentProviderConfigurationError as exc:
        db.rollback()
        record_checkout("provider_configuration_error")
        raise HTTPException(status_code=409, detail=exc.code) from exc
    db.add(
        OrderItem(
            order_id=order.id,
            item_type=f"{sellable_plan['scope_type']}_plan",
            product_id=sellable_plan["product_id"],
            bundle_id=sellable_plan["bundle_id"],
            plan_id=sellable_plan["plan_id"],
            product_code_snapshot=payload.product if sellable_plan["scope_type"] == "product" else None,
            plan_code_snapshot=sellable_plan["plan_code"],
            title_snapshot=str(sellable_plan["plan_name"]),
            quantity=1,
            list_amount_minor=amount_minor,
            discount_amount_minor=0,
            unit_amount_minor=amount_minor,
            amount_minor=amount_minor,
            currency=currency,
            trial_days_snapshot=int(sellable_plan["trial_days"]),
            pricing_snapshot=sellable_plan["pricing_snapshot"],
        )
    )

    db.commit()
    record_checkout("created")

    return {
        "status": ProductAccessStatus.PENDING.value,
        "product_state": present_product_state(db, user=user, product_code=payload.product, order=order),
        "checkout": {
            "amount_minor": amount_minor,
            "amount": round(amount_minor / 100, 2),
            "currency": currency,
            "action": checkout_action.as_response(),
        },
    }
