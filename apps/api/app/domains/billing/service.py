"""Provider-neutral subscription and entitlement lifecycle."""

from __future__ import annotations

import calendar
from contextlib import contextmanager
from functools import wraps
import uuid
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy.orm import Session

from app.domains.billing.enums import (
    BillingPeriod,
    EntitlementSource,
    EntitlementStatus,
    OrderStatus,
    PaymentStatus,
    ProviderSubscriptionState,
    SubscriptionRenewalMode,
    SubscriptionEventType,
    SubscriptionScopeType,
    SubscriptionStatus,
    SensitiveMetadataKey,
    WebhookEventStatus,
)
from app.models import (
    Entitlement,
    Order,
    Plan,
    Subscription,
    SubscriptionEvent,
)
from app.core.time import utc_now
from app.infrastructure.queries.legal import get_document_acceptance_by_id
from app.infrastructure.queries.identity import lock_user_by_id
from app.infrastructure.queries.orders import get_order_by_id, get_order_item_with_plan
from app.infrastructure.queries.payments import (
    get_payment_by_id,
    get_payment_for_refund,
    get_provider_account_by_id,
    get_refund_by_id,
)
from app.infrastructure.queries.plans import get_plan_by_id
from app.infrastructure.queries.subscriptions import (
    get_active_entitlement,
    get_subscription_by_id,
    get_subscription_event_by_operation_key,
    get_subscription_for_event,
    get_subscription_for_order,
    get_trial_for_scope,
    list_active_subscriptions_for_user,
    list_due_subscriptions,
)
from app.infrastructure.queries.webhooks import get_processed_webhook_event


class LifecycleCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation_idempotency_key: str = Field(min_length=1, max_length=255)
    occurred_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def normalize_occurrence(self) -> "LifecycleCommand":
        if self.occurred_at is None:
            self.occurred_at = utc_now()
        elif self.occurred_at.tzinfo is None:
            raise ValueError("occurred_at_must_be_timezone_aware")
        return self


class StartTrialCommand(LifecycleCommand):
    tenant_id: str
    region: str
    user_id: uuid.UUID
    plan_id: uuid.UUID


class ActivatePaidPeriodCommand(LifecycleCommand):
    order_id: uuid.UUID
    payment_id: uuid.UUID
    webhook_event_id: uuid.UUID


class EnableAutomaticRenewalCommand(LifecycleCommand):
    subscription_id: uuid.UUID
    provider_account_id: uuid.UUID
    provider_subscription_id: str = Field(min_length=1, max_length=255)
    recurring_consent_acceptance_id: uuid.UUID


