from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.observability import traced
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
    CheckoutCommand,
    create_checkout,
)
from app.domains.identity.session import DEFAULT_REGION, DEFAULT_TENANT_ID
from app.http_dependencies import get_current_session, get_payment_provider_registry
from app.models import (
    AuthSession,
    SubscriptionScopeType,
    User,
)
from app.payment_providers.contracts import CheckoutAction
from app.payment_providers.errors import (
    PaymentProviderConfigurationError,
    PaymentProviderUnavailableError,
)
from app.payment_providers.registry import PaymentProviderRegistry

router = APIRouter(prefix="/api/auth", tags=["auth"])


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
    model_config = ConfigDict(extra="forbid")

    plan_id: uuid.UUID
    auto_renew: bool = False
    recurring_consent_acceptance_id: uuid.UUID | None = None
    entrypoint_type: str
    entrypoint_value: str
    frontend_id: str | None = None
    source_url: str | None = None


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
) -> CheckoutIntentResponse:
    user, _ = current
    try:
        result = create_checkout(
            db,
            user=user,
            providers=providers,
            command=CheckoutCommand(
                plan_id=payload.plan_id,
                auto_renew=payload.auto_renew,
                recurring_consent_acceptance_id=payload.recurring_consent_acceptance_id,
                entrypoint_type=payload.entrypoint_type,
                entrypoint_value=payload.entrypoint_value,
                frontend_id=payload.frontend_id,
                source_url=payload.source_url,
                client_ip=request.client.host if request.client else None,
                user_agent=request.headers.get("user-agent"),
            ),
        )
    except PaymentProviderConfigurationError as exc:
        raise HTTPException(status_code=409, detail=exc.code) from exc
    except PaymentProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail=exc.code) from exc

    return CheckoutIntentResponse(
        purchase=CheckoutPurchaseResponse(
            order_id=result.order_id,
            plan_id=result.plan_id,
            plan_code=result.plan_code,
            plan_name=result.plan_name,
            scope_type=result.scope_type,
            product_id=result.product_id,
            bundle_id=result.bundle_id,
            invoice_id=result.invoice_id,
        ),
        checkout=CheckoutPaymentResponse(
            amount_minor=result.amount_minor,
            amount=float(Decimal(result.amount_minor) / Decimal(100)),
            currency=result.currency,
            action=result.action,
        ),
    )
