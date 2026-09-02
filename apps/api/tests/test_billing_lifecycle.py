from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.domains.billing.enums import (
    EntitlementSource,
    EntitlementStatus,
    ProviderSubscriptionState,
    SubscriptionEventType,
    SubscriptionRenewalMode,
    SubscriptionStatus,
)
from app.domains.billing.service import (
    ActivatePaidPeriodCommand,
    EnableAutomaticRenewalCommand,
    ApplyRefundCommand,
    ApplyProviderSubscriptionStateCommand,
    ApplyRenewalPaymentCommand,
    ExpireDueSubscriptionsCommand,
    SubscriptionLifecycleError,
    activate_paid_period,
    enable_automatic_renewal,
    apply_refund,
    apply_renewal_payment,
    apply_provider_subscription_state,
    ensure_subscription_status_transition,
    expire_due_subscriptions,
    subscription_status_from_provider_state,
)
from app.domains.legal.service import expected_acceptance_text_hash
from app.infrastructure.queries.subscriptions import (
    get_active_entitlement_for_scope,
    get_subscription_for_order,
)
from app.models import (
    DocumentAcceptance,
    DocumentVersion,
    Entitlement,
    EntrypointSession,
    LegalEntity,
    Order,
    OrderItem,
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


@pytest.mark.parametrize(
    ("provider_state", "expected_status"),
    (
        (ProviderSubscriptionState.PAST_DUE, SubscriptionStatus.PAST_DUE),
        (ProviderSubscriptionState.PAUSED, SubscriptionStatus.PAUSED),
    ),
)
@pytest.mark.parametrize("entitlement_source", (EntitlementSource.TRIAL, EntitlementSource.ORDER))
def test_trialing_provider_state_keeps_current_entitlement_and_is_idempotent(
    db_session,
    provider_state: ProviderSubscriptionState,
    expected_status: SubscriptionStatus,
    entitlement_source: EntitlementSource,
) -> None:
    now = datetime.now(timezone.utc)
    key = f"trialing-provider-state-{provider_state.value}-{entitlement_source.value}"
    plan = db_session.query(Plan).filter(Plan.tenant_id == "anytoolai", Plan.region == "ru").first()
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, key)
    order_id = None
    if entitlement_source == EntitlementSource.ORDER:
        order, _, _ = _add_verified_paid_order(
            db_session,
            key=key,
            user=user,
            account=account,
            plan=plan,
            paid_at=now,
        )
        order_id = order.id
    subscription = Subscription(
        tenant_id="anytoolai",
        region="ru",
        user_id=user.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=SubscriptionStatus.TRIALING.value,
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
        source=entitlement_source.value,
        order_id=order_id,
    )
    db_session.add(entitlement)
    db_session.flush()

    command = ApplyProviderSubscriptionStateCommand(
        operation_idempotency_key=key,
        subscription_id=subscription.id,
        provider_state=provider_state,
        occurred_at=now,
    )
    result = apply_provider_subscription_state(db_session, command)
    repeated = apply_provider_subscription_state(db_session, command)

    events = (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.PROVIDER_SUBSCRIPTION_STATE_APPLIED.value,
        )
        .all()
    )
    db_session.refresh(entitlement)
    assert result.status == expected_status.value
    assert repeated.id == result.id
    assert repeated.status == expected_status.value
    assert entitlement.status == EntitlementStatus.ACTIVE.value
    assert entitlement.revoked_at is None
    assert len(events) == 1
    assert events[0].previous_status == SubscriptionStatus.TRIALING.value
    assert events[0].next_status == expected_status.value


def test_terminal_subscription_cannot_be_reactivated() -> None:
    with pytest.raises(SubscriptionLifecycleError, match="invalid_subscription_status_transition"):
        ensure_subscription_status_transition(SubscriptionStatus.REFUNDED.value, SubscriptionStatus.ACTIVE)


def test_renewal_paid_at_must_be_timezone_aware() -> None:
    with pytest.raises(ValueError, match="paid_at_must_be_timezone_aware"):
        ApplyRenewalPaymentCommand(
            operation_idempotency_key="renewal-1",
            subscription_id=uuid.uuid4(),
            succeeded=True,
            order_id=uuid.uuid4(),
            payment_id=uuid.uuid4(),
            webhook_event_id=uuid.uuid4(),
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


def _plan_by_code(db_session, code: str) -> Plan:
    plan = db_session.query(Plan).filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.code == code).one()
    return plan


def _add_recurring_consent_acceptance(
    db_session,
    *,
    user: User,
    key: str,
    plan_code: str,
    accepted_at: datetime,
    entrypoint_type: str = "product",
    entrypoint_value: str | None = None,
) -> DocumentAcceptance:
    document = (
        db_session.query(DocumentVersion)
        .filter(
            DocumentVersion.tenant_id == user.tenant_id,
            DocumentVersion.region == user.region,
            DocumentVersion.doc_type == "recurring_consent",
            DocumentVersion.is_active.is_(True),
            DocumentVersion.requires_acceptance.is_(True),
            DocumentVersion.effective_from <= accepted_at,
        )
        .one_or_none()
    )
    if document is None:
        entity = LegalEntity(
            tenant_id=user.tenant_id,
            region=user.region,
            name=f"{key} legal entity",
            entity_type="company",
            legal_address="Test address",
            support_email="support@example.com",
            status="active",
        )
        db_session.add(entity)
        db_session.flush()
        document = DocumentVersion(
            tenant_id=user.tenant_id,
            region=user.region,
            legal_entity_id=entity.id,
            doc_type="recurring_consent",
            version=f"{key}-v1",
            title="Согласие на рекуррентные платежи",
            url_path="/ru/recurring_consent",
            content_hash=f"sha256:{key}",
            published_at=accepted_at,
            effective_from=accepted_at,
            is_active=True,
            requires_acceptance=True,
        )
        db_session.add(document)
        db_session.flush()
    resolved_entrypoint_value = entrypoint_value or plan_code
    entrypoint_session = EntrypointSession(
        tenant_id=user.tenant_id,
        route_region=user.region,
        resolved_region=user.region,
        entrypoint_type=entrypoint_type,
        entrypoint_value=resolved_entrypoint_value,
        user_id=user.id,
        metadata_={"plan_id": str(_plan_by_code(db_session, plan_code).id)},
    )
    db_session.add(entrypoint_session)
    db_session.flush()
    acceptance = DocumentAcceptance(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        entrypoint_session_id=entrypoint_session.id,
        document_version_id=document.id,
        doc_type=document.doc_type,
        version=document.version,
        acceptance_kind="recurring_consent",
        accepted_at=accepted_at,
        acceptance_text_hash=expected_acceptance_text_hash(document),
        entrypoint_type=entrypoint_type,
        entrypoint_value=resolved_entrypoint_value,
        metadata_={"plan_id": str(_plan_by_code(db_session, plan_code).id), "fixture_key": key},
    )
    db_session.add(acceptance)
    db_session.flush()
    return acceptance


