from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domains.billing.enums import (
    EntitlementStatus,
    ProviderSubscriptionState,
    SubscriptionEventType,
    SubscriptionRenewalMode,
    SubscriptionStatus,
)
from app.domains.billing.service import (
    ActivatePaidPeriodCommand,
    ApplyRefundCommand,
    ApplyProviderSubscriptionStateCommand,
    ApplyRenewalPaymentCommand,
    ExpireDueSubscriptionsCommand,
    SubscriptionLifecycleError,
    activate_paid_period,
    apply_refund,
    apply_provider_subscription_state,
    ensure_subscription_status_transition,
    expire_due_subscriptions,
    subscription_status_from_provider_state,
)
from app.infrastructure.queries.subscriptions import get_subscription_for_order
from app.models import (
    Entitlement,
    Order,
    Payment,
    PaymentProviderAccount,
    PaymentWebhookEvent,
    Plan,
    Refund,
    Subscription,
    SubscriptionEvent,
    User,
)


def test_provider_state_is_mapped_to_domain_status() -> None:
    assert subscription_status_from_provider_state(ProviderSubscriptionState.ENDED) == SubscriptionStatus.CANCELED


@pytest.mark.parametrize(
    "provider_state",
    (
        ProviderSubscriptionState.CANCELED,
        ProviderSubscriptionState.REJECTED,
        ProviderSubscriptionState.EXPIRED,
        ProviderSubscriptionState.ENDED,
    ),
)
def test_terminal_provider_states_stop_future_renewal(provider_state: ProviderSubscriptionState) -> None:
    assert subscription_status_from_provider_state(provider_state) == SubscriptionStatus.CANCELED


@pytest.mark.parametrize(
    ("provider_state", "expected_status", "expected_renewal_mode"),
    (
        (
            ProviderSubscriptionState.PAST_DUE,
            SubscriptionStatus.PAST_DUE.value,
            SubscriptionRenewalMode.AUTOMATIC.value,
        ),
        (
            ProviderSubscriptionState.REJECTED,
            SubscriptionStatus.CANCELED.value,
            SubscriptionRenewalMode.MANUAL.value,
        ),
    ),
)
def test_provider_state_keeps_paid_entitlement_valid(
    db_session,
    provider_state: ProviderSubscriptionState,
    expected_status: str,
    expected_renewal_mode: str,
) -> None:
    now = datetime.now(timezone.utc)
    plan = db_session.query(Plan).filter(Plan.tenant_id == "anytoolai", Plan.region == "ru").first()
    assert plan is not None

    user = User(
        tenant_id="anytoolai",
        region="ru",
        email="provider-state-lifecycle@example.com",
        email_normalized="provider-state-lifecycle@example.com",
        status="active",
    )
    db_session.add(user)
    db_session.flush()
    account = PaymentProviderAccount(
        tenant_id="anytoolai",
        region="ru",
        provider="test-provider",
        public_identifier="provider-state-account",
        default_currency="RUB",
        enabled=True,
        test_mode=True,
        config={},
    )
    db_session.add(account)
    db_session.flush()
    order = Order(
        tenant_id="anytoolai",
        region="ru",
        order_number="provider-state-order",
        user_id=user.id,
        plan_id=plan.id,
        status="paid",
        amount_minor=plan.price_amount_minor,
        currency=plan.currency,
        provider="test-provider",
        provider_account_id=account.id,
        merchant_order_id="provider-state-merchant-order",
        paid_at=now,
    )
    db_session.add(order)
    db_session.flush()
    subscription = Subscription(
        tenant_id="anytoolai",
        region="ru",
        user_id=user.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=SubscriptionStatus.ACTIVE.value,
        renewal_mode=SubscriptionRenewalMode.AUTOMATIC.value,
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    db_session.add(subscription)
    db_session.flush()
    entitlement = Entitlement(
        tenant_id="anytoolai",
        region="ru",
        user_id=user.id,
        subscription_id=subscription.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=EntitlementStatus.ACTIVE.value,
        valid_from=now,
        valid_until=subscription.current_period_end,
        source="order",
        order_id=order.id,
    )
    db_session.add(entitlement)
    db_session.flush()

    result = apply_provider_subscription_state(
        db_session,
        ApplyProviderSubscriptionStateCommand(
            operation_idempotency_key="provider-state-terminal",
            subscription_id=subscription.id,
            provider_state=provider_state,
            occurred_at=now,
        ),
    )

    assert result.status == expected_status
    assert result.renewal_mode == expected_renewal_mode
    assert entitlement.status == EntitlementStatus.ACTIVE.value
    assert entitlement.valid_until == subscription.current_period_end


def test_terminal_subscription_cannot_be_reactivated() -> None:
    with pytest.raises(SubscriptionLifecycleError, match="invalid_subscription_status_transition"):
        ensure_subscription_status_transition(SubscriptionStatus.REFUNDED.value, SubscriptionStatus.ACTIVE)


def test_renewal_paid_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="paid_at_must_be_timezone_aware"):
        ApplyRenewalPaymentCommand(
            operation_idempotency_key="renewal-1",
            subscription_id=uuid.uuid4(),
            succeeded=True,
            paid_at=datetime(2026, 8, 24, 12, 0),
        )


