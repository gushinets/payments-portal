from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import record_checkout, traced
from app.core.time import utc_now
from app.domains.identity.errors import (
    AutomaticRenewalNotPermittedError,
    MissingRequiredDocumentsError,
    ProviderCurrencyMismatchError,
)
from app.domains.identity.services.auth import (
    AuthenticationResult,
    login_user,
    logout_session,
    normalize_email as normalize_email,
    register_user,
)
from app.domains.identity.services.account import (
    ProductStateResult,
    load_account_session,
    load_payment_status,
)
from app.domains.identity.services.checkout import (
    CheckoutIntentRequest,
    CheckoutIntentResponse,
    CheckoutPaymentResponse,
    CheckoutPurchaseResponse,
    get_sellable_plan,
    make_invoice_id,
    make_order_number,
    raise_missing_recurring_consent,
)
from app.domains.identity.session import DEFAULT_REGION, DEFAULT_TENANT_ID
from app.domains.legal.service import (
    get_current_recurring_consent_acceptance,
    get_missing_required_documents_for_user,
    present_required_document,
)
from app.http_dependencies import get_current_session, get_payment_provider_registry
from app.models import (
    AuthSession,
    CheckoutSession,
    CheckoutSessionStatus,
    EntrypointSession,
    Order,
    OrderItem,
    OrderItemType,
    OrderStatus,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    User,
)
from app.payment_providers.accounts import get_or_create_checkout_provider_account
from app.payment_providers.errors import PaymentProviderConfigurationError
from app.payment_providers.registry import PaymentProviderRegistry

router = APIRouter(prefix="/api/auth", tags=["auth"])
logger = logging.getLogger(__name__)


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


def present_user(result: AuthenticationResult) -> dict:
    return {
        "tenant_id": result.tenant_id,
        "region": result.region,
        "user_id": str(result.user_id),
        "email": result.email,
    }


def present_product_state(
    result: ProductStateResult,
) -> dict:
    return {
        "product_code": result.product_code,
        "plan_code": result.plan_code,
        "plan_name": result.plan_name,
        "invoice_id": result.invoice_id,
        "transaction_id": result.transaction_id,
        "status": result.status.value,
        "starts_at": result.starts_at.isoformat() if result.starts_at else None,
        "expires_at": result.expires_at.isoformat() if result.expires_at else None,
    }