def _add_verified_paid_order(
    db_session,
    *,
    key: str,
    user: User,
    account: PaymentProviderAccount,
    plan: Plan,
    paid_at: datetime,
    entrypoint_session_id: uuid.UUID | None = None,
    metadata: dict | None = None,
) -> tuple[Order, Payment, PaymentWebhookEvent]:
    order = Order(
        tenant_id="anytoolai",
        region="ru",
        order_number=f"{key}-order",
        user_id=user.id,
        entrypoint_session_id=entrypoint_session_id,
        plan_id=plan.id,
        status="paid",
        amount_minor=plan.price_amount_minor,
        currency=plan.currency,
        provider="test-provider",
        provider_account_id=account.id,
        merchant_order_id=f"{key}-merchant-order",
        paid_at=paid_at,
        metadata_=metadata or {},
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


def _assert_no_paid_activation_access_mutation(db_session, *, user: User, order: Order, operation_key: str) -> None:
    assert db_session.query(Subscription).filter(Subscription.user_id == user.id).count() == 0
    assert db_session.query(Entitlement).filter(Entitlement.order_id == order.id).count() == 0
    assert (
        db_session.query(SubscriptionEvent).filter(SubscriptionEvent.operation_idempotency_key == operation_key).count()
        == 0
    )
    assert (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.order_id == order.id,
            SubscriptionEvent.event_type == SubscriptionEventType.PAID_PERIOD_ACTIVATED.value,
        )
        .count()
        == 0
    )


def _add_refund(
    db_session,
    *,
    key: str,
    order: Order,
    payment: Payment,
    account: PaymentProviderAccount,
    amount_minor: int,
    occurred_at: datetime,
    status: str = "succeeded",
) -> Refund:
    refund = Refund(
        tenant_id=order.tenant_id,
        region=order.region,
        order_id=order.id,
        payment_id=payment.id,
        provider_account_id=account.id,
        provider_refund_id=f"{key}-refund",
        status=status,
        amount_minor=amount_minor,
        currency=payment.currency,
        requested_at=occurred_at,
        succeeded_at=occurred_at if status == "succeeded" else None,
    )
    db_session.add(refund)
    db_session.flush()
    return refund


def _add_paid_subscription_for_order(
    db_session,
    *,
    key: str,
    order: Order,
    payment: Payment,
    plan: Plan,
    starts_at: datetime,
    ends_at: datetime,
    status: str = SubscriptionStatus.ACTIVE.value,
) -> tuple[Subscription, Entitlement, SubscriptionEvent]:
    subscription = Subscription(
        tenant_id=order.tenant_id,
        region=order.region,
        user_id=order.user_id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=status,
        renewal_mode=SubscriptionRenewalMode.MANUAL.value,
        current_period_start=starts_at,
        current_period_end=ends_at,
    )
    db_session.add(subscription)
    db_session.flush()
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
        valid_from=starts_at,
        valid_until=ends_at,
        source="order",
        order_id=order.id,
    )
    event = SubscriptionEvent(
        subscription_id=subscription.id,
        event_type=SubscriptionEventType.PAID_PERIOD_ACTIVATED.value,
        previous_status=None,
        next_status=status,
        occurred_at=starts_at,
        operation_idempotency_key=f"paid_period_activated:{key}",
        order_id=order.id,
        payment_id=payment.id,
        metadata_={},
    )
    db_session.add_all([entitlement, event])
    db_session.flush()
    return subscription, entitlement, event


def _add_automatic_renewal_context(
    db_session,
    *,
    key: str,
    user: User,
    account: PaymentProviderAccount,
    plan: Plan,
    now: datetime,
) -> tuple[DocumentAcceptance, Order, Subscription]:
    acceptance = _add_recurring_consent_acceptance(
        db_session,
        user=user,
        key=key,
        plan_code=plan.code,
        accepted_at=now,
    )
    order, payment, _ = _add_verified_paid_order(
        db_session,
        key=key,
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
        entrypoint_session_id=acceptance.entrypoint_session_id,
        metadata={
            "auto_renew": True,
            "recurring_consent_acceptance_id": str(acceptance.id),
        },
    )
    subscription, _, _ = _add_paid_subscription_for_order(
        db_session,
        key=key,
        order=order,
        payment=payment,
        plan=plan,
        starts_at=now,
        ends_at=now + timedelta(days=30),
    )
    return acceptance, order, subscription


@pytest.mark.postgres
def test_automatic_renewal_provider_reference_conflict_uses_domain_error_and_savepoint(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = db_session.query(Plan).filter(Plan.tenant_id == "anytoolai", Plan.region == "ru").first()
    assert plan is not None
    plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC.value
    db_session.flush()
    first_user, account = _add_billing_user_and_account(db_session, "automatic-renewal-reference-first")
    second_user = User(
        tenant_id="anytoolai",
        region="ru",
        email="automatic-renewal-reference-second@example.com",
        email_normalized="automatic-renewal-reference-second@example.com",
        status="active",
    )
    db_session.add(second_user)
    db_session.flush()
    first_acceptance = _add_recurring_consent_acceptance(
        db_session,
        user=first_user,
        key="automatic-renewal-reference-first",
        plan_code=plan.code,
        accepted_at=now,
    )
    second_acceptance = _add_recurring_consent_acceptance(
        db_session,
        user=second_user,
        key="automatic-renewal-reference-second",
        plan_code=plan.code,
        accepted_at=now,
    )
    first_order, first_payment, _ = _add_verified_paid_order(
        db_session,
        key="automatic-renewal-reference-first",
        user=first_user,
        account=account,
        plan=plan,
        paid_at=now,
        entrypoint_session_id=first_acceptance.entrypoint_session_id,
        metadata={
            "auto_renew": True,
            "recurring_consent_acceptance_id": str(first_acceptance.id),
        },
    )
    second_order, second_payment, _ = _add_verified_paid_order(
        db_session,
        key="automatic-renewal-reference-second",
        user=second_user,
        account=account,
        plan=plan,
        paid_at=now,
        entrypoint_session_id=second_acceptance.entrypoint_session_id,
        metadata={
            "auto_renew": True,
            "recurring_consent_acceptance_id": str(second_acceptance.id),
        },
    )
    first_subscription, _, _ = _add_paid_subscription_for_order(
        db_session,
        key="automatic-renewal-reference-first",
        order=first_order,
        payment=first_payment,
        plan=plan,
        starts_at=now,
        ends_at=now + timedelta(days=30),
    )
    second_subscription, _, _ = _add_paid_subscription_for_order(
        db_session,
        key="automatic-renewal-reference-second",
        order=second_order,
        payment=second_payment,
        plan=plan,
        starts_at=now,
        ends_at=now + timedelta(days=30),
    )

    first_command = EnableAutomaticRenewalCommand(
        operation_idempotency_key="automatic-renewal-reference-first",
        subscription_id=first_subscription.id,
        order_id=first_order.id,
        provider_account_id=account.id,
        provider_subscription_id="provider-reference-shared",
        recurring_consent_acceptance_id=first_acceptance.id,
        occurred_at=now,
    )
    first_result = enable_automatic_renewal(db_session, first_command)
    repeated_result = enable_automatic_renewal(db_session, first_command)

    assert first_result.id == first_subscription.id
    assert repeated_result.id == first_subscription.id

    with pytest.raises(SubscriptionLifecycleError, match="provider_subscription_reference_conflict"):
        enable_automatic_renewal(
            db_session,
            EnableAutomaticRenewalCommand(
                operation_idempotency_key="automatic-renewal-reference-second-conflict",
                subscription_id=second_subscription.id,
                order_id=second_order.id,
                provider_account_id=account.id,
                provider_subscription_id="provider-reference-shared",
                recurring_consent_acceptance_id=second_acceptance.id,
                occurred_at=now,
            ),
        )

    db_session.refresh(first_subscription)
    db_session.refresh(second_subscription)
    assert first_subscription.provider_subscription_id == "provider-reference-shared"
    assert first_subscription.renewal_mode == SubscriptionRenewalMode.AUTOMATIC.value
    assert second_subscription.provider_subscription_id is None
    assert second_subscription.renewal_mode == SubscriptionRenewalMode.MANUAL.value
    assert (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == first_subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.AUTOMATIC_RENEWAL_ENABLED.value,
        )
        .count()
        == 1
    )

    unique_result = enable_automatic_renewal(
        db_session,
        EnableAutomaticRenewalCommand(
            operation_idempotency_key="automatic-renewal-reference-second-success",
            subscription_id=second_subscription.id,
            order_id=second_order.id,
            provider_account_id=account.id,
            provider_subscription_id="provider-reference-second",
            recurring_consent_acceptance_id=second_acceptance.id,
            occurred_at=now,
        ),
    )

    assert unique_result.id == second_subscription.id
    assert unique_result.provider_subscription_id == "provider-reference-second"