def _add_billing_user_and_account(db_session, key: str) -> tuple[User, PaymentProviderAccount]:
    user = User(
        tenant_id="anytoolai",
        region="ru",
        email=f"{key}@example.com",
        email_normalized=f"{key}@example.com",
        status="active",
    )
    account = PaymentProviderAccount(
        tenant_id="anytoolai",
        region="ru",
        provider="test-provider",
        public_identifier=f"{key}-account",
        default_currency="RUB",
        enabled=True,
        test_mode=True,
        config={},
    )
    db_session.add_all([user, account])
    db_session.flush()
    return user, account


def _add_verified_paid_order(
    db_session,
    *,
    key: str,
    user: User,
    account: PaymentProviderAccount,
    plan: Plan,
    paid_at: datetime,
) -> tuple[Order, Payment, PaymentWebhookEvent]:
    order = Order(
        tenant_id="anytoolai",
        region="ru",
        order_number=f"{key}-order",
        user_id=user.id,
        plan_id=plan.id,
        status="paid",
        amount_minor=plan.price_amount_minor,
        currency=plan.currency,
        provider="test-provider",
        provider_account_id=account.id,
        merchant_order_id=f"{key}-merchant-order",
        paid_at=paid_at,
    )
    db_session.add(order)
    db_session.flush()
    payment = Payment(
        tenant_id="anytoolai",
        region="ru",
        order_id=order.id,
        provider_account_id=account.id,
        provider="test-provider",
        provider_payment_id=f"{key}-payment",
        status="succeeded",
        amount_minor=order.amount_minor,
        currency=order.currency,
        refunded_amount_minor=0,
        raw_summary={},
    )
    db_session.add(payment)
    db_session.flush()
    webhook = PaymentWebhookEvent(
        tenant_id="anytoolai",
        region="ru",
        provider_account_id=account.id,
        provider="test-provider",
        endpoint="pay",
        idempotency_key=f"{key}-webhook",
        payload_hash=f"{key}-payload-hash",
        invoice_id=order.provider_invoice_id,
        transaction_id=payment.provider_payment_id,
        order_id=order.id,
        payment_id=payment.id,
        amount_minor=order.amount_minor,
        currency=order.currency,
        raw_payload={},
        status="processed",
        processed_at=paid_at,
    )
    db_session.add(webhook)
    db_session.flush()
    return order, payment, webhook