@router.post("/register")
def register(
    payload: RegisterRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    result = register_user(
        db,
        tenant_id=payload.tenant_id,
        region=payload.region,
        email=str(payload.email),
        password=payload.password,
        personal_consent=payload.personal_consent,
        offer_consent=payload.offer_consent,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return {
        "status": "registered",
        "token": result.token,
        "user": present_user(result),
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
):
    result = login_user(
        db,
        tenant_id=payload.tenant_id,
        region=payload.region,
        email=str(payload.email),
        password=payload.password,
        client_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return {
        "status": "authenticated",
        "token": result.token,
        "user": present_user(result),
    }


@router.get("/session")
def get_session(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
    product: str | None = None,
):
    user, _ = current
    result = load_account_session(db, user=user, product_code=product)

    return {
        "authenticated": True,
        "user": {
            "tenant_id": result.tenant_id,
            "region": result.region,
            "user_id": str(result.user_id),
            "email": result.email,
        },
        "product_state": present_product_state(result.product_state) if result.product_state else None,
    }


@router.get("/payment-status")
def get_payment_status(
    invoice_id: Annotated[str, Query(min_length=1)],
    email: Annotated[EmailStr, Query()],
    db: Annotated[Session, Depends(get_db)],
    tenant_id: Annotated[str, Query()] = DEFAULT_TENANT_ID,
    region: Annotated[str, Query()] = DEFAULT_REGION,
):
    result = load_payment_status(
        db,
        invoice_id=invoice_id,
        email=str(email),
        tenant_id=tenant_id,
        region=region,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="payment_not_found")

    return {
        "tenant_id": result.tenant_id,
        "region": result.region,
        "user_id": str(result.user_id),
        "email": result.email,
        "product_state": present_product_state(result.product_state),
        "order": {
            "order_id": str(result.order.order_id),
            "order_number": result.order.order_number,
            "status": result.order.status,
            "amount_minor": result.order.amount_minor,
            "currency": result.order.currency,
            "paid_at": result.order.paid_at.isoformat() if result.order.paid_at else None,
            "failed_at": result.order.failed_at.isoformat() if result.order.failed_at else None,
        },
        "payment": {
            "payment_id": str(result.payment.payment_id),
            "status": result.payment.status,
            "provider_payment_id": result.payment.provider_payment_id,
            "amount_minor": result.payment.amount_minor,
            "currency": result.payment.currency,
            "captured_at": result.payment.captured_at.isoformat() if result.payment.captured_at else None,
            "failed_at": result.payment.failed_at.isoformat() if result.payment.failed_at else None,
            "refunded_amount_minor": result.payment.refunded_amount_minor,
        }
        if result.payment is not None
        else None,
    }


@router.post("/logout")
def logout(
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
):
    _, session = current
    logout_session(db, auth_session=session)
    return {"status": "logged_out"}


@router.post("/checkout-intent", response_model=CheckoutIntentResponse)
@traced("billing.checkout_intent.create")
def create_checkout_intent(
    payload: CheckoutIntentRequest,
    request: Request,
    current: Annotated[tuple[User, AuthSession], Depends(get_current_session)],
    db: Annotated[Session, Depends(get_db)],
    providers: Annotated[PaymentProviderRegistry, Depends(get_payment_provider_registry)],
):
    user, _ = current
    now = utc_now()
    sellable_plan = get_sellable_plan(
        db,
        user=user,
        plan_id=payload.plan_id,
        now=now,
    )
    if payload.auto_renew and sellable_plan.renewal_mode != SubscriptionRenewalMode.AUTOMATIC:
        raise AutomaticRenewalNotPermittedError()
    missing_documents = get_missing_required_documents_for_user(
        db,
        user=user,
        now=now,
        require_recurring_consent=payload.auto_renew,
    )
    if missing_documents:
        record_checkout("missing_required_documents")
        raise MissingRequiredDocumentsError([present_required_document(document) for document in missing_documents])

    recurring_consent = None
    if payload.auto_renew and payload.recurring_consent_acceptance_id is None:
        raise_missing_recurring_consent(db, user=user, now=now)
    if payload.auto_renew:
        recurring_consent = get_current_recurring_consent_acceptance(
            db,
            acceptance_id=payload.recurring_consent_acceptance_id,
            user=user,
            entrypoint_type=payload.entrypoint_type,
            entrypoint_value=payload.entrypoint_value,
            plan_id=sellable_plan.id,
            now=now,
        )
        if recurring_consent is None:
            raise_missing_recurring_consent(db, user=user, now=now)

    provider_account, provider_adapter = get_or_create_checkout_provider_account(
        db,
        user=user,
        registry=providers,
    )
    invoice_id = make_invoice_id()
    amount_minor = sellable_plan.price_amount_minor
    currency = sellable_plan.currency
    if currency != provider_account.default_currency:
        record_checkout("provider_currency_mismatch")
        raise ProviderCurrencyMismatchError()
    expires_at = now + timedelta(minutes=30)

    entrypoint_session = EntrypointSession(
        tenant_id=user.tenant_id,
        route_region=user.region,
        resolved_region=user.region,
        entrypoint_type=payload.entrypoint_type,
        entrypoint_value=payload.entrypoint_value,
        product_id=sellable_plan.product_id,
        bundle_id=sellable_plan.bundle_id,
        frontend_id=payload.frontend_id or "web_checkout",
        user_id=user.id,
        source_url=payload.source_url,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        metadata_={
            "plan_id": str(sellable_plan.id),
            "plan_code": sellable_plan.code,
            "scope_type": sellable_plan.scope_type.value,
            "auto_renew": payload.auto_renew,
        },
    )
    db.add(entrypoint_session)
    db.flush()

    checkout_session = CheckoutSession(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        entrypoint_session_id=entrypoint_session.id,
        plan_id=sellable_plan.id,
        status=CheckoutSessionStatus.ORDER_CREATED,
        amount_minor=amount_minor,
        currency=currency,
        expires_at=expires_at,
        metadata_={
            "plan_id": str(sellable_plan.id),
            "plan_code": sellable_plan.code,
            "scope_type": sellable_plan.scope_type.value,
            "product_code": sellable_plan.product_code,
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
        plan_id=sellable_plan.id,
        status=OrderStatus.PENDING_PAYMENT,
        amount_minor=amount_minor,
        currency=currency,
        provider=provider_account.provider,
        provider_account_id=provider_account.id,
        merchant_order_id=invoice_id,
        provider_invoice_id=invoice_id,
        expires_at=expires_at,
        metadata_={
            "plan_id": str(sellable_plan.id),
            "plan_code": sellable_plan.code,
            "scope_type": sellable_plan.scope_type.value,
            "product_code": sellable_plan.product_code,
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
            description=sellable_plan.name,
            metadata={
                "plan_id": str(sellable_plan.id),
                "plan_code": sellable_plan.code,
                "scope_type": sellable_plan.scope_type.value,
                "product_code": sellable_plan.product_code,
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
            item_type={
                SubscriptionScopeType.PRODUCT: OrderItemType.PRODUCT_PLAN,
                SubscriptionScopeType.BUNDLE: OrderItemType.BUNDLE_PLAN,
                SubscriptionScopeType.ALL_ACCESS: OrderItemType.ALL_ACCESS_PLAN,
            }[sellable_plan.scope_type],
            product_id=sellable_plan.product_id,
            bundle_id=sellable_plan.bundle_id,
            plan_id=sellable_plan.id,
            product_code_snapshot=sellable_plan.product_code,
            plan_code_snapshot=sellable_plan.code,
            title_snapshot=sellable_plan.name,
            quantity=1,
            list_amount_minor=amount_minor,
            discount_amount_minor=0,
            unit_amount_minor=amount_minor,
            amount_minor=amount_minor,
            currency=currency,
            trial_days_snapshot=sellable_plan.trial_days,
            pricing_snapshot=sellable_plan.pricing_snapshot,
        )
    )

    order_id = str(order.id)
    db.commit()
    logger.info("billing_checkout_committed", extra={"structured": {"order_id": order_id}})
    record_checkout("created")

    return CheckoutIntentResponse(
        purchase=CheckoutPurchaseResponse(
            order_id=order.id,
            plan_id=sellable_plan.id,
            plan_code=sellable_plan.code,
            plan_name=sellable_plan.name,
            scope_type=sellable_plan.scope_type,
            product_id=sellable_plan.product_id,
            bundle_id=sellable_plan.bundle_id,
            invoice_id=invoice_id,
        ),
        checkout=CheckoutPaymentResponse(
            amount_minor=amount_minor,
            amount=float(Decimal(amount_minor) / Decimal(100)),
            currency=currency,
            action=checkout_action,
        ),
    )