def test_automatic_renewal_accepts_exact_paid_checkout_context(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = _plan_by_code(db_session, "document-summary-pro")
    plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC.value
    user, account = _add_billing_user_and_account(db_session, "automatic-renewal-valid-context")
    acceptance, order, subscription = _add_automatic_renewal_context(
        db_session,
        key="automatic-renewal-valid-context",
        user=user,
        account=account,
        plan=plan,
        now=now,
    )

    result = enable_automatic_renewal(
        db_session,
        EnableAutomaticRenewalCommand(
            operation_idempotency_key="automatic-renewal-valid-context-operation",
            subscription_id=subscription.id,
            order_id=order.id,
            provider_account_id=account.id,
            provider_subscription_id="provider-valid-context",
            recurring_consent_acceptance_id=acceptance.id,
            occurred_at=now,
        ),
    )

    assert result.id == subscription.id
    assert result.renewal_mode == SubscriptionRenewalMode.AUTOMATIC.value
    assert result.provider_account_id == account.id
    assert result.provider_subscription_id == "provider-valid-context"
    assert result.recurring_consent_acceptance_id == acceptance.id
    event = (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.AUTOMATIC_RENEWAL_ENABLED.value,
        )
        .one()
    )
    assert event.order_id == order.id


def test_automatic_renewal_rejects_same_scope_provider_account_substitution_without_mutation(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = _plan_by_code(db_session, "document-summary-pro")
    plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC.value
    user, account = _add_billing_user_and_account(db_session, "automatic-renewal-provider-substitution")
    acceptance, order, subscription = _add_automatic_renewal_context(
        db_session,
        key="automatic-renewal-provider-substitution",
        user=user,
        account=account,
        plan=plan,
        now=now,
    )
    secondary_entity = LegalEntity(
        tenant_id=account.tenant_id,
        region=account.region,
        name="automatic-renewal-provider-substitution legal entity",
        entity_type="company",
        legal_address="Test address",
        support_email="support@example.com",
        status="active",
    )
    db_session.add(secondary_entity)
    db_session.flush()
    substituted_account = PaymentProviderAccount(
        tenant_id=account.tenant_id,
        region=account.region,
        legal_entity_id=secondary_entity.id,
        provider=account.provider,
        public_identifier="automatic-renewal-provider-substitution-account-b",
        default_currency=account.default_currency,
        enabled=True,
        test_mode=account.test_mode,
        config={},
    )
    db_session.add(substituted_account)
    db_session.flush()
    assert order.provider_account_id == account.id
    assert substituted_account.id != account.id

    _assert_automatic_renewal_rejected_without_mutation(
        db_session,
        subscription=subscription,
        command=EnableAutomaticRenewalCommand(
            operation_idempotency_key="automatic-renewal-provider-substitution-operation",
            subscription_id=subscription.id,
            order_id=order.id,
            provider_account_id=substituted_account.id,
            provider_subscription_id="provider-substituted-account",
            recurring_consent_acceptance_id=acceptance.id,
            occurred_at=now,
        ),
        expected_error="automatic_renewal_context_missing",
    )


def _assert_automatic_renewal_rejected_without_mutation(
    db_session,
    *,
    subscription: Subscription,
    command: EnableAutomaticRenewalCommand,
    expected_error: str,
) -> None:
    before = (
        subscription.renewal_mode,
        subscription.provider_account_id,
        subscription.provider_subscription_id,
        subscription.recurring_consent_acceptance_id,
    )
    with pytest.raises(SubscriptionLifecycleError, match=expected_error):
        enable_automatic_renewal(db_session, command)
    db_session.refresh(subscription)
    assert (
        subscription.renewal_mode,
        subscription.provider_account_id,
        subscription.provider_subscription_id,
        subscription.recurring_consent_acceptance_id,
    ) == before
    assert (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.AUTOMATIC_RENEWAL_ENABLED.value,
        )
        .count()
        == 0
    )


@pytest.mark.parametrize(
    ("invalid_context", "expected_error"),
    (
        ("stale_document", "recurring_consent_invalid"),
        ("wrong_hash", "recurring_consent_invalid"),
        ("missing_acceptance_entrypoint", "recurring_consent_invalid"),
        ("missing_entrypoint_session", "automatic_renewal_context_missing"),
        ("missing_plan_id", "recurring_consent_invalid"),
        ("non_string_plan_id", "recurring_consent_invalid"),
        ("wrong_plan_id", "recurring_consent_invalid"),
        ("wrong_entrypoint_type", "recurring_consent_invalid"),
        ("wrong_entrypoint_value", "recurring_consent_invalid"),
        ("foreign_user", "recurring_consent_invalid"),
        ("foreign_contour", "consent_scope_mismatch"),
    ),
)
def test_automatic_renewal_revalidates_persisted_consent_context(
    db_session,
    invalid_context: str,
    expected_error: str,
) -> None:
    now = datetime.now(timezone.utc)
    plan = _plan_by_code(db_session, "document-summary-pro")
    plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC.value
    user, account = _add_billing_user_and_account(db_session, f"automatic-renewal-{invalid_context}")
    acceptance, order, subscription = _add_automatic_renewal_context(
        db_session,
        key=f"automatic-renewal-{invalid_context}",
        user=user,
        account=account,
        plan=plan,
        now=now,
    )

    if invalid_context == "stale_document":
        current_document = db_session.get(DocumentVersion, acceptance.document_version_id)
        assert current_document is not None
        stale_document = DocumentVersion(
            tenant_id=current_document.tenant_id,
            region=current_document.region,
            legal_entity_id=current_document.legal_entity_id,
            doc_type=current_document.doc_type,
            version=f"stale-{invalid_context}",
            title=current_document.title,
            url_path=current_document.url_path,
            content_hash=current_document.content_hash,
            published_at=now - timedelta(days=2),
            effective_from=now - timedelta(days=2),
            is_active=False,
            requires_acceptance=True,
        )
        db_session.add(stale_document)
        db_session.flush()
        acceptance.document_version_id = stale_document.id
        acceptance.acceptance_text_hash = expected_acceptance_text_hash(stale_document)
    elif invalid_context == "wrong_hash":
        acceptance.acceptance_text_hash = "wrong-acceptance-text-hash"
    elif invalid_context == "missing_acceptance_entrypoint":
        acceptance.entrypoint_type = None
    elif invalid_context == "missing_entrypoint_session":
        order.entrypoint_session_id = None
    elif invalid_context == "missing_plan_id":
        acceptance.metadata_ = {}
    elif invalid_context == "non_string_plan_id":
        acceptance.metadata_ = {"plan_id": 123}
    elif invalid_context == "wrong_plan_id":
        acceptance.metadata_ = {"plan_id": str(uuid.uuid4())}
    elif invalid_context == "wrong_entrypoint_type":
        acceptance.entrypoint_type = "bundle"
    elif invalid_context == "wrong_entrypoint_value":
        acceptance.entrypoint_value = "different-entrypoint"
    elif invalid_context == "foreign_user":
        foreign_user = User(
            tenant_id=user.tenant_id,
            region=user.region,
            email=f"{invalid_context}-foreign@example.com",
            email_normalized=f"{invalid_context}-foreign@example.com",
            status="active",
        )
        db_session.add(foreign_user)
        db_session.flush()
        acceptance.user_id = foreign_user.id
    elif invalid_context == "foreign_contour":
        acceptance.region = "eu"

    db_session.flush()
    _assert_automatic_renewal_rejected_without_mutation(
        db_session,
        subscription=subscription,
        command=EnableAutomaticRenewalCommand(
            operation_idempotency_key=f"automatic-renewal-{invalid_context}-operation",
            subscription_id=subscription.id,
            order_id=order.id,
            provider_account_id=account.id,
            provider_subscription_id=f"provider-{invalid_context}",
            recurring_consent_acceptance_id=acceptance.id,
            occurred_at=now,
        ),
        expected_error=expected_error,
    )