def test_cumulative_refund_revokes_access(db_session) -> None:
    region = "ru"
    tenant_id = "anytoolai"
    now = datetime.now(timezone.utc)
    plan = db_session.query(Plan).filter(Plan.tenant_id == tenant_id, Plan.region == region).first()
    assert plan is not None

    user = User(
        tenant_id=tenant_id,
        region=region,
        email="refund-lifecycle@example.com",
        email_normalized="refund-lifecycle@example.com",
        status="active",
    )
    account = PaymentProviderAccount(
        tenant_id=tenant_id,
        region=region,
        provider="test-provider",
        public_identifier="test-provider-account",
        default_currency="RUB",
        enabled=True,
        test_mode=True,
        config={},
    )
    db_session.add_all([user, account])
    db_session.flush()

    order = Order(
        tenant_id=tenant_id,
        region=region,
        order_number="refund-lifecycle-order",
        user_id=user.id,
        plan_id=plan.id,
        status="paid",
        amount_minor=10000,
        currency="RUB",
        provider="test-provider",
        provider_account_id=account.id,
        merchant_order_id="refund-lifecycle-merchant-order",
        paid_at=now,
    )
    db_session.add(order)
    db_session.flush()

    payment = Payment(
        tenant_id=tenant_id,
        region=region,
        order_id=order.id,
        provider_account_id=account.id,
        provider="test-provider",
        provider_payment_id="refund-lifecycle-payment",
        status="succeeded",
        amount_minor=10000,
        currency="RUB",
        refunded_amount_minor=10000,
        raw_summary={},
    )
    db_session.add(payment)
    db_session.flush()

    subscription = Subscription(
        tenant_id=tenant_id,
        region=region,
        user_id=user.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=SubscriptionStatus.ACTIVE.value,
        renewal_mode="manual",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    db_session.add(subscription)
    db_session.flush()
    db_session.add(
        Entitlement(
            tenant_id=tenant_id,
            region=region,
            user_id=user.id,
            subscription_id=subscription.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status="active",
            valid_from=now,
            valid_until=now + timedelta(days=30),
            source="order",
            order_id=order.id,
        )
    )
    db_session.flush()
    db_session.add(
        SubscriptionEvent(
            subscription_id=subscription.id,
            event_type=SubscriptionEventType.PAID_PERIOD_ACTIVATED.value,
            previous_status=None,
            next_status=SubscriptionStatus.ACTIVE.value,
            occurred_at=now,
            operation_idempotency_key="refund-lifecycle-activation",
            order_id=order.id,
            payment_id=payment.id,
            metadata_={},
        )
    )
    db_session.flush()

    refund = Refund(
        tenant_id=tenant_id,
        region=region,
        order_id=order.id,
        payment_id=payment.id,
        provider_account_id=account.id,
        provider_refund_id="refund-lifecycle-refund",
        status="succeeded",
        amount_minor=4000,
        currency="RUB",
    )
    db_session.add(refund)
    db_session.flush()

    result = apply_refund(
        db_session,
        ApplyRefundCommand(
            operation_idempotency_key="refund-lifecycle-operation",
            order_id=order.id,
            refund_id=refund.id,
            amount_minor=4000,
        ),
    )

    assert result.status == SubscriptionStatus.REFUNDED.value


def test_full_refund_after_provider_cancellation_revokes_access(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "refund-after-provider-cancel")
    order, payment, webhook = _add_verified_paid_order(
        db_session,
        key="refund-after-provider-cancel",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="refund-after-provider-cancel-activate",
            order_id=order.id,
            payment_id=payment.id,
            webhook_event_id=webhook.id,
            occurred_at=now,
        ),
    )
    apply_provider_subscription_state(
        db_session,
        ApplyProviderSubscriptionStateCommand(
            operation_idempotency_key="refund-after-provider-cancel-provider-state",
            subscription_id=subscription.id,
            provider_state=ProviderSubscriptionState.CANCELED,
            occurred_at=now + timedelta(minutes=1),
        ),
    )
    payment.status = "refunded"
    payment.refunded_amount_minor = payment.amount_minor
    refund = Refund(
        tenant_id="anytoolai",
        region="ru",
        order_id=order.id,
        payment_id=payment.id,
        provider_account_id=account.id,
        provider_refund_id="refund-after-provider-cancel-refund",
        status="succeeded",
        amount_minor=payment.amount_minor,
        currency=payment.currency,
    )
    db_session.add(refund)
    db_session.flush()

    result = apply_refund(
        db_session,
        ApplyRefundCommand(
            operation_idempotency_key="refund-after-provider-cancel-apply",
            order_id=order.id,
            refund_id=refund.id,
            amount_minor=refund.amount_minor,
            occurred_at=now + timedelta(minutes=2),
        ),
    )

    entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == subscription.id).one()
    event = (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.REFUND_APPLIED.value,
        )
        .one()
    )
    assert result.status == SubscriptionStatus.REFUNDED.value
    assert entitlement.status == EntitlementStatus.REVOKED.value
    assert event.previous_status == SubscriptionStatus.CANCELED.value
    assert event.next_status == SubscriptionStatus.REFUNDED.value


