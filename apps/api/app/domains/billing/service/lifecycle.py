"""Provider-neutral subscription and entitlement lifecycle."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domains.billing.enums import (
    EntitlementSource,
    EntitlementStatus,
    SubscriptionRenewalMode,
    SubscriptionEventType,
    SubscriptionStatus,
)
from app.models import Entitlement, Subscription
from app.domains.billing.service.commands import (
    ActivatePaidPeriodCommand,
    LifecycleCommand,
    StartTrialCommand,
)
from app.domains.billing.service.state_machine import (
    SubscriptionLifecycleError,
    ensure_subscription_status_transition,
)
from app.domains.billing.service.support import (
    _active_or_future_entitlements,
    _event_for_key,
    _find_plan_for_order,
    _new_subscription,
    _period_end,
    _scope_matches,
    _scope_values,
    _subscription_for_event,
    _transactional,
    _verify_successful_payment_context,
    _write_event,
)
from app.infrastructure.queries.identity import lock_user_by_id
from app.infrastructure.queries.plans import get_plan_by_id
from app.infrastructure.queries.subscriptions import (
    get_live_subscription_for_scope,
    get_subscription_by_id,
    get_trial_for_scope,
    list_active_subscriptions_for_user,
    list_remaining_canceled_entitlements_for_scope,
)


_LIVE_SUBSCRIPTION_UNIQUE_INDEXES = frozenset(
    {
        "uq_subscriptions_live_product_scope",
        "uq_subscriptions_live_bundle_scope",
        "uq_subscriptions_live_all_access_scope",
    }
)


def _is_live_subscription_unique_conflict(error: IntegrityError) -> bool:
    constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", None)
    return constraint_name in _LIVE_SUBSCRIPTION_UNIQUE_INDEXES


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
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)
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
    existing_live = get_live_subscription_for_scope(
        db,
        tenant_id=command.tenant_id,
        region=command.region,
        user_id=command.user_id,
        scope_type=scope_type,
        product_id=product_id,
        bundle_id=bundle_id,
        for_update=True,
    )
    if existing_live:
        raise SubscriptionLifecycleError("live_subscription_conflict")

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
    try:
        with db.begin_nested():
            db.add(subscription)
            db.flush()
    except IntegrityError as exc:
        if not _is_live_subscription_unique_conflict(exc):
            raise
        raise SubscriptionLifecycleError("live_subscription_conflict") from exc
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
    user = lock_user_by_id(db, order.user_id)
    if user is None or user.tenant_id != order.tenant_id or user.region != order.region:
        raise SubscriptionLifecycleError("user_not_found")
    existing_event = _event_for_key(db, command.operation_idempotency_key)
    if existing_event:
        return _subscription_for_event(db, existing_event)

    paid_at = order.paid_at or command.occurred_at
    scope_type, product_id, bundle_id = _scope_values(plan)
    candidates = list_active_subscriptions_for_user(
        db,
        tenant_id=order.tenant_id,
        region=order.region,
        user_id=order.user_id,
        for_update=True,
    )
    subscription = next((item for item in candidates if item.plan_id == plan.id and _scope_matches(item, plan)), None)
    previous_status = subscription.status if subscription is not None else None
    superseded_entitlements: list[Entitlement] = []
    carry_forward_entitlements: list[Entitlement] = []
    carry_forward_boundary = paid_at
    if subscription is None:
        previous = next((item for item in candidates if _scope_matches(item, plan)), None)
        replaced_previous_status: str | None = None
        try:
            with db.begin_nested():
                if previous:
                    replaced_previous_status = previous.status
                    ensure_subscription_status_transition(replaced_previous_status, SubscriptionStatus.CANCELED)
                    previous.status = SubscriptionStatus.CANCELED.value
                    previous.canceled_at = command.occurred_at
                    superseded_entitlements = _active_or_future_entitlements(db, previous, now=command.occurred_at)
                    for previous_entitlement in superseded_entitlements:
                        previous_entitlement.status = EntitlementStatus.SUPERSEDED.value
                        previous_entitlement.superseded_at = command.occurred_at
                    db.flush()
                else:
                    carry_forward_entitlements = list_remaining_canceled_entitlements_for_scope(
                        db,
                        tenant_id=order.tenant_id,
                        region=order.region,
                        user_id=order.user_id,
                        scope_type=scope_type,
                        product_id=product_id,
                        bundle_id=bundle_id,
                        boundary=paid_at,
                        for_update=True,
                    )
                    carry_forward_boundary = max(
                        (entitlement.valid_until for entitlement in carry_forward_entitlements),
                        default=paid_at,
                    )
                subscription = _new_subscription(
                    tenant_id=order.tenant_id,
                    region=order.region,
                    user_id=order.user_id,
                    plan=plan,
                    start=carry_forward_boundary,
                )
                db.add(subscription)
                db.flush()
        except IntegrityError as exc:
            if not _is_live_subscription_unique_conflict(exc):
                raise
            subscription = get_live_subscription_for_scope(
                db,
                tenant_id=order.tenant_id,
                region=order.region,
                user_id=order.user_id,
                scope_type=scope_type,
                product_id=product_id,
                bundle_id=bundle_id,
                for_update=True,
            )
            if subscription is None or subscription.plan_id != plan.id:
                raise SubscriptionLifecycleError("live_subscription_conflict") from exc
            previous_status = subscription.status
            superseded_entitlements = []
            ensure_subscription_status_transition(subscription.status, SubscriptionStatus.ACTIVE)
            start = (
                paid_at
                if subscription.status == SubscriptionStatus.TRIALING.value
                else max(subscription.current_period_end, paid_at)
            )
            subscription.current_period_start = start
            subscription.current_period_end = _period_end(start, plan)
            subscription.status = SubscriptionStatus.ACTIVE.value
        else:
            if previous:
                assert replaced_previous_status is not None
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
            elif carry_forward_entitlements:
                predecessor = get_subscription_by_id(
                    db,
                    carry_forward_entitlements[0].subscription_id,
                    for_update=True,
                )
                replacement_event_key = f"{command.operation_idempotency_key}:subscription-replaced"
                if predecessor is not None and _event_for_key(db, replacement_event_key) is None:
                    _write_event(
                        db,
                        subscription=predecessor,
                        command=LifecycleCommand(
                            operation_idempotency_key=replacement_event_key,
                            occurred_at=command.occurred_at,
                            metadata={
                                **command.metadata,
                                "replacement_subscription_id": str(subscription.id),
                                "paid_through_valid_until": carry_forward_boundary.isoformat(),
                            },
                        ),
                        event_type=SubscriptionEventType.SUBSCRIPTION_REPLACED,
                        previous_status=predecessor.status,
                        next_status=predecessor.status,
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