def test_automatic_renewal_rejects_order_not_linked_to_target_subscription(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = _plan_by_code(db_session, "document-summary-pro")
    plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC.value
    user, account = _add_billing_user_and_account(db_session, "automatic-renewal-unlinked-order")
    acceptance, order, subscription = _add_automatic_renewal_context(
        db_session,
        key="automatic-renewal-unlinked-order",
        user=user,
        account=account,
        plan=plan,
        now=now,
    )
    unlinked_order, _, _ = _add_verified_paid_order(
        db_session,
        key="automatic-renewal-unlinked-order-second",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
        entrypoint_session_id=acceptance.entrypoint_session_id,
        metadata={
            "auto_renew": True,
            "recurring_consent_acceptance_id": str(acceptance.id),
        },
    )
    db_session.flush()
    _assert_automatic_renewal_rejected_without_mutation(
        db_session,
        subscription=subscription,
        command=EnableAutomaticRenewalCommand(
            operation_idempotency_key="automatic-renewal-unlinked-order-operation",
            subscription_id=subscription.id,
            order_id=unlinked_order.id,
            provider_account_id=account.id,
            provider_subscription_id="provider-unlinked-order",
            recurring_consent_acceptance_id=acceptance.id,
            occurred_at=now,
        ),
        expected_error="automatic_renewal_context_missing",
    )
    assert order.id != unlinked_order.id


def test_automatic_renewal_rejects_acceptance_not_stored_on_order(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = _plan_by_code(db_session, "document-summary-pro")
    plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC.value
    user, account = _add_billing_user_and_account(db_session, "automatic-renewal-acceptance-mismatch")
    acceptance, order, subscription = _add_automatic_renewal_context(
        db_session,
        key="automatic-renewal-acceptance-mismatch",
        user=user,
        account=account,
        plan=plan,
        now=now,
    )
    other_acceptance = _add_recurring_consent_acceptance(
        db_session,
        user=user,
        key="automatic-renewal-acceptance-mismatch-other",
        plan_code=plan.code,
        accepted_at=now,
    )
    _assert_automatic_renewal_rejected_without_mutation(
        db_session,
        subscription=subscription,
        command=EnableAutomaticRenewalCommand(
            operation_idempotency_key="automatic-renewal-acceptance-mismatch-operation",
            subscription_id=subscription.id,
            order_id=order.id,
            provider_account_id=account.id,
            provider_subscription_id="provider-acceptance-mismatch",
            recurring_consent_acceptance_id=other_acceptance.id,
            occurred_at=now,
        ),
        expected_error="recurring_consent_invalid",
    )
    assert order.metadata_["recurring_consent_acceptance_id"] == str(acceptance.id)


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
        requested_at=now,
        succeeded_at=now,
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

    entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == subscription.id).one()
    assert result.status == SubscriptionStatus.REFUNDED.value
    assert entitlement.status == EntitlementStatus.REVOKED.value


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
        requested_at=now + timedelta(minutes=2),
        succeeded_at=now + timedelta(minutes=2),
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


def test_full_refund_of_paid_access_revokes_entitlement_and_refunds_subscription(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "paid-refund-active")
    order, payment, _ = _add_verified_paid_order(
        db_session,
        key="paid-refund-active",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    subscription, entitlement, activation_event = _add_paid_subscription_for_order(
        db_session,
        key="paid-refund-active",
        order=order,
        payment=payment,
        plan=plan,
        starts_at=now,
        ends_at=now + timedelta(days=30),
    )
    payment.status = "refunded"
    payment.refunded_amount_minor = payment.amount_minor
    refund = _add_refund(
        db_session,
        key="paid-refund-active",
        order=order,
        payment=payment,
        account=account,
        amount_minor=payment.amount_minor,
        occurred_at=now + timedelta(minutes=5),
    )

    lookup = get_subscription_for_order(db_session, order.id)
    result = apply_refund(
        db_session,
        ApplyRefundCommand(
            operation_idempotency_key="paid-refund-active-apply",
            order_id=order.id,
            refund_id=refund.id,
            amount_minor=refund.amount_minor,
            occurred_at=now + timedelta(minutes=5),
        ),
    )

    refund_event = (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.REFUND_APPLIED.value,
        )
        .one()
    )
    db_session.refresh(entitlement)
    assert lookup is not None
    assert lookup.id == subscription.id
    assert result.status == SubscriptionStatus.REFUNDED.value
    assert entitlement.status == EntitlementStatus.REVOKED.value
    assert activation_event.event_type == SubscriptionEventType.PAID_PERIOD_ACTIVATED.value
    assert refund_event.previous_status == SubscriptionStatus.ACTIVE.value
    assert refund_event.next_status == SubscriptionStatus.REFUNDED.value
    assert refund_event.order_id == order.id
    assert refund_event.refund_id == refund.id
    assert (
        db_session.query(SubscriptionEvent)
        .filter(SubscriptionEvent.event_type == SubscriptionEventType.PAID_PERIOD_ACTIVATED.value)
        .count()
        == 1
    )


def test_full_refund_of_previously_canceled_paid_order_revokes_access(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "paid-refund-canceled")
    order, payment, _ = _add_verified_paid_order(
        db_session,
        key="paid-refund-canceled",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    order.status = "canceled"
    order.canceled_at = now + timedelta(minutes=1)
    subscription, entitlement, _ = _add_paid_subscription_for_order(
        db_session,
        key="paid-refund-canceled",
        order=order,
        payment=payment,
        plan=plan,
        starts_at=now,
        ends_at=now + timedelta(days=30),
        status=SubscriptionStatus.CANCELED.value,
    )
    payment.status = "refunded"
    payment.refunded_amount_minor = payment.amount_minor
    refund = _add_refund(
        db_session,
        key="paid-refund-canceled",
        order=order,
        payment=payment,
        account=account,
        amount_minor=payment.amount_minor,
        occurred_at=now + timedelta(minutes=5),
    )

    result = apply_refund(
        db_session,
        ApplyRefundCommand(
            operation_idempotency_key="paid-refund-canceled-apply",
            order_id=order.id,
            refund_id=refund.id,
            amount_minor=refund.amount_minor,
            occurred_at=now + timedelta(minutes=5),
        ),
    )

    db_session.refresh(entitlement)
    assert result.id == subscription.id
    assert result.status == SubscriptionStatus.REFUNDED.value
    assert entitlement.status == EntitlementStatus.REVOKED.value


def test_partial_refund_of_paid_access_does_not_revoke_entitlement(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "paid-partial-refund")
    order, payment, _ = _add_verified_paid_order(
        db_session,
        key="paid-partial-refund",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    subscription, entitlement, _ = _add_paid_subscription_for_order(
        db_session,
        key="paid-partial-refund",
        order=order,
        payment=payment,
        plan=plan,
        starts_at=now,
        ends_at=now + timedelta(days=30),
    )
    payment.status = "partially_refunded"
    payment.refunded_amount_minor = payment.amount_minor // 2
    refund = _add_refund(
        db_session,
        key="paid-partial-refund",
        order=order,
        payment=payment,
        account=account,
        amount_minor=payment.refunded_amount_minor,
        occurred_at=now + timedelta(minutes=5),
    )

    result = apply_refund(
        db_session,
        ApplyRefundCommand(
            operation_idempotency_key="paid-partial-refund-apply",
            order_id=order.id,
            refund_id=refund.id,
            amount_minor=refund.amount_minor,
            occurred_at=now + timedelta(minutes=5),
        ),
    )

    event = (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.PARTIAL_REFUND_APPLIED.value,
        )
        .one()
    )
    db_session.refresh(entitlement)
    assert result.status == SubscriptionStatus.ACTIVE.value
    assert entitlement.status == EntitlementStatus.ACTIVE.value
    assert event.order_id == order.id
    assert event.refund_id == refund.id


def test_missing_subscription_event_for_paid_refund_is_not_swallowed(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "paid-refund-missing-subscription")
    order, payment, _ = _add_verified_paid_order(
        db_session,
        key="paid-refund-missing-subscription",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    payment.status = "refunded"
    payment.refunded_amount_minor = payment.amount_minor
    refund = _add_refund(
        db_session,
        key="paid-refund-missing-subscription",
        order=order,
        payment=payment,
        account=account,
        amount_minor=payment.amount_minor,
        occurred_at=now + timedelta(minutes=5),
    )

    with pytest.raises(SubscriptionLifecycleError, match="subscription_not_found_for_order"):
        apply_refund(
            db_session,
            ApplyRefundCommand(
                operation_idempotency_key="paid-refund-missing-subscription-apply",
                order_id=order.id,
                refund_id=refund.id,
                amount_minor=refund.amount_minor,
                occurred_at=now + timedelta(minutes=5),
            ),
        )


def test_paid_orders_create_distinct_entitlements_and_refund_uses_order_provenance(db_session) -> None:
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
    first_paid_entitlements = (
        db_session.query(Entitlement).filter(Entitlement.subscription_id == first_subscription.id).all()
    )
    assert len(first_paid_entitlements) == 1
    assert first_paid_entitlements[0].order_id == first_order.id
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
    entitlements = (
        db_session.query(Entitlement)
        .filter(Entitlement.subscription_id == first_subscription.id)
        .order_by(Entitlement.valid_from.asc())
        .all()
    )
    assert len(entitlements) == 2
    first_entitlement, second_entitlement = entitlements
    assert first_entitlement.order_id == first_order.id
    assert second_entitlement.order_id == second_order.id
    assert first_entitlement.valid_until == second_entitlement.valid_from

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
        requested_at=now + timedelta(days=2),
        succeeded_at=now + timedelta(days=2),
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

    db_session.refresh(first_entitlement)
    db_session.refresh(second_entitlement)
    assert result.status == SubscriptionStatus.ACTIVE.value
    assert first_entitlement.status == EntitlementStatus.REVOKED.value
    assert first_entitlement.order_id == first_order.id
    assert second_entitlement.status == EntitlementStatus.ACTIVE.value
    assert second_entitlement.order_id == second_order.id


@pytest.mark.parametrize(
    ("case", "plan_tenant_id", "plan_region"),
    (
        ("tenant", "foreign-tenant", "ru"),
        ("region", "anytoolai", "eu"),
    ),
)
def test_activate_paid_period_rejects_order_plan_scope_mismatch_without_mutation(
    db_session,
    case: str,
    plan_tenant_id: str,
    plan_region: str,
) -> None:
    now = datetime.now(timezone.utc)
    source_plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert source_plan is not None
    mismatched_plan = Plan(
        tenant_id=plan_tenant_id,
        region=plan_region,
        code=f"paid-order-scope-mismatch-{case}",
        name=f"Paid Order Scope Mismatch {case.title()}",
        scope_type=source_plan.scope_type,
        product_id=source_plan.product_id,
        bundle_id=source_plan.bundle_id,
        price_amount_minor=source_plan.price_amount_minor,
        currency=source_plan.currency,
        billing_period=source_plan.billing_period,
        renewal_mode=source_plan.renewal_mode,
        trial_days=source_plan.trial_days,
        status=source_plan.status,
        valid_from=now,
    )
    db_session.add(mismatched_plan)
    db_session.flush()
    user, account = _add_billing_user_and_account(db_session, f"paid-order-scope-mismatch-{case}")
    order, payment, webhook = _add_verified_paid_order(
        db_session,
        key=f"paid-order-scope-mismatch-{case}",
        user=user,
        account=account,
        plan=source_plan,
        paid_at=now,
    )
    order.plan_id = mismatched_plan.id
    db_session.flush()
    operation_key = f"paid-order-scope-mismatch-{case}-activate"

    with pytest.raises(SubscriptionLifecycleError, match="order_plan_missing"):
        activate_paid_period(
            db_session,
            ActivatePaidPeriodCommand(
                operation_idempotency_key=operation_key,
                order_id=order.id,
                payment_id=payment.id,
                webhook_event_id=webhook.id,
                occurred_at=now,
            ),
        )

    _assert_no_paid_activation_access_mutation(db_session, user=user, order=order, operation_key=operation_key)


def test_activate_paid_period_preserves_missing_order_plan_without_mutation(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "missing-order-plan")
    order, payment, webhook = _add_verified_paid_order(
        db_session,
        key="missing-order-plan",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    order.plan_id = None
    db_session.flush()
    assert (
        db_session.query(OrderItem).filter(OrderItem.order_id == order.id, OrderItem.plan_id.is_not(None)).count() == 0
    )
    operation_key = "missing-order-plan-activate"

    with pytest.raises(SubscriptionLifecycleError, match="order_plan_missing"):
        activate_paid_period(
            db_session,
            ActivatePaidPeriodCommand(
                operation_idempotency_key=operation_key,
                order_id=order.id,
                payment_id=payment.id,
                webhook_event_id=webhook.id,
                occurred_at=now,
            ),
        )

    _assert_no_paid_activation_access_mutation(db_session, user=user, order=order, operation_key=operation_key)


@pytest.mark.postgres
def test_paid_period_after_canceled_paid_through_scope_starts_at_old_valid_until_and_is_idempotent(db_session) -> None:
    paid_at = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    paid_through = paid_at + timedelta(days=20)
    expected_new_period_end = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)
    plan = _plan_by_code(db_session, "document-summary-pro")
    user, account = _add_billing_user_and_account(db_session, "canceled-paid-through-carry-forward")
    old_order, old_payment, old_webhook = _add_verified_paid_order(
        db_session,
        key="canceled-paid-through-carry-forward-old",
        user=user,
        account=account,
        plan=plan,
        paid_at=paid_at - timedelta(days=10),
    )
    old_subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="canceled-paid-through-carry-forward-old-activate",
            order_id=old_order.id,
            payment_id=old_payment.id,
            webhook_event_id=old_webhook.id,
            occurred_at=paid_at - timedelta(days=10),
        ),
    )
    old_entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == old_subscription.id).one()
    old_subscription.status = SubscriptionStatus.CANCELED.value
    old_subscription.canceled_at = paid_at
    old_subscription.current_period_end = paid_through
    old_entitlement.valid_until = paid_through
    db_session.flush()
    new_order, new_payment, new_webhook = _add_verified_paid_order(
        db_session,
        key="canceled-paid-through-carry-forward-new",
        user=user,
        account=account,
        plan=plan,
        paid_at=paid_at,
    )
    command = ActivatePaidPeriodCommand(
        operation_idempotency_key="canceled-paid-through-carry-forward-new-activate",
        order_id=new_order.id,
        payment_id=new_payment.id,
        webhook_event_id=new_webhook.id,
        occurred_at=paid_at,
    )

    new_subscription = activate_paid_period(db_session, command)
    repeated_subscription = activate_paid_period(db_session, command)

    db_session.refresh(old_subscription)
    db_session.refresh(old_entitlement)
    new_entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == new_subscription.id).one()
    successor_event = (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == old_subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.SUBSCRIPTION_REPLACED.value,
        )
        .one()
    )
    assert old_subscription.status == SubscriptionStatus.CANCELED.value
    assert old_entitlement.status == EntitlementStatus.ACTIVE.value
    assert old_entitlement.valid_until == paid_through
    assert new_subscription.id != old_subscription.id
    assert repeated_subscription.id == new_subscription.id
    assert new_subscription.current_period_start == paid_through
    assert new_entitlement.valid_from == paid_through
    assert new_entitlement.valid_until == expected_new_period_end
    assert old_entitlement.valid_until == new_entitlement.valid_from
    assert old_entitlement.valid_until <= new_entitlement.valid_from
    assert successor_event.previous_status == SubscriptionStatus.CANCELED.value
    assert successor_event.next_status == SubscriptionStatus.CANCELED.value
    assert successor_event.metadata_ == {
        "replacement_subscription_id": str(new_subscription.id),
        "paid_through_valid_until": paid_through.isoformat(),
    }
    assert (
        db_session.query(Entitlement)
        .filter(Entitlement.order_id == new_order.id, Entitlement.subscription_id == new_subscription.id)
        .count()
        == 1
    )