def test_all_paid_orders_resolve_subscription_and_refund_revokes_current_access(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "paid-order-lookup")
    first_order, first_payment, first_webhook = _add_verified_paid_order(
        db_session,
        key="paid-order-lookup-first",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    second_order, second_payment, second_webhook = _add_verified_paid_order(
        db_session,
        key="paid-order-lookup-second",
        user=user,
        account=account,
        plan=plan,
        paid_at=now + timedelta(days=1),
    )

    first_subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="paid-order-lookup-first-activate",
            order_id=first_order.id,
            payment_id=first_payment.id,
            webhook_event_id=first_webhook.id,
            occurred_at=now,
        ),
    )
    second_subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="paid-order-lookup-second-activate",
            order_id=second_order.id,
            payment_id=second_payment.id,
            webhook_event_id=second_webhook.id,
            occurred_at=now + timedelta(days=1),
        ),
    )

    first_lookup = get_subscription_for_order(db_session, first_order.id)
    second_lookup = get_subscription_for_order(db_session, second_order.id)
    assert first_lookup is not None
    assert second_lookup is not None
    assert first_lookup.id == first_subscription.id
    assert second_lookup.id == first_subscription.id
    assert second_subscription.id == first_subscription.id

    first_payment.status = "refunded"
    first_payment.refunded_amount_minor = first_payment.amount_minor
    refund = Refund(
        tenant_id="anytoolai",
        region="ru",
        order_id=first_order.id,
        payment_id=first_payment.id,
        provider_account_id=account.id,
        provider_refund_id="paid-order-lookup-first-refund",
        status="succeeded",
        amount_minor=first_payment.amount_minor,
        currency=first_payment.currency,
    )
    db_session.add(refund)
    db_session.flush()

    result = apply_refund(
        db_session,
        ApplyRefundCommand(
            operation_idempotency_key="paid-order-lookup-first-refund-apply",
            order_id=first_order.id,
            refund_id=refund.id,
            amount_minor=refund.amount_minor,
            occurred_at=now + timedelta(days=2),
        ),
    )

    entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == first_subscription.id).one()
    assert result.status == SubscriptionStatus.REFUNDED.value
    assert entitlement.status == EntitlementStatus.REVOKED.value
    assert entitlement.order_id == second_order.id