class ApplyRenewalPaymentCommand(LifecycleCommand):
    subscription_id: uuid.UUID
    succeeded: bool
    payment_id: uuid.UUID | None = None
    webhook_event_id: uuid.UUID | None = None
    paid_at: datetime | None = None

    @field_validator("paid_at")
    @classmethod
    def require_aware_paid_at(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("paid_at_must_be_timezone_aware")
        return value


class ApplyProviderSubscriptionStateCommand(LifecycleCommand):
    subscription_id: uuid.UUID
    provider_state: ProviderSubscriptionState


class RequestCancellationCommand(LifecycleCommand):
    subscription_id: uuid.UUID


class ApplyRefundCommand(LifecycleCommand):
    order_id: uuid.UUID
    refund_id: uuid.UUID
    amount_minor: int = Field(gt=0)


class ExpireDueSubscriptionsCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    now: datetime | None = None
    batch_size: int = Field(default=100, gt=0, le=1000)

    @model_validator(mode="after")
    def normalize_now(self) -> "ExpireDueSubscriptionsCommand":
        if self.now is None:
            self.now = utc_now()
        elif self.now.tzinfo is None:
            raise ValueError("now_must_be_timezone_aware")
        return self


class SubscriptionLifecycleError(ValueError):
    """Raised when a lifecycle command cannot be applied safely."""


PROVIDER_SUBSCRIPTION_STATUS_MAP = {
    ProviderSubscriptionState.ACTIVE: SubscriptionStatus.ACTIVE,
    ProviderSubscriptionState.PAST_DUE: SubscriptionStatus.PAST_DUE,
    ProviderSubscriptionState.CANCELED: SubscriptionStatus.CANCELED,
    ProviderSubscriptionState.REJECTED: SubscriptionStatus.CANCELED,
    ProviderSubscriptionState.EXPIRED: SubscriptionStatus.CANCELED,
    ProviderSubscriptionState.PAUSED: SubscriptionStatus.PAUSED,
    ProviderSubscriptionState.ENDED: SubscriptionStatus.CANCELED,
}

SUBSCRIPTION_STATUS_TRANSITIONS = {
    SubscriptionStatus.TRIALING: frozenset(
        {SubscriptionStatus.ACTIVE, SubscriptionStatus.CANCELED, SubscriptionStatus.EXPIRED}
    ),
    SubscriptionStatus.ACTIVE: frozenset(
        {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.CANCELED,
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.REFUNDED,
            SubscriptionStatus.PAUSED,
        }
    ),
    SubscriptionStatus.PAST_DUE: frozenset(
        {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.CANCELED,
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.REFUNDED,
            SubscriptionStatus.PAUSED,
        }
    ),
    SubscriptionStatus.PAUSED: frozenset(
        {
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
            SubscriptionStatus.CANCELED,
            SubscriptionStatus.EXPIRED,
            SubscriptionStatus.REFUNDED,
            SubscriptionStatus.PAUSED,
        }
    ),
}


def subscription_status_from_provider_state(state: ProviderSubscriptionState) -> SubscriptionStatus:
    return PROVIDER_SUBSCRIPTION_STATUS_MAP[state]


def ensure_subscription_status_transition(current: str, next_status: SubscriptionStatus) -> None:
    try:
        current_status = SubscriptionStatus(current)
    except ValueError as exc:
        raise SubscriptionLifecycleError("invalid_current_subscription_status") from exc
    if next_status not in SUBSCRIPTION_STATUS_TRANSITIONS.get(current_status, frozenset()):
        raise SubscriptionLifecycleError("invalid_subscription_status_transition")


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
        with _transaction(db):
            return function(db, *args, **kwargs)

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


def _active_entitlement(db: Session, subscription: Subscription) -> Entitlement | None:
    return (
        get_active_entitlement(db, subscription.id, for_update=True)
    )


@_transactional
def start_trial(db: Session, command: StartTrialCommand) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)

    plan = get_plan_by_id(db, command.plan_id, for_update=True)
    if plan is None or plan.tenant_id != command.tenant_id or plan.region != command.region:
        raise SubscriptionLifecycleError("plan_not_found")
    user = lock_user_by_id(db, command.user_id)
    if user is None or user.tenant_id != command.tenant_id or user.region != command.region:
        raise SubscriptionLifecycleError("user_not_found")
    if plan.trial_days <= 0:
        raise SubscriptionLifecycleError("trial_not_available")

    existing_trial = get_trial_for_scope(
        db,
        tenant_id=command.tenant_id,
        region=command.region,
        user_id=command.user_id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
    )
    if existing_trial:
        raise SubscriptionLifecycleError("trial_already_used_for_scope")

    start = command.occurred_at
    scope_type, product_id, bundle_id = _scope_values(plan)
    subscription = Subscription(
        tenant_id=command.tenant_id,
        region=command.region,
        user_id=command.user_id,
        plan_id=plan.id,
        scope_type=scope_type,
        product_id=product_id,
        bundle_id=bundle_id,
        status=SubscriptionStatus.TRIALING.value,
        renewal_mode=SubscriptionRenewalMode.MANUAL.value,
        trial_start_at=start,
        trial_end_at=start + timedelta(days=plan.trial_days),
        current_period_start=start,
        current_period_end=start + timedelta(days=plan.trial_days),
    )
    db.add(subscription)
    db.flush()
    entitlement = Entitlement(
        tenant_id=command.tenant_id,
        region=command.region,
        user_id=command.user_id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=EntitlementStatus.ACTIVE.value,
        valid_from=start,
        valid_until=subscription.current_period_end,
        source=EntitlementSource.TRIAL.value,
    )
    db.add(entitlement)
    _write_event(
        db,
        subscription=subscription,
        command=command,
        event_type=SubscriptionEventType.TRIAL_STARTED,
        previous_status=None,
        next_status=subscription.status,
    )
    return subscription