@pytest.mark.postgres
def test_canceled_expired_entitlement_does_not_shift_new_paid_period(db_session) -> None:
    paid_at = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    plan = _plan_by_code(db_session, "document-summary-pro")
    user, account = _add_billing_user_and_account(db_session, "canceled-expired-history")
    old_order, old_payment, _ = _add_verified_paid_order(
        db_session,
        key="canceled-expired-history-old",
        user=user,
        account=account,
        plan=plan,
        paid_at=paid_at - timedelta(days=40),
    )
    old_subscription, old_entitlement, _ = _add_paid_subscription_for_order(
        db_session,
        key="canceled-expired-history-old",
        order=old_order,
        payment=old_payment,
        plan=plan,
        starts_at=paid_at - timedelta(days=40),
        ends_at=paid_at - timedelta(days=10),
        status=SubscriptionStatus.CANCELED.value,
    )
    old_entitlement.status = EntitlementStatus.EXPIRED.value
    old_entitlement.expired_at = paid_at - timedelta(days=10)
    new_order, new_payment, new_webhook = _add_verified_paid_order(
        db_session,
        key="canceled-expired-history-new",
        user=user,
        account=account,
        plan=plan,
        paid_at=paid_at,
    )

    new_subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="canceled-expired-history-new-activate",
            order_id=new_order.id,
            payment_id=new_payment.id,
            webhook_event_id=new_webhook.id,
            occurred_at=paid_at,
        ),
    )

    new_entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == new_subscription.id).one()
    assert old_subscription.status == SubscriptionStatus.CANCELED.value
    assert new_subscription.current_period_start == paid_at
    assert new_entitlement.valid_from == paid_at
    assert (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == old_subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.SUBSCRIPTION_REPLACED.value,
        )
        .count()
        == 0
    )


