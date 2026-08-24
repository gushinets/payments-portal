from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domains.billing.enums import (
    EntitlementStatus,
    ProviderSubscriptionState,
    SubscriptionRenewalMode,
    SubscriptionStatus,
)
from app.domains.billing.service import (
    ApplyRefundCommand,
    ApplyProviderSubscriptionStateCommand,
    ApplyRenewalPaymentCommand,
    SubscriptionLifecycleError,
    apply_refund,
    apply_provider_subscription_state,
    ensure_subscription_status_transition,
    subscription_status_from_provider_state,
)
from app.models import Entitlement, Order, Payment, PaymentProviderAccount, Plan, Refund, Subscription, User


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
def test_terminal_provider_states_stop_future_renewal() -> None:
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
