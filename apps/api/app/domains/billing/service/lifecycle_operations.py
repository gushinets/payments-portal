"""Additional provider-neutral subscription lifecycle operations."""

from __future__ import annotations

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Entitlement,
    EntitlementSource,
    EntitlementStatus,
    OrderStatus,
    RefundStatus,
    Subscription,
    SubscriptionEventType,
    SubscriptionRenewalMode,
    SubscriptionStatus,
)
from app.domains.billing.service.commands import (
    ApplyProviderSubscriptionStateCommand,
    ApplyRefundCommand,
    ApplyRenewalPaymentCommand,
    EnableAutomaticRenewalCommand,
    ExpireDueSubscriptionsCommand,
    LifecycleCommand,
    RequestCancellationCommand,
)
from app.domains.billing.service.state_machine import (
    SubscriptionLifecycleError,
    ensure_subscription_status_transition,
    subscription_status_from_provider_state,
)
from app.domains.billing.service.support import (
    _active_or_future_entitlements,
    _current_entitlement,
    _event_for_key,
    _find_plan_for_order,
    _period_end,
    _scope_matches,
    _subscription_for_event,
    _transactional,
    _verify_renewal_context,
    _write_event,
)
from app.domains.legal.service import (
    is_current_legacy_recurring_consent_acceptance,
    is_current_recurring_consent_acceptance,
)
from app.infrastructure.queries.identity import lock_user_by_id
from app.infrastructure.queries.legal import get_document_acceptance_by_id
from app.infrastructure.queries.orders import get_entrypoint_session_by_id, get_order_by_id, get_order_item_with_plan
from app.infrastructure.queries.payments import (
    get_payment_for_refund,
    get_provider_account_by_id,
    get_refund_by_id,
)
from app.infrastructure.queries.plans import get_plan_by_id
from app.infrastructure.queries.subscriptions import (
    get_subscription_by_id,
    get_subscription_for_order,
    list_due_entitlements_for_subscription,
    list_due_subscriptions,
    list_entitlements_for_order,
)

_PROVIDER_SUBSCRIPTION_REFERENCE_INDEX = "uq_subscriptions_provider_reference"


def _is_provider_subscription_reference_conflict(error: IntegrityError) -> bool:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    return constraint_name == _PROVIDER_SUBSCRIPTION_REFERENCE_INDEX