@pytest.mark.postgres
def test_canceled_paid_through_different_scope_does_not_shift_new_paid_period(db_session) -> None:
    paid_at = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    plan = _plan_by_code(db_session, "document-summary-pro")
    other_plan = _plan_by_code(db_session, "prompt-optimizer-pro")
    user, account = _add_billing_user_and_account(db_session, "canceled-other-scope")
    old_order, old_payment, _ = _add_verified_paid_order(
        db_session,
        key="canceled-other-scope-old",
        user=user,
        account=account,
        plan=other_plan,
        paid_at=paid_at - timedelta(days=10),
    )
    _, old_entitlement, _ = _add_paid_subscription_for_order(
        db_session,
        key="canceled-other-scope-old",
        order=old_order,
        payment=old_payment,
        plan=other_plan,
        starts_at=paid_at - timedelta(days=10),
        ends_at=paid_at + timedelta(days=20),
        status=SubscriptionStatus.CANCELED.value,
    )
    new_order, new_payment, new_webhook = _add_verified_paid_order(
        db_session,
        key="canceled-other-scope-new",
        user=user,
        account=account,
        plan=plan,
        paid_at=paid_at,
    )

    new_subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="canceled-other-scope-new-activate",
            order_id=new_order.id,
            payment_id=new_payment.id,
            webhook_event_id=new_webhook.id,
            occurred_at=paid_at,
        ),
    )

    new_entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == new_subscription.id).one()
    assert old_entitlement.status == EntitlementStatus.ACTIVE.value
    assert new_subscription.current_period_start == paid_at
    assert new_entitlement.valid_from == paid_at


