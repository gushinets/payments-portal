from __future__ import annotations

import logging
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.core.observability import record_checkout
from app.core.time import utc_now
from app.domains.identity.errors import (
    AutomaticRenewalNotPermittedError,
    MissingRequiredDocumentsError,
    ProviderCurrencyMismatchError,
    RecurringConsentRequiredError,
    UnknownProductPlanError,
)
from app.domains.legal.service import (
    get_active_required_documents,
    get_current_recurring_consent_acceptance,
    get_missing_required_documents_for_user,
    present_required_document,
)
from app.infrastructure.queries.plans import get_current_sellable_plan
from app.infrastructure.queries.products import get_active_bundle_by_id, get_active_product_by_id
from app.models import (
    BillingPeriod,
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
from app.payment_providers.contracts import CheckoutAction
from app.payment_providers.errors import PaymentProviderConfigurationError
from app.payment_providers.registry import PaymentProviderRegistry


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CheckoutCommand:
    plan_id: uuid.UUID
    auto_renew: bool
    recurring_consent_acceptance_id: uuid.UUID | None
    entrypoint_type: str
    entrypoint_value: str
    frontend_id: str | None
    source_url: str | None
    client_ip: str | None
    user_agent: str | None


@dataclass(frozen=True)
class CheckoutResult:
    order_id: uuid.UUID
    plan_id: uuid.UUID
    plan_code: str
    plan_name: str
    scope_type: SubscriptionScopeType
    product_id: uuid.UUID | None
    bundle_id: uuid.UUID | None
    invoice_id: str
    amount_minor: int
    currency: str
    action: CheckoutAction


@dataclass(frozen=True)
class ResolvedCheckoutPlan:
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
    pricing_snapshot: dict[str, int | str | BillingPeriod]


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
        raise UnknownProductPlanError()

    scope_type = plan.scope_type

    product_code = None
    if scope_type is SubscriptionScopeType.PRODUCT:
        if plan.product_id is None or plan.bundle_id is not None:
            raise UnknownProductPlanError()
        product = get_active_product_by_id(
            db,
            product_id=plan.product_id,
            tenant_id=user.tenant_id,
        )
        if product is None:
            raise UnknownProductPlanError()
        product_code = product.code
    elif scope_type is SubscriptionScopeType.BUNDLE:
        if plan.product_id is not None or plan.bundle_id is None:
            raise UnknownProductPlanError()
        bundle = get_active_bundle_by_id(
            db,
            bundle_id=plan.bundle_id,
            tenant_id=user.tenant_id,
        )
        if bundle is None:
            raise UnknownProductPlanError()
    elif plan.product_id is not None or plan.bundle_id is not None:
        raise UnknownProductPlanError()

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
        raise MissingRequiredDocumentsError([present_required_document(document) for document in recurring_documents])
    raise RecurringConsentRequiredError()


def create_checkout(
    db: Session,
    *,
    user: User,
    providers: PaymentProviderRegistry,
    command: CheckoutCommand,
) -> CheckoutResult:
    now = utc_now()
    sellable_plan = get_sellable_plan(
        db,
        user=user,
        plan_id=command.plan_id,
        now=now,
    )
    if command.auto_renew and sellable_plan.renewal_mode != SubscriptionRenewalMode.AUTOMATIC:
        raise AutomaticRenewalNotPermittedError()
    missing_documents = get_missing_required_documents_for_user(
        db,
        user=user,
        now=now,
        require_recurring_consent=command.auto_renew,
    )
    if missing_documents:
        record_checkout("missing_required_documents")
        raise MissingRequiredDocumentsError([present_required_document(document) for document in missing_documents])

    recurring_consent = None
    if command.auto_renew:
        acceptance_id = command.recurring_consent_acceptance_id
        if acceptance_id is None:
            raise_missing_recurring_consent(db, user=user, now=now)
        else:
            recurring_consent = get_current_recurring_consent_acceptance(
                db,
                acceptance_id=acceptance_id,
                user=user,
                entrypoint_type=command.entrypoint_type,
                entrypoint_value=command.entrypoint_value,
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
        entrypoint_type=command.entrypoint_type,
        entrypoint_value=command.entrypoint_value,
        product_id=sellable_plan.product_id,
        bundle_id=sellable_plan.bundle_id,
        frontend_id=command.frontend_id or "web_checkout",
        user_id=user.id,
        source_url=command.source_url,
        ip=command.client_ip,
        user_agent=command.user_agent,
        metadata_={
            "plan_id": str(sellable_plan.id),
            "plan_code": sellable_plan.code,
            "scope_type": sellable_plan.scope_type.value,
            "auto_renew": command.auto_renew,
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
            "auto_renew": command.auto_renew,
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
            "auto_renew": command.auto_renew,
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
    except PaymentProviderConfigurationError:
        db.rollback()
        record_checkout("provider_configuration_error")
        raise
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

    result = CheckoutResult(
        order_id=order.id,
        plan_id=sellable_plan.id,
        plan_code=sellable_plan.code,
        plan_name=sellable_plan.name,
        scope_type=sellable_plan.scope_type,
        product_id=sellable_plan.product_id,
        bundle_id=sellable_plan.bundle_id,
        invoice_id=invoice_id,
        amount_minor=amount_minor,
        currency=currency,
        action=checkout_action,
    )
    db.commit()
    logger.info("billing_checkout_committed", extra={"structured": {"order_id": str(result.order_id)}})
    record_checkout("created")
    return result
