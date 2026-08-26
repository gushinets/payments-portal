"""Private helpers for provider-neutral lifecycle operations."""

from __future__ import annotations

import calendar
from contextlib import contextmanager
from functools import wraps
import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.domains.billing.enums import (
    BillingPeriod,
    OrderStatus,
    PaymentStatus,
    SubscriptionEventType,
    SubscriptionRenewalMode,
    SubscriptionScopeType,
    SubscriptionStatus,
    SensitiveMetadataKey,
    WebhookEventStatus,
)
from app.domains.billing.service.commands import ApplyRenewalPaymentCommand, LifecycleCommand
from app.domains.billing.service.state_machine import SubscriptionLifecycleError
from app.infrastructure.queries.orders import get_order_by_id, get_order_item_with_plan
from app.infrastructure.queries.payments import get_payment_by_id
from app.infrastructure.queries.plans import get_plan_by_id
from app.infrastructure.queries.subscriptions import (
    get_current_entitlement,
    get_subscription_event_by_operation_key,
    get_subscription_for_event,
    list_active_or_future_entitlements_for_subscription,
)
from app.infrastructure.queries.webhooks import get_processed_webhook_event
from app.models import Entitlement, Order, Payment, PaymentWebhookEvent, Plan, Subscription, SubscriptionEvent


@contextmanager
def _transaction(db: Session):
    if db.in_transaction():
        yield
    else:
        with db.begin():
            yield


def _transactional(function):
    @wraps(function)
    def wrapped(db: Session, *args, **kwargs):
        opened_transaction = not db.in_transaction()
        with _transaction(db):
            result = function(db, *args, **kwargs)
        if opened_transaction and isinstance(result, Subscription):
            db.refresh(result)
        return result

    return wrapped


def _event_for_key(db: Session, key: str) -> SubscriptionEvent | None:
    return get_subscription_event_by_operation_key(db, key)


def _subscription_for_event(db: Session, event: SubscriptionEvent) -> Subscription:
    subscription = get_subscription_for_event(db, event)
    if subscription is None:
        raise SubscriptionLifecycleError("subscription_missing_for_existing_event")
    return subscription


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    forbidden = tuple(key.value for key in SensitiveMetadataKey)

    def clean(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                str(key): clean(item)
                for key, item in value.items()
                if not any(word in str(key).lower() for word in forbidden)
            }
        if isinstance(value, list):
            return [clean(item) for item in value]
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        return str(value)

    return clean(metadata)


def _write_event(
    db: Session,
    *,
    subscription: Subscription,
    command: LifecycleCommand,
    event_type: SubscriptionEventType,
    previous_status: str | None,
    next_status: str | None,
    order_id: uuid.UUID | None = None,
    payment_id: uuid.UUID | None = None,
    refund_id: uuid.UUID | None = None,
    webhook_event_id: uuid.UUID | None = None,
) -> SubscriptionEvent:
    event = SubscriptionEvent(
        subscription_id=subscription.id,
        event_type=event_type.value,
        previous_status=previous_status,
        next_status=next_status,
        occurred_at=command.occurred_at,
        operation_idempotency_key=command.operation_idempotency_key,
        order_id=order_id,
        payment_id=payment_id,
        refund_id=refund_id,
        webhook_event_id=webhook_event_id,
        metadata_=_safe_metadata(command.metadata),
    )
    db.add(event)
    db.flush()
    return event


def _scope_matches(left: Subscription, right: Plan) -> bool:
    return (
        left.scope_type == right.scope_type
        and left.product_id == right.product_id
        and left.bundle_id == right.bundle_id
    )


def _period_end(start: datetime, plan: Plan) -> datetime:
    period = plan.billing_period.strip().lower()
    if period in {BillingPeriod.DAY.value, BillingPeriod.DAYS.value}:
        return start + timedelta(days=1)
    if period in {BillingPeriod.WEEK.value, BillingPeriod.WEEKS.value}:
        return start + timedelta(weeks=1)
    if period in {
        BillingPeriod.YEAR.value,
        BillingPeriod.YEARS.value,
        BillingPeriod.ANNUAL.value,
        BillingPeriod.YEARLY.value,
    }:
        months = 12
    elif period in {BillingPeriod.MONTH.value, BillingPeriod.MONTHS.value}:
        months = 1
    else:
        raise SubscriptionLifecycleError("unsupported_billing_period")

    month_index = start.month - 1 + months
    year = start.year + month_index // 12
    month = month_index % 12 + 1
    return start.replace(year=year, month=month, day=min(start.day, calendar.monthrange(year, month)[1]))


def _scope_values(plan: Plan) -> tuple[str, uuid.UUID | None, uuid.UUID | None]:
    if plan.scope_type not in {scope.value for scope in SubscriptionScopeType}:
        raise SubscriptionLifecycleError("invalid_plan_scope")
    return plan.scope_type, plan.product_id, plan.bundle_id