@pytest.mark.postgres
def test_canceled_paid_through_uses_latest_remaining_same_scope_grant(db_session) -> None:
    paid_at = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)
    latest_paid_through = paid_at + timedelta(days=20)
    plan = _plan_by_code(db_session, "document-summary-pro")
    user, account = _add_billing_user_and_account(db_session, "canceled-multiple-history")
    subscription = Subscription(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        plan_id=plan.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        status=SubscriptionStatus.CANCELED.value,
        renewal_mode=SubscriptionRenewalMode.MANUAL.value,
        current_period_start=paid_at - timedelta(days=60),
        current_period_end=latest_paid_through,
        canceled_at=paid_at,
    )
    db_session.add(subscription)
    db_session.flush()
    for index, (starts_at, ends_at) in enumerate(
        (
            (paid_at - timedelta(days=60), paid_at - timedelta(days=30)),
            (paid_at - timedelta(days=30), paid_at + timedelta(days=5)),
            (paid_at + timedelta(days=5), latest_paid_through),
        ),
        start=1,
    ):
        old_order, _, _ = _add_verified_paid_order(
            db_session,
            key=f"canceled-multiple-history-old-{index}",
            user=user,
            account=account,
            plan=plan,
            paid_at=starts_at,
        )
        db_session.add(
            Entitlement(
                tenant_id=user.tenant_id,
                region=user.region,
                user_id=user.id,
                subscription_id=subscription.id,
                plan_id=plan.id,
                scope_type=plan.scope_type,
                product_id=plan.product_id,
                bundle_id=plan.bundle_id,
                status=EntitlementStatus.ACTIVE.value,
                valid_from=starts_at,
                valid_until=ends_at,
                source=EntitlementSource.ORDER.value,
                order_id=old_order.id,
            )
        )
    new_order, new_payment, new_webhook = _add_verified_paid_order(
        db_session,
        key="canceled-multiple-history-new",
        user=user,
        account=account,
        plan=plan,
        paid_at=paid_at,
    )

    new_subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="canceled-multiple-history-new-activate",
            order_id=new_order.id,
            payment_id=new_payment.id,
            webhook_event_id=new_webhook.id,
            occurred_at=paid_at,
        ),
    )

    entitlements = (
        db_session.query(Entitlement)
        .filter(Entitlement.user_id == user.id, Entitlement.status == EntitlementStatus.ACTIVE.value)
        .order_by(Entitlement.valid_from.asc())
        .all()
    )
    new_entitlement = next(
        entitlement for entitlement in entitlements if entitlement.subscription_id == new_subscription.id
    )
    assert subscription.status == SubscriptionStatus.CANCELED.value
    assert new_entitlement.valid_from == latest_paid_through
    assert entitlements[-2].valid_until == new_entitlement.valid_from


def test_partial_refund_records_event_without_revoking_entitlement(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "partial-refund-lifecycle")
    order, payment, webhook = _add_verified_paid_order(
        db_session,
        key="partial-refund-lifecycle",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="partial-refund-lifecycle-activate",
            order_id=order.id,
            payment_id=payment.id,
            webhook_event_id=webhook.id,
            occurred_at=now,
        ),
    )
    payment.status = "partially_refunded"
    payment.refunded_amount_minor = payment.amount_minor // 2
    refund = _add_refund(
        db_session,
        key="partial-refund-lifecycle",
        order=order,
        payment=payment,
        account=account,
        amount_minor=payment.refunded_amount_minor,
        occurred_at=now + timedelta(minutes=5),
    )

    result = apply_refund(
        db_session,
        ApplyRefundCommand(
            operation_idempotency_key="partial-refund-lifecycle-apply",
            order_id=order.id,
            refund_id=refund.id,
            amount_minor=refund.amount_minor,
            occurred_at=now + timedelta(minutes=5),
        ),
    )

    entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == subscription.id).one()
    event = (
        db_session.query(SubscriptionEvent)
        .filter(SubscriptionEvent.event_type == SubscriptionEventType.PARTIAL_REFUND_APPLIED.value)
        .one()
    )
    assert result.status == SubscriptionStatus.ACTIVE.value
    assert entitlement.status == EntitlementStatus.ACTIVE.value
    assert event.refund_id == refund.id


def test_access_query_ignores_future_entitlement_until_valid_from(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "future-access-query")
    order, payment, webhook = _add_verified_paid_order(
        db_session,
        key="future-access-query",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="future-access-query-activate",
            order_id=order.id,
            payment_id=payment.id,
            webhook_event_id=webhook.id,
            occurred_at=now,
        ),
    )
    entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == subscription.id).one()
    entitlement.valid_from = now + timedelta(days=1)
    entitlement.valid_until = now + timedelta(days=31)
    db_session.flush()

    current = get_active_entitlement_for_scope(
        db_session,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        now=now,
    )
    future_current = get_active_entitlement_for_scope(
        db_session,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        scope_type=plan.scope_type,
        product_id=plan.product_id,
        bundle_id=plan.bundle_id,
        now=now + timedelta(days=2),
    )

    assert current is None
    assert future_current is not None
    assert future_current.id == entitlement.id


def test_renewal_success_without_order_payment_webhook_is_rejected() -> None:
    with pytest.raises(ValidationError) as exc_info:
        ApplyRenewalPaymentCommand(
            operation_idempotency_key="renewal-missing-evidence",
            subscription_id=uuid.uuid4(),
            succeeded=True,
        )

    error_text = str(exc_info.value)
    assert "order_id" in error_text
    assert "payment_id" in error_text
    assert "webhook_event_id" in error_text


def test_renewal_with_mismatched_payment_order_is_rejected(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "renewal-mismatched-payment")
    first_order, first_payment, first_webhook = _add_verified_paid_order(
        db_session,
        key="renewal-mismatched-payment-initial",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="renewal-mismatched-payment-initial-activate",
            order_id=first_order.id,
            payment_id=first_payment.id,
            webhook_event_id=first_webhook.id,
            occurred_at=now,
        ),
    )
    renewal_order, renewal_payment, renewal_webhook = _add_verified_paid_order(
        db_session,
        key="renewal-mismatched-payment-renewal",
        user=user,
        account=account,
        plan=plan,
        paid_at=now + timedelta(days=1),
    )
    other_order, other_payment, _ = _add_verified_paid_order(
        db_session,
        key="renewal-mismatched-payment-other",
        user=user,
        account=account,
        plan=plan,
        paid_at=now + timedelta(days=2),
    )
    assert renewal_payment.order_id == renewal_order.id
    assert other_payment.order_id == other_order.id

    with pytest.raises(SubscriptionLifecycleError, match="payment_context_missing"):
        apply_renewal_payment(
            db_session,
            ApplyRenewalPaymentCommand(
                operation_idempotency_key="renewal-mismatched-payment-apply",
                subscription_id=subscription.id,
                succeeded=True,
                order_id=renewal_order.id,
                payment_id=other_payment.id,
                webhook_event_id=renewal_webhook.id,
                occurred_at=now + timedelta(days=1),
            ),
        )