@_transactional
def enable_automatic_renewal(db: Session, command: EnableAutomaticRenewalCommand) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)
    subscription = get_subscription_by_id(db, command.subscription_id, for_update=True)
    if subscription is None:
        raise SubscriptionLifecycleError("automatic_renewal_context_missing")
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)
    order = get_order_by_id(db, command.order_id, for_update=True)
    account = get_provider_account_by_id(db, command.provider_account_id, for_update=True)
    acceptance = get_document_acceptance_by_id(db, command.recurring_consent_acceptance_id, for_update=True)
    if order is None or account is None or acceptance is None:
        raise SubscriptionLifecycleError("automatic_renewal_context_missing")
    if subscription.renewal_mode == SubscriptionRenewalMode.AUTOMATIC:
        raise SubscriptionLifecycleError("automatic_renewal_already_enabled")
    if account.tenant_id != subscription.tenant_id or account.region != subscription.region:
        raise SubscriptionLifecycleError("provider_account_scope_mismatch")
    if acceptance.tenant_id != subscription.tenant_id or acceptance.region != subscription.region:
        raise SubscriptionLifecycleError("consent_scope_mismatch")
    if acceptance.user_id != subscription.user_id or acceptance.acceptance_kind != "recurring_consent":
        raise SubscriptionLifecycleError("recurring_consent_invalid")
    plan = get_plan_by_id(db, subscription.plan_id, for_update=True)
    if plan is None or plan.renewal_mode != SubscriptionRenewalMode.AUTOMATIC:
        raise SubscriptionLifecycleError("automatic_renewal_not_permitted")
    user = lock_user_by_id(db, subscription.user_id)
    entrypoint_session = (
        get_entrypoint_session_by_id(db, order.entrypoint_session_id, for_update=True)
        if order.entrypoint_session_id is not None
        else None
    )
    linked_subscription = get_subscription_for_order(db, order.id)
    if (
        user is None
        or user.tenant_id != subscription.tenant_id
        or user.region != subscription.region
        or order.status != OrderStatus.PAID
        or order.tenant_id != subscription.tenant_id
        or order.region != subscription.region
        or order.user_id != subscription.user_id
        or order.plan_id != subscription.plan_id
        or order.provider_account_id != account.id
        or linked_subscription is None
        or linked_subscription.id != command.subscription_id
        or entrypoint_session is None
        or entrypoint_session.tenant_id != subscription.tenant_id
        or entrypoint_session.resolved_region != subscription.region
        or entrypoint_session.user_id != subscription.user_id
    ):
        raise SubscriptionLifecycleError("automatic_renewal_context_missing")
    metadata = order.metadata_
    if (
        not isinstance(metadata, dict)
        or metadata.get("auto_renew") is not True
        or metadata.get("recurring_consent_acceptance_id") != str(command.recurring_consent_acceptance_id)
    ):
        raise SubscriptionLifecycleError("recurring_consent_invalid")
    consent_is_current = is_current_recurring_consent_acceptance(
        db,
        acceptance=acceptance,
        user=user,
        entrypoint_type=entrypoint_session.entrypoint_type,
        entrypoint_value=entrypoint_session.entrypoint_value,
        plan_id=plan.id,
        now=command.occurred_at,
    )
    if not consent_is_current:
        order_metadata = order.metadata_
        entrypoint_metadata = entrypoint_session.metadata_
        order_item = get_order_item_with_plan(db, order.id)
        is_legacy_auto_renew_order = (
            isinstance(order_metadata, dict)
            and "plan_id" not in order_metadata
            and order_metadata.get("auto_renew") is True
            and order_metadata.get("plan_code") == plan.code
            and isinstance(entrypoint_metadata, dict)
            and "plan_id" not in entrypoint_metadata
            and entrypoint_metadata.get("auto_renew") is True
            and entrypoint_metadata.get("plan_code") == plan.code
            and order_item is not None
            and order_item.plan_id == order.plan_id == plan.id
            and order_item.plan_code_snapshot == plan.code
        )
        consent_is_current = is_legacy_auto_renew_order and is_current_legacy_recurring_consent_acceptance(
            db,
            acceptance=acceptance,
            user=user,
            entrypoint_type=entrypoint_session.entrypoint_type,
            entrypoint_value=entrypoint_session.entrypoint_value,
            plan_code=plan.code,
            now=command.occurred_at,
        )
    if not consent_is_current:
        raise SubscriptionLifecycleError("recurring_consent_invalid")
    try:
        with db.begin_nested():
            subscription.provider_account_id = account.id
            subscription.provider_subscription_id = command.provider_subscription_id
            subscription.recurring_consent_acceptance_id = acceptance.id
            subscription.renewal_mode = SubscriptionRenewalMode.AUTOMATIC
            _write_event(
                db,
                subscription=subscription,
                command=command,
                event_type=SubscriptionEventType.AUTOMATIC_RENEWAL_ENABLED,
                previous_status=subscription.status,
                next_status=subscription.status,
                order_id=order.id,
            )
    except IntegrityError as exc:
        if not _is_provider_subscription_reference_conflict(exc):
            raise
        raise SubscriptionLifecycleError("provider_subscription_reference_conflict") from exc
    return subscription


@_transactional
def apply_renewal_payment(db: Session, command: ApplyRenewalPaymentCommand) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)
    subscription = get_subscription_by_id(db, command.subscription_id, for_update=True)
    if subscription is None:
        raise SubscriptionLifecycleError("subscription_not_found")
    order, _, _ = _verify_renewal_context(db, subscription=subscription, command=command)
    order_plan = _find_plan_for_order(db, order)
    if order_plan.id != subscription.plan_id or not _scope_matches(subscription, order_plan):
        raise SubscriptionLifecycleError("renewal_order_plan_mismatch")
    previous = subscription.status
    if command.succeeded:
        ensure_subscription_status_transition(previous, SubscriptionStatus.ACTIVE)
        paid_at = order.paid_at or command.paid_at or command.occurred_at
        start = max(subscription.current_period_end, paid_at)
        subscription.current_period_start = start
        subscription.current_period_end = _period_end(start, order_plan)
        subscription.status = SubscriptionStatus.ACTIVE
        db.add(
            Entitlement(
                tenant_id=subscription.tenant_id,
                region=subscription.region,
                user_id=subscription.user_id,
                subscription_id=subscription.id,
                plan_id=order_plan.id,
                scope_type=subscription.scope_type,
                product_id=subscription.product_id,
                bundle_id=subscription.bundle_id,
                status=EntitlementStatus.ACTIVE,
                valid_from=subscription.current_period_start,
                valid_until=subscription.current_period_end,
                source=EntitlementSource.ORDER,
                order_id=order.id,
            )
        )
        event_type = SubscriptionEventType.RENEWAL_SUCCEEDED
    else:
        ensure_subscription_status_transition(previous, SubscriptionStatus.PAST_DUE)
        subscription.status = SubscriptionStatus.PAST_DUE
        event_type = SubscriptionEventType.RENEWAL_FAILED
    _write_event(
        db,
        subscription=subscription,
        command=command,
        event_type=event_type,
        previous_status=previous,
        next_status=subscription.status,
        order_id=order.id,
        payment_id=command.payment_id,
        webhook_event_id=command.webhook_event_id,
    )
    return subscription