def _find_plan_for_order(db: Session, order: Order) -> Plan:
    plan_id = order.plan_id
    if plan_id is None:
        item = get_order_item_with_plan(db, order.id)
        plan_id = item.plan_id if item else None
    plan = get_plan_by_id(db, plan_id, for_update=True) if plan_id else None
    if plan is None:
        raise SubscriptionLifecycleError("order_plan_missing")
    return plan


@_transactional
def activate_paid_period(db: Session, command: ActivatePaidPeriodCommand) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)

    order = get_order_by_id(db, command.order_id, for_update=True)
    payment = get_payment_by_id(db, command.payment_id, for_update=True)
    if order is None or payment is None or payment.order_id != order.id:
        raise SubscriptionLifecycleError("payment_context_missing")
    webhook = get_processed_webhook_event(db, command.webhook_event_id)
    if (
        webhook is None
        or webhook.status != WebhookEventStatus.PROCESSED.value
        or webhook.order_id != order.id
        or webhook.payment_id != payment.id
    ):
        raise SubscriptionLifecycleError("verified_webhook_missing")
    if order.status != OrderStatus.PAID.value or payment.status != PaymentStatus.SUCCEEDED.value:
        raise SubscriptionLifecycleError("payment_not_verified")
    if payment.tenant_id != order.tenant_id or payment.region != order.region:
        raise SubscriptionLifecycleError("payment_scope_mismatch")

    plan = _find_plan_for_order(db, order)
    paid_at = order.paid_at or command.occurred_at
    candidates = list_active_subscriptions_for_user(
        db, tenant_id=order.tenant_id, region=order.region, user_id=order.user_id
    )
    subscription = next((item for item in candidates if item.plan_id == plan.id and _scope_matches(item, plan)), None)
    previous_status = subscription.status if subscription is not None else None
    previous_entitlement = None
    if subscription is None:
        previous = next((item for item in candidates if _scope_matches(item, plan)), None)
        subscription = _new_subscription(
            tenant_id=order.tenant_id,
            region=order.region,
            user_id=order.user_id,
            plan=plan,
            start=paid_at,
        )
        db.add(subscription)
        db.flush()
        if previous:
            ensure_subscription_status_transition(previous.status, SubscriptionStatus.CANCELED)
            previous.status = SubscriptionStatus.CANCELED.value
            previous.canceled_at = command.occurred_at
            previous_entitlement = _active_entitlement(db, previous)
            if previous_entitlement:
                previous_entitlement.status = EntitlementStatus.SUPERSEDED.value
                previous_entitlement.superseded_at = command.occurred_at
    else:
        ensure_subscription_status_transition(subscription.status, SubscriptionStatus.ACTIVE)
        start = paid_at if subscription.status == SubscriptionStatus.TRIALING.value else max(
            subscription.current_period_end, paid_at
        )
        subscription.current_period_start = start
        subscription.current_period_end = _period_end(start, plan)
        subscription.status = SubscriptionStatus.ACTIVE.value

    subscription.current_period_start = subscription.current_period_start or paid_at
    entitlement = _active_entitlement(db, subscription)
    if entitlement is None:
        entitlement = Entitlement(
            tenant_id=order.tenant_id,
            region=order.region,
            user_id=order.user_id,
            subscription_id=subscription.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=EntitlementStatus.ACTIVE.value,
            valid_from=paid_at,
            valid_until=subscription.current_period_end,
            source=EntitlementSource.ORDER.value,
            order_id=order.id,
        )
        db.add(entitlement)
    else:
        entitlement.plan_id = plan.id
        entitlement.valid_until = subscription.current_period_end
        entitlement.source = EntitlementSource.ORDER.value
        entitlement.order_id = order.id
    db.flush()
    if previous_entitlement is not None:
        previous_entitlement.superseded_by_entitlement_id = entitlement.id
    _write_event(
        db,
        subscription=subscription,
        command=command,
        event_type=SubscriptionEventType.PAID_PERIOD_ACTIVATED,
        previous_status=previous_status,
        next_status=subscription.status,
        order_id=order.id,
        payment_id=payment.id,
        webhook_event_id=command.webhook_event_id,
    )
    return subscription