def test_replacement_writes_audit_event_and_is_idempotent(db_session) -> None:
    now = datetime.now(timezone.utc)
    original_plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert original_plan is not None
    replacement_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="replacement-audit-plan",
        name="Replacement Audit Plan",
        scope_type=original_plan.scope_type,
        product_id=original_plan.product_id,
        bundle_id=original_plan.bundle_id,
        price_amount_minor=original_plan.price_amount_minor,
        currency=original_plan.currency,
        billing_period=original_plan.billing_period,
        renewal_mode=original_plan.renewal_mode,
        trial_days=0,
        status="active",
        valid_from=now,
    )
    db_session.add(replacement_plan)
    db_session.flush()
    user, account = _add_billing_user_and_account(db_session, "replacement-audit")
    first_order, first_payment, first_webhook = _add_verified_paid_order(
        db_session,
        key="replacement-audit-first",
        user=user,
        account=account,
        plan=original_plan,
        paid_at=now,
    )
    second_order, second_payment, second_webhook = _add_verified_paid_order(
        db_session,
        key="replacement-audit-second",
        user=user,
        account=account,
        plan=replacement_plan,
        paid_at=now + timedelta(days=1),
    )
    old_subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="replacement-audit-first-activate",
            order_id=first_order.id,
            payment_id=first_payment.id,
            webhook_event_id=first_webhook.id,
            occurred_at=now,
        ),
    )
    old_entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == old_subscription.id).one()
    replacement_command = ActivatePaidPeriodCommand(
        operation_idempotency_key="replacement-audit-second-activate",
        order_id=second_order.id,
        payment_id=second_payment.id,
        webhook_event_id=second_webhook.id,
        occurred_at=now + timedelta(days=1),
    )

    new_subscription = activate_paid_period(db_session, replacement_command)
    repeated_subscription = activate_paid_period(db_session, replacement_command)

    db_session.refresh(old_subscription)
    db_session.refresh(old_entitlement)
    new_entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == new_subscription.id).one()
    audit_event = (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == old_subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.SUBSCRIPTION_REPLACED.value,
        )
        .one()
    )
    paid_event = (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == new_subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.PAID_PERIOD_ACTIVATED.value,
        )
        .one()
    )
    assert old_subscription.status == SubscriptionStatus.CANCELED.value
    assert new_subscription.status == SubscriptionStatus.ACTIVE.value
    assert repeated_subscription.id == new_subscription.id
    assert old_entitlement.status == EntitlementStatus.SUPERSEDED.value
    assert old_entitlement.superseded_by_entitlement_id == new_entitlement.id
    assert audit_event.previous_status == SubscriptionStatus.ACTIVE.value
    assert audit_event.next_status == SubscriptionStatus.CANCELED.value
    assert audit_event.order_id == second_order.id
    assert audit_event.payment_id == second_payment.id
    assert audit_event.webhook_event_id == second_webhook.id
    assert audit_event.metadata_ == {"replacement_subscription_id": str(new_subscription.id)}
    assert audit_event.operation_idempotency_key == "replacement-audit-second-activate:subscription-replaced"
    assert paid_event.operation_idempotency_key == "replacement-audit-second-activate"
    assert (
        db_session.query(SubscriptionEvent)
        .filter(SubscriptionEvent.event_type == SubscriptionEventType.SUBSCRIPTION_REPLACED.value)
        .count()
        == 1
    )


def test_replacement_audit_event_is_written_without_active_entitlement(db_session) -> None:
    now = datetime.now(timezone.utc)
    original_plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert original_plan is not None
    replacement_plan = Plan(
        tenant_id="anytoolai",
        region="ru",
        code="replacement-without-entitlement-plan",
        name="Replacement Without Entitlement Plan",
        scope_type=original_plan.scope_type,
        product_id=original_plan.product_id,
        bundle_id=original_plan.bundle_id,
        price_amount_minor=original_plan.price_amount_minor,
        currency=original_plan.currency,
        billing_period=original_plan.billing_period,
        renewal_mode=original_plan.renewal_mode,
        trial_days=0,
        status="active",
        valid_from=now,
    )
    db_session.add(replacement_plan)
    db_session.flush()
    user, account = _add_billing_user_and_account(db_session, "replacement-no-active-entitlement")
    first_order, first_payment, first_webhook = _add_verified_paid_order(
        db_session,
        key="replacement-no-active-entitlement-first",
        user=user,
        account=account,
        plan=original_plan,
        paid_at=now,
    )
    second_order, second_payment, second_webhook = _add_verified_paid_order(
        db_session,
        key="replacement-no-active-entitlement-second",
        user=user,
        account=account,
        plan=replacement_plan,
        paid_at=now + timedelta(days=1),
    )
    old_subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="replacement-no-active-entitlement-first-activate",
            order_id=first_order.id,
            payment_id=first_payment.id,
            webhook_event_id=first_webhook.id,
            occurred_at=now,
        ),
    )
    old_entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == old_subscription.id).one()
    old_entitlement.status = EntitlementStatus.REVOKED.value
    old_entitlement.revoked_at = now + timedelta(hours=1)
    db_session.flush()

    new_subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="replacement-no-active-entitlement-second-activate",
            order_id=second_order.id,
            payment_id=second_payment.id,
            webhook_event_id=second_webhook.id,
            occurred_at=now + timedelta(days=1),
        ),
    )

    audit_event = (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == old_subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.SUBSCRIPTION_REPLACED.value,
        )
        .one()
    )
    assert old_subscription.status == SubscriptionStatus.CANCELED.value
    assert new_subscription.status == SubscriptionStatus.ACTIVE.value
    assert audit_event.metadata_ == {"replacement_subscription_id": str(new_subscription.id)}