@_transactional
def apply_provider_subscription_state(db: Session, command: ApplyProviderSubscriptionStateCommand) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)
    subscription = get_subscription_by_id(db, command.subscription_id, for_update=True)
    if subscription is None:
        raise SubscriptionLifecycleError("subscription_not_found")
    previous = subscription.status
    status = subscription_status_from_provider_state(command.provider_state)
    ensure_subscription_status_transition(previous, status)
    subscription.status = status
    if status == SubscriptionStatus.CANCELED:
        subscription.renewal_mode = SubscriptionRenewalMode.MANUAL
        subscription.canceled_at = subscription.canceled_at or command.occurred_at
    _write_event(
        db,
        subscription=subscription,
        command=command,
        event_type=SubscriptionEventType.PROVIDER_SUBSCRIPTION_STATE_APPLIED,
        previous_status=previous,
        next_status=status,
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
        SubscriptionStatus.TRIALING,
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.PAST_DUE,
        SubscriptionStatus.PAUSED,
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
    if refund.amount_minor != command.amount_minor:
        raise SubscriptionLifecycleError("refund_amount_mismatch")
    if refund.status != RefundStatus.SUCCEEDED:
        raise SubscriptionLifecycleError("refund_not_verified")
    subscription = get_subscription_for_order(db, order.id, for_update=True)
    if subscription is None:
        raise SubscriptionLifecycleError("subscription_not_found_for_order")
    payment = get_payment_for_refund(db, refund.payment_id)
    if payment is None or payment.order_id != order.id:
        raise SubscriptionLifecycleError("refund_payment_missing")
    if (
        refund.provider_account_id != order.provider_account_id
        or payment.provider_account_id != order.provider_account_id
    ):
        raise SubscriptionLifecycleError("refund_provider_context_mismatch")
    previous = subscription.status
    full_refund = payment.refunded_amount_minor >= payment.amount_minor
    if full_refund:
        refunded_entitlements = list_entitlements_for_order(db, order.id, for_update=True)
        for entitlement in refunded_entitlements:
            if entitlement.status == EntitlementStatus.ACTIVE.value:
                entitlement.status = EntitlementStatus.REVOKED.value
                entitlement.revoked_at = command.occurred_at
        db.flush()
        remaining_grants = _active_or_future_entitlements(db, subscription, now=command.occurred_at)
        if remaining_grants:
            if subscription.status in {SubscriptionStatus.PAST_DUE.value, SubscriptionStatus.PAUSED.value}:
                ensure_subscription_status_transition(previous, SubscriptionStatus.ACTIVE)
                subscription.status = SubscriptionStatus.ACTIVE.value
        else:
            ensure_subscription_status_transition(previous, SubscriptionStatus.REFUNDED)
            subscription.status = SubscriptionStatus.REFUNDED.value
            current_entitlement = _current_entitlement(db, subscription, now=command.occurred_at)
            if current_entitlement:
                current_entitlement.status = EntitlementStatus.REVOKED.value
                current_entitlement.revoked_at = command.occurred_at
    _write_event(
        db,
        subscription=subscription,
        command=command,
        event_type=(
            SubscriptionEventType.REFUND_APPLIED if full_refund else SubscriptionEventType.PARTIAL_REFUND_APPLIED
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
        subscription.status = SubscriptionStatus.EXPIRED
        for entitlement in list_due_entitlements_for_subscription(
            db,
            subscription.id,
            now=command.now,
            for_update=True,
        ):
            entitlement.status = EntitlementStatus.EXPIRED
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