@_transactional
def enable_automatic_renewal(db: Session, command: EnableAutomaticRenewalCommand) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)
    subscription = get_subscription_by_id(db, command.subscription_id, for_update=True)
    account = get_provider_account_by_id(db, command.provider_account_id, for_update=True)
    acceptance = get_document_acceptance_by_id(db, command.recurring_consent_acceptance_id, for_update=True)
    if subscription is None or account is None or acceptance is None:
        raise SubscriptionLifecycleError("automatic_renewal_context_missing")
    if subscription.renewal_mode == SubscriptionRenewalMode.AUTOMATIC.value:
        raise SubscriptionLifecycleError("automatic_renewal_already_enabled")
    if account.tenant_id != subscription.tenant_id or account.region != subscription.region:
        raise SubscriptionLifecycleError("provider_account_scope_mismatch")
    if acceptance.tenant_id != subscription.tenant_id or acceptance.region != subscription.region:
        raise SubscriptionLifecycleError("consent_scope_mismatch")
    if acceptance.user_id != subscription.user_id or acceptance.acceptance_kind != "recurring_consent":
        raise SubscriptionLifecycleError("recurring_consent_invalid")
    plan = get_plan_by_id(db, subscription.plan_id, for_update=True)
    if plan is None or plan.renewal_mode != SubscriptionRenewalMode.AUTOMATIC.value:
        raise SubscriptionLifecycleError("automatic_renewal_not_permitted")
    subscription.provider_account_id = account.id
    subscription.provider_subscription_id = command.provider_subscription_id
    subscription.recurring_consent_acceptance_id = acceptance.id
    subscription.renewal_mode = SubscriptionRenewalMode.AUTOMATIC.value
    _write_event(
        db,
        subscription=subscription,
        command=command,
        event_type=SubscriptionEventType.AUTOMATIC_RENEWAL_ENABLED,
        previous_status=subscription.status,
        next_status=subscription.status,
    )
    return subscription


@_transactional
def apply_renewal_payment(db: Session, command: ApplyRenewalPaymentCommand) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)
    subscription = get_subscription_by_id(db, command.subscription_id, for_update=True)
    if subscription is None:
        raise SubscriptionLifecycleError("subscription_not_found")
    previous = subscription.status
    if command.succeeded:
        ensure_subscription_status_transition(previous, SubscriptionStatus.ACTIVE)
        plan = get_plan_by_id(db, subscription.plan_id, for_update=True)
        if plan is None:
            raise SubscriptionLifecycleError("plan_not_found")
        paid_at = command.paid_at or command.occurred_at
        start = max(subscription.current_period_end, paid_at)
        subscription.current_period_start = start
        subscription.current_period_end = _period_end(start, plan)
        subscription.status = SubscriptionStatus.ACTIVE.value
        entitlement = _active_entitlement(db, subscription)
        if entitlement:
            entitlement.valid_until = subscription.current_period_end
        event_type = SubscriptionEventType.RENEWAL_SUCCEEDED
    else:
        ensure_subscription_status_transition(previous, SubscriptionStatus.PAST_DUE)
        subscription.status = SubscriptionStatus.PAST_DUE.value
        event_type = SubscriptionEventType.RENEWAL_FAILED
    _write_event(
        db,
        subscription=subscription,
        command=command,
        event_type=event_type,
        previous_status=previous,
        next_status=subscription.status,
        payment_id=command.payment_id,
        webhook_event_id=command.webhook_event_id,
    )
    return subscription


@_transactional
def apply_provider_subscription_state(
    db: Session, command: ApplyProviderSubscriptionStateCommand
) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)
    subscription = get_subscription_by_id(db, command.subscription_id, for_update=True)
    if subscription is None:
        raise SubscriptionLifecycleError("subscription_not_found")
    previous = subscription.status
    status = subscription_status_from_provider_state(command.provider_state)
    ensure_subscription_status_transition(previous, status)
    subscription.status = status.value
    if status == SubscriptionStatus.CANCELED:
        subscription.renewal_mode = SubscriptionRenewalMode.MANUAL.value
        subscription.canceled_at = subscription.canceled_at or command.occurred_at
    _write_event(
        db,
        subscription=subscription,
        command=command,
        event_type=SubscriptionEventType.PROVIDER_SUBSCRIPTION_STATE_APPLIED,
        previous_status=previous,
        next_status=status.value,
    )
    return subscription