def test_expire_due_subscriptions_batches_canceled_access_and_is_idempotent(db_session) -> None:
    now = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    plan = db_session.query(Plan).filter(Plan.tenant_id == "anytoolai", Plan.region == "ru").first()
    assert plan is not None

    user = User(
        tenant_id="anytoolai",
        region="ru",
        email="expiration-lifecycle@example.com",
        email_normalized="expiration-lifecycle@example.com",
        status="active",
    )
    db_session.add(user)
    db_session.flush()

    due_subscriptions: list[Subscription] = []
    for index, status in enumerate(
        (
            SubscriptionStatus.ACTIVE.value,
            SubscriptionStatus.CANCELED.value,
            SubscriptionStatus.PAST_DUE.value,
        )
    ):
        period_end = now - timedelta(minutes=index + 1)
        subscription = Subscription(
            tenant_id="anytoolai",
            region="ru",
            user_id=user.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=status,
            renewal_mode="manual",
            current_period_start=period_end - timedelta(days=30),
            current_period_end=period_end,
        )
        db_session.add(subscription)
        db_session.flush()
        db_session.add(
            Entitlement(
                tenant_id="anytoolai",
                region="ru",
                user_id=user.id,
                subscription_id=subscription.id,
                plan_id=plan.id,
                scope_type=plan.scope_type,
                product_id=plan.product_id,
                bundle_id=plan.bundle_id,
                status=EntitlementStatus.ACTIVE.value,
                valid_from=subscription.current_period_start,
                valid_until=period_end,
                source="trial",
            )
        )
        due_subscriptions.append(subscription)

    future_subscription = Subscription(
        tenant_id="anytoolai",
        region="ru",
        user_id=user.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=SubscriptionStatus.ACTIVE.value,
        renewal_mode="manual",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    db_session.add(future_subscription)
    db_session.flush()

    first_batch = expire_due_subscriptions(
        db_session,
        ExpireDueSubscriptionsCommand(now=now, batch_size=2),
    )
    second_batch = expire_due_subscriptions(
        db_session,
        ExpireDueSubscriptionsCommand(now=now, batch_size=2),
    )
    third_batch = expire_due_subscriptions(
        db_session,
        ExpireDueSubscriptionsCommand(now=now, batch_size=2),
    )

    assert len(first_batch) == 2
    assert len(second_batch) == 1
    assert third_batch == []
    assert {subscription.status for subscription in due_subscriptions} == {SubscriptionStatus.EXPIRED.value}
    entitlements = db_session.query(Entitlement).filter(Entitlement.user_id == user.id).all()
    assert {entitlement.status for entitlement in entitlements} == {EntitlementStatus.EXPIRED.value}
    assert all(entitlement.expired_at == now for entitlement in entitlements)
    assert future_subscription.status == SubscriptionStatus.ACTIVE.value
    assert db_session.query(SubscriptionEvent).count() == 3