def _new_subscription(*, tenant_id: str, region: str, user_id: uuid.UUID, plan: Plan, start: datetime) -> Subscription:
    scope_type, product_id, bundle_id = _scope_values(plan)
    return Subscription(
        tenant_id=tenant_id,
        region=region,
        user_id=user_id,
        plan_id=plan.id,
        scope_type=scope_type,
        product_id=product_id,
        bundle_id=bundle_id,
        status=SubscriptionStatus.ACTIVE.value,
        renewal_mode=SubscriptionRenewalMode.MANUAL.value,
        current_period_start=start,
        current_period_end=_period_end(start, plan),
    )


def _current_entitlement(db: Session, subscription: Subscription, *, now: datetime) -> Entitlement | None:
    return get_current_entitlement(db, subscription.id, now=now, for_update=True)


def _active_or_future_entitlements(db: Session, subscription: Subscription, *, now: datetime) -> list[Entitlement]:
    return list_active_or_future_entitlements_for_subscription(db, subscription.id, now=now, for_update=True)


def _verify_order_payment_webhook(
    db: Session,
    *,
    order_id: uuid.UUID,
    payment_id: uuid.UUID,
    webhook_event_id: uuid.UUID,
) -> tuple[Order, Payment, PaymentWebhookEvent]:
    order = get_order_by_id(db, order_id, for_update=True)
    payment = get_payment_by_id(db, payment_id, for_update=True)
    if order is None or payment is None or payment.order_id != order.id:
        raise SubscriptionLifecycleError("payment_context_missing")
    webhook = get_processed_webhook_event(db, webhook_event_id)
    if (
        webhook is None
        or webhook.status != WebhookEventStatus.PROCESSED.value
        or webhook.order_id != order.id
        or webhook.payment_id != payment.id
    ):
        raise SubscriptionLifecycleError("verified_webhook_missing")
    if payment.tenant_id != order.tenant_id or payment.region != order.region:
        raise SubscriptionLifecycleError("payment_scope_mismatch")
    if payment.provider_account_id != order.provider_account_id or payment.provider != order.provider:
        raise SubscriptionLifecycleError("payment_provider_context_mismatch")
    if webhook.provider_account_id is not None and webhook.provider_account_id != order.provider_account_id:
        raise SubscriptionLifecycleError("webhook_provider_context_mismatch")
    return order, payment, webhook


def _verify_successful_payment_context(
    db: Session,
    *,
    order_id: uuid.UUID,
    payment_id: uuid.UUID,
    webhook_event_id: uuid.UUID,
) -> tuple[Order, Payment, PaymentWebhookEvent]:
    order, payment, webhook = _verify_order_payment_webhook(
        db,
        order_id=order_id,
        payment_id=payment_id,
        webhook_event_id=webhook_event_id,
    )
    if order.status != OrderStatus.PAID.value or payment.status != PaymentStatus.SUCCEEDED.value:
        raise SubscriptionLifecycleError("payment_not_verified")
    return order, payment, webhook


def _verify_renewal_context(
    db: Session,
    *,
    subscription: Subscription,
    command: ApplyRenewalPaymentCommand,
) -> tuple[Order, Payment, PaymentWebhookEvent]:
    order, payment, webhook = _verify_order_payment_webhook(
        db,
        order_id=command.order_id,
        payment_id=command.payment_id,
        webhook_event_id=command.webhook_event_id,
    )
    if (
        order.tenant_id != subscription.tenant_id
        or order.region != subscription.region
        or order.user_id != subscription.user_id
    ):
        raise SubscriptionLifecycleError("renewal_order_scope_mismatch")
    if subscription.provider_account_id is not None and order.provider_account_id != subscription.provider_account_id:
        raise SubscriptionLifecycleError("renewal_provider_context_mismatch")
    if command.succeeded:
        if order.status != OrderStatus.PAID.value or payment.status != PaymentStatus.SUCCEEDED.value:
            raise SubscriptionLifecycleError("renewal_payment_not_verified")
    elif order.status not in {OrderStatus.PAYMENT_FAILED.value, OrderStatus.CANCELED.value} or payment.status not in {
        PaymentStatus.FAILED.value,
        PaymentStatus.CANCELED.value,
    }:
        raise SubscriptionLifecycleError("renewal_failure_not_verified")
    return order, payment, webhook


def _find_plan_for_order(db: Session, order: Order) -> Plan:
    plan_id = order.plan_id
    if plan_id is None:
        item = get_order_item_with_plan(db, order.id)
        plan_id = item.plan_id if item else None
    plan = get_plan_by_id(db, plan_id, for_update=True) if plan_id else None
    if plan is None:
        raise SubscriptionLifecycleError("order_plan_missing")
    return plan