@_transactional
def request_cancellation(db: Session, command: RequestCancellationCommand) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)
    subscription = get_subscription_by_id(db, command.subscription_id, for_update=True)
    if subscription is None:
        raise SubscriptionLifecycleError("subscription_not_found")
    if subscription.status not in {
        SubscriptionStatus.TRIALING.value,
        SubscriptionStatus.ACTIVE.value,
        SubscriptionStatus.PAST_DUE.value,
        SubscriptionStatus.PAUSED.value,
    }:
        raise SubscriptionLifecycleError("subscription_cannot_be_canceled")
    subscription.cancel_requested_at = command.occurred_at
    _write_event(
        db,
        subscription=subscription,
        command=command,
        event_type=SubscriptionEventType.CANCELLATION_REQUESTED,
        previous_status=subscription.status,
        next_status=subscription.status,
    )
    return subscription


@_transactional
def apply_refund(db: Session, command: ApplyRefundCommand) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)
    order = get_order_by_id(db, command.order_id, for_update=True)
    refund = get_refund_by_id(db, command.refund_id, for_update=True)
    if order is None or refund is None or refund.order_id != order.id:
        raise SubscriptionLifecycleError("refund_context_missing")
    subscription = get_subscription_for_order(db, order.id, for_update=True)
    if subscription is None:
        raise SubscriptionLifecycleError("subscription_not_found_for_order")
    payment = get_payment_for_refund(db, refund.payment_id)
    previous = subscription.status
    full_refund = payment is not None and payment.refunded_amount_minor >= payment.amount_minor
    if full_refund:
        ensure_subscription_status_transition(previous, SubscriptionStatus.REFUNDED)
        subscription.status = SubscriptionStatus.REFUNDED.value
        entitlement = _active_entitlement(db, subscription)
        if entitlement:
            entitlement.status = EntitlementStatus.REVOKED.value
            entitlement.revoked_at = command.occurred_at
    _write_event(
        db,
        subscription=subscription,
        command=command,
        event_type=(
            SubscriptionEventType.REFUND_APPLIED
            if full_refund
            else SubscriptionEventType.PARTIAL_REFUND_APPLIED
        ),
        previous_status=previous,
        next_status=subscription.status,
        order_id=order.id,
        refund_id=refund.id,
    )
    return subscription


@_transactional
def expire_due_subscriptions(db: Session, command: ExpireDueSubscriptionsCommand) -> list[Subscription]:
    subscriptions = list_due_subscriptions(db, now=command.now, batch_size=command.batch_size)
    for subscription in subscriptions:
        previous_status = subscription.status
        ensure_subscription_status_transition(previous_status, SubscriptionStatus.EXPIRED)
        subscription.status = SubscriptionStatus.EXPIRED.value
        entitlement = _active_entitlement(db, subscription)
        if entitlement:
            entitlement.status = EntitlementStatus.EXPIRED.value
            entitlement.expired_at = command.now
        event_key = f"subscription-expired:{subscription.id}:{subscription.current_period_end.isoformat()}"
        event = _event_for_key(db, event_key)
        if event is None:
            _write_event(
                db,
                subscription=subscription,
                command=LifecycleCommand(operation_idempotency_key=event_key, occurred_at=command.now),
                event_type=SubscriptionEventType.SUBSCRIPTION_EXPIRED,
                previous_status=previous_status,
                next_status=subscription.status,
            )
    db.flush()
    return subscriptions


__all__ = [
    "ApplyProviderSubscriptionStateCommand",
    "ApplyRefundCommand",
    "ApplyRenewalPaymentCommand",
    "ActivatePaidPeriodCommand",
    "EnableAutomaticRenewalCommand",
    "ExpireDueSubscriptionsCommand",
    "RequestCancellationCommand",
    "StartTrialCommand",
    "SubscriptionLifecycleError",
    "activate_paid_period",
    "apply_provider_subscription_state",
    "apply_refund",
    "apply_renewal_payment",
    "enable_automatic_renewal",
    "expire_due_subscriptions",
    "request_cancellation",
    "start_trial",
    "subscription_status_from_provider_state",
]
