"""Provider-neutral subscription and entitlement lifecycle."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.orm import Session

from app.domains.billing.enums import (
    EntitlementSource,
    EntitlementStatus,
    SubscriptionRenewalMode,
    SubscriptionEventType,
    SubscriptionStatus,
)
from app.models import (
    Entitlement,
    Subscription,
)
from app.domains.billing.service.commands import (
    ActivatePaidPeriodCommand,
    ApplyProviderSubscriptionStateCommand,
    ApplyRefundCommand,
    ApplyRenewalPaymentCommand,
    EnableAutomaticRenewalCommand,
    ExpireDueSubscriptionsCommand,
    LifecycleCommand,
    RequestCancellationCommand,
    StartTrialCommand,
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
    _new_subscription,
    _period_end,
    _scope_matches,
    _scope_values,
    _subscription_for_event,
    _transactional,
    _verify_renewal_context,
    _verify_successful_payment_context,
    _write_event,
)
from app.infrastructure.queries.legal import get_document_acceptance_by_id
from app.infrastructure.queries.identity import lock_user_by_id
from app.infrastructure.queries.orders import get_order_by_id
from app.infrastructure.queries.payments import (
    get_payment_for_refund,
    get_provider_account_by_id,
    get_refund_by_id,
)
from app.infrastructure.queries.plans import get_plan_by_id
from app.infrastructure.queries.subscriptions import (
    get_subscription_by_id,
    get_subscription_for_order,
    get_trial_for_scope,
    list_active_subscriptions_for_user,
    list_due_entitlements_for_subscription,
    list_due_subscriptions,
    list_entitlements_for_order,
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


@_transactional
def activate_paid_period(db: Session, command: ActivatePaidPeriodCommand) -> Subscription:
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)

    order, payment, _ = _verify_successful_payment_context(
        db,
        order_id=command.order_id,
        payment_id=command.payment_id,
        webhook_event_id=command.webhook_event_id,
    )

    plan = _find_plan_for_order(db, order)
    paid_at = order.paid_at or command.occurred_at
    candidates = list_active_subscriptions_for_user(
        db, tenant_id=order.tenant_id, region=order.region, user_id=order.user_id
    )
    subscription = next((item for item in candidates if item.plan_id == plan.id and _scope_matches(item, plan)), None)
    previous_status = subscription.status if subscription is not None else None
    superseded_entitlements: list[Entitlement] = []
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
            replaced_previous_status = previous.status
            ensure_subscription_status_transition(replaced_previous_status, SubscriptionStatus.CANCELED)
            previous.status = SubscriptionStatus.CANCELED.value
            previous.canceled_at = command.occurred_at
            superseded_entitlements = _active_or_future_entitlements(db, previous, now=command.occurred_at)
            for previous_entitlement in superseded_entitlements:
                previous_entitlement.status = EntitlementStatus.SUPERSEDED.value
                previous_entitlement.superseded_at = command.occurred_at
            replacement_event_key = f"{command.operation_idempotency_key}:subscription-replaced"
            if _event_for_key(db, replacement_event_key) is None:
                _write_event(
                    db,
                    subscription=previous,
                    command=LifecycleCommand(
                        operation_idempotency_key=replacement_event_key,
                        occurred_at=command.occurred_at,
                        metadata={
                            **command.metadata,
                            "replacement_subscription_id": str(subscription.id),
                        },
                    ),
                    event_type=SubscriptionEventType.SUBSCRIPTION_REPLACED,
                    previous_status=replaced_previous_status,
                    next_status=SubscriptionStatus.CANCELED.value,
                    order_id=order.id,
                    payment_id=payment.id,
                    webhook_event_id=command.webhook_event_id,
                )
    else:
        ensure_subscription_status_transition(subscription.status, SubscriptionStatus.ACTIVE)
        start = (
            paid_at
            if subscription.status == SubscriptionStatus.TRIALING.value
            else max(subscription.current_period_end, paid_at)
        )
        subscription.current_period_start = start
        subscription.current_period_end = _period_end(start, plan)
        subscription.status = SubscriptionStatus.ACTIVE.value

    subscription.current_period_start = subscription.current_period_start or paid_at
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
        valid_from=subscription.current_period_start,
        valid_until=subscription.current_period_end,
        source=EntitlementSource.ORDER.value,
        order_id=order.id,
    )
    db.add(entitlement)
    db.flush()
    for previous_entitlement in superseded_entitlements:
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
        subscription.status = SubscriptionStatus.ACTIVE.value
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
                status=EntitlementStatus.ACTIVE.value,
                valid_from=subscription.current_period_start,
                valid_until=subscription.current_period_end,
                source=EntitlementSource.ORDER.value,
                order_id=order.id,
            )
        )
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
    if refund.amount_minor != command.amount_minor:
        raise SubscriptionLifecycleError("refund_amount_mismatch")
    if refund.status != "succeeded":
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
        subscription.status = SubscriptionStatus.EXPIRED.value
        for entitlement in list_due_entitlements_for_subscription(
            db,
            subscription.id,
            now=command.now,
            for_update=True,
        ):
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