def test_renewal_with_unprocessed_or_mismatched_webhook_is_rejected(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "renewal-webhook-evidence")
    first_order, first_payment, first_webhook = _add_verified_paid_order(
        db_session,
        key="renewal-webhook-evidence-initial",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="renewal-webhook-evidence-initial-activate",
            order_id=first_order.id,
            payment_id=first_payment.id,
            webhook_event_id=first_webhook.id,
            occurred_at=now,
        ),
    )
    renewal_order, renewal_payment, unprocessed_webhook = _add_verified_paid_order(
        db_session,
        key="renewal-webhook-evidence-unprocessed",
        user=user,
        account=account,
        plan=plan,
        paid_at=now + timedelta(days=1),
    )
    unprocessed_webhook.status = "received"
    mismatched_order, mismatched_payment, mismatched_webhook = _add_verified_paid_order(
        db_session,
        key="renewal-webhook-evidence-mismatched",
        user=user,
        account=account,
        plan=plan,
        paid_at=now + timedelta(days=2),
    )
    mismatched_webhook.order_id = renewal_order.id
    mismatched_webhook.payment_id = mismatched_payment.id
    db_session.flush()
    assert mismatched_order.id != renewal_order.id

    for key, webhook_id in (
        ("unprocessed", unprocessed_webhook.id),
        ("mismatched", mismatched_webhook.id),
    ):
        with pytest.raises(SubscriptionLifecycleError, match="verified_webhook_missing"):
            apply_renewal_payment(
                db_session,
                ApplyRenewalPaymentCommand(
                    operation_idempotency_key=f"renewal-webhook-evidence-{key}-apply",
                    subscription_id=subscription.id,
                    succeeded=True,
                    order_id=renewal_order.id,
                    payment_id=renewal_payment.id,
                    webhook_event_id=webhook_id,
                    occurred_at=now + timedelta(days=1),
                ),
            )


def test_verified_renewal_creates_entitlement_and_is_idempotent(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "verified-renewal")
    first_order, first_payment, first_webhook = _add_verified_paid_order(
        db_session,
        key="verified-renewal-initial",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="verified-renewal-initial-activate",
            order_id=first_order.id,
            payment_id=first_payment.id,
            webhook_event_id=first_webhook.id,
            occurred_at=now,
        ),
    )
    first_entitlement = db_session.query(Entitlement).filter(Entitlement.subscription_id == subscription.id).one()
    renewal_order, renewal_payment, renewal_webhook = _add_verified_paid_order(
        db_session,
        key="verified-renewal-renewal",
        user=user,
        account=account,
        plan=plan,
        paid_at=now + timedelta(days=1),
    )
    command = ApplyRenewalPaymentCommand(
        operation_idempotency_key="verified-renewal-apply",
        subscription_id=subscription.id,
        succeeded=True,
        order_id=renewal_order.id,
        payment_id=renewal_payment.id,
        webhook_event_id=renewal_webhook.id,
        occurred_at=now + timedelta(days=1),
    )

    result = apply_renewal_payment(db_session, command)
    repeated = apply_renewal_payment(db_session, command)

    entitlements = (
        db_session.query(Entitlement)
        .filter(Entitlement.subscription_id == subscription.id)
        .order_by(Entitlement.valid_from.asc())
        .all()
    )
    renewal_events = (
        db_session.query(SubscriptionEvent)
        .filter(
            SubscriptionEvent.subscription_id == subscription.id,
            SubscriptionEvent.event_type == SubscriptionEventType.RENEWAL_SUCCEEDED.value,
        )
        .all()
    )
    assert result.id == subscription.id
    assert repeated.id == subscription.id
    assert len(entitlements) == 2
    assert entitlements[0].id == first_entitlement.id
    assert entitlements[0].order_id == first_order.id
    assert entitlements[1].order_id == renewal_order.id
    assert entitlements[1].valid_from == entitlements[0].valid_until
    assert len(renewal_events) == 1
    assert renewal_events[0].order_id == renewal_order.id
    assert renewal_events[0].payment_id == renewal_payment.id
    assert renewal_events[0].webhook_event_id == renewal_webhook.id


def test_failed_renewal_requires_persisted_failure_evidence(db_session) -> None:
    now = datetime.now(timezone.utc)
    plan = (
        db_session.query(Plan)
        .filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.price_amount_minor > 0)
        .first()
    )
    assert plan is not None
    user, account = _add_billing_user_and_account(db_session, "failed-renewal-evidence")
    first_order, first_payment, first_webhook = _add_verified_paid_order(
        db_session,
        key="failed-renewal-evidence-initial",
        user=user,
        account=account,
        plan=plan,
        paid_at=now,
    )
    subscription = activate_paid_period(
        db_session,
        ActivatePaidPeriodCommand(
            operation_idempotency_key="failed-renewal-evidence-initial-activate",
            order_id=first_order.id,
            payment_id=first_payment.id,
            webhook_event_id=first_webhook.id,
            occurred_at=now,
        ),
    )
    failed_order, failed_payment, failed_webhook = _add_verified_paid_order(
        db_session,
        key="failed-renewal-evidence-renewal",
        user=user,
        account=account,
        plan=plan,
        paid_at=now + timedelta(days=1),
    )
    failed_order.status = "payment_failed"
    failed_order.paid_at = None
    failed_payment.status = "failed"
    db_session.flush()

    result = apply_renewal_payment(
        db_session,
        ApplyRenewalPaymentCommand(
            operation_idempotency_key="failed-renewal-evidence-apply",
            subscription_id=subscription.id,
            succeeded=False,
            order_id=failed_order.id,
            payment_id=failed_payment.id,
            webhook_event_id=failed_webhook.id,
            occurred_at=now + timedelta(days=1),
        ),
    )

    event = (
        db_session.query(SubscriptionEvent)
        .filter(SubscriptionEvent.event_type == SubscriptionEventType.RENEWAL_FAILED.value)
        .one()
    )
    assert result.status == SubscriptionStatus.PAST_DUE.value
    assert db_session.query(Entitlement).filter(Entitlement.subscription_id == subscription.id).count() == 1
    assert event.order_id == failed_order.id
    assert event.payment_id == failed_payment.id
    assert event.webhook_event_id == failed_webhook.id


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

    due_subscriptions: list[Subscription] = []
    for index, status in enumerate(
        (
            SubscriptionStatus.ACTIVE.value,
            SubscriptionStatus.CANCELED.value,
            SubscriptionStatus.PAST_DUE.value,
        )
    ):
        user = User(
            tenant_id="anytoolai",
            region="ru",
            email=f"expiration-lifecycle-{index}@example.com",
            email_normalized=f"expiration-lifecycle-{index}@example.com",
            status="active",
        )
        db_session.add(user)
        db_session.flush()
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

    future_user = User(
        tenant_id="anytoolai",
        region="ru",
        email="expiration-lifecycle-future@example.com",
        email_normalized="expiration-lifecycle-future@example.com",
        status="active",
    )
    db_session.add(future_user)
    db_session.flush()
    future_subscription = Subscription(
        tenant_id="anytoolai",
        region="ru",
        user_id=future_user.id,
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
    entitlements = (
        db_session.query(Entitlement)
        .filter(Entitlement.subscription_id.in_({subscription.id for subscription in due_subscriptions}))
        .all()
    )
    assert {entitlement.status for entitlement in entitlements} == {EntitlementStatus.EXPIRED.value}
    assert all(entitlement.expired_at == now for entitlement in entitlements)
    assert future_subscription.status == SubscriptionStatus.ACTIVE.value
    assert db_session.query(SubscriptionEvent).count() == 3
