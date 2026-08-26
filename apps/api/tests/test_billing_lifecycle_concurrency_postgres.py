from __future__ import annotations

import time
import uuid
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock, get_ident

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.domains.billing.enums import (
    EntitlementSource,
    EntitlementStatus,
    SubscriptionEventType,
    SubscriptionRenewalMode,
    SubscriptionStatus,
)
from app.domains.billing.service import (
    ActivatePaidPeriodCommand,
    EnableAutomaticRenewalCommand,
    StartTrialCommand,
    SubscriptionLifecycleError,
    activate_paid_period,
    enable_automatic_renewal,
    start_trial,
)
from app.domains.billing.service import lifecycle_operations
from app.infrastructure.queries.identity import lock_user_by_id
from app.infrastructure.queries.subscriptions import get_subscription_by_id
from app.models import (
    DocumentAcceptance,
    DocumentVersion,
    Entitlement,
    LegalEntity,
    Order,
    Payment,
    PaymentProviderAccount,
    PaymentWebhookEvent,
    Plan,
    Subscription,
    SubscriptionEvent,
    User,
)


pytestmark = pytest.mark.postgres


@pytest.fixture(autouse=True)
def _migrated_concurrency_database(migrated_database: Engine) -> None:
    """Run each concurrency test against its own migrated PostgreSQL schema."""


def _plan_by_code(session: Session, code: str) -> Plan:
    plan = session.query(Plan).filter(Plan.tenant_id == "anytoolai", Plan.region == "ru", Plan.code == code).one()
    return plan


def _add_billing_user_and_account(session: Session, key: str) -> tuple[User, PaymentProviderAccount]:
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
        provider=f"test-provider-{key}",
        public_identifier=f"{key}-account",
        default_currency="RUB",
        enabled=True,
        test_mode=True,
        config={},
    )
    session.add_all([user, account])
    session.flush()
    return user, account


def _add_recurring_consent_acceptance(session: Session, *, user: User, key: str) -> DocumentAcceptance:
    now = datetime.now(UTC)
    entity = LegalEntity(
        tenant_id=user.tenant_id,
        region=user.region,
        name=f"{key} legal entity",
        entity_type="company",
        legal_address="Test address",
        support_email="support@example.com",
        status="active",
    )
    session.add(entity)
    session.flush()
    document = DocumentVersion(
        tenant_id=user.tenant_id,
        region=user.region,
        legal_entity_id=entity.id,
        doc_type="recurring_consent",
        version=f"{key}-v1",
        title="Согласие на рекуррентные платежи",
        url_path="/ru/recurring_consent",
        content_hash=f"sha256:{key}",
        published_at=now,
        effective_from=now,
        is_active=True,
        requires_acceptance=True,
    )
    session.add(document)
    session.flush()
    acceptance = DocumentAcceptance(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        document_version_id=document.id,
        doc_type=document.doc_type,
        version=document.version,
        acceptance_kind="recurring_consent",
        accepted_at=now,
        acceptance_text_hash=f"{key}-acceptance-hash",
        metadata_={},
    )
    session.add(acceptance)
    session.flush()
    return acceptance


def _add_verified_paid_order(
    session: Session,
    *,
    key: str,
    user: User,
    account: PaymentProviderAccount,
    plan: Plan,
    paid_at: datetime,
) -> tuple[Order, Payment, PaymentWebhookEvent]:
    order = Order(
        tenant_id=user.tenant_id,
        region=user.region,
        order_number=f"{key}-order",
        user_id=user.id,
        plan_id=plan.id,
        status="paid",
        amount_minor=plan.price_amount_minor,
        currency=plan.currency,
        provider=account.provider,
        provider_account_id=account.id,
        merchant_order_id=f"{key}-merchant-order",
        paid_at=paid_at,
    )
    session.add(order)
    session.flush()
    payment = Payment(
        tenant_id=order.tenant_id,
        region=order.region,
        order_id=order.id,
        provider_account_id=account.id,
        provider=account.provider,
        provider_payment_id=f"{key}-payment",
        status="succeeded",
        amount_minor=order.amount_minor,
        currency=order.currency,
        refunded_amount_minor=0,
        raw_summary={},
    )
    session.add(payment)
    session.flush()
    webhook = PaymentWebhookEvent(
        tenant_id=order.tenant_id,
        region=order.region,
        provider_account_id=account.id,
        provider=account.provider,
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
    session.add(webhook)
    session.flush()
    return order, payment, webhook


def _seed_paid_orders(
    session_factory: sessionmaker[Session],
    *,
    key: str,
    plan_codes: tuple[str, ...],
    paid_at: datetime,
) -> tuple[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, uuid.UUID]]]:
    with session_factory() as session, session.begin():
        user, account = _add_billing_user_and_account(session, key)
        order_contexts = []
        for index, plan_code in enumerate(plan_codes, start=1):
            plan = _plan_by_code(session, plan_code)
            order, payment, webhook = _add_verified_paid_order(
                session,
                key=f"{key}-{index}",
                user=user,
                account=account,
                plan=plan,
                paid_at=paid_at + timedelta(minutes=index),
            )
            order_contexts.append((order.id, payment.id, webhook.id))
        return user.id, order_contexts


def _with_user_lock_released_after_workers_start(
    session_factory: sessionmaker[Session],
    *,
    user_id: uuid.UUID,
    workers: int,
    submit,
) -> list:
    blocker = session_factory()
    blocker.begin()
    try:
        assert lock_user_by_id(blocker, user_id) is not None
        start_barrier = Barrier(workers + 1)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(submit, start_barrier, index) for index in range(workers)]
            start_barrier.wait(timeout=5)
            time.sleep(0.1)
            blocker.commit()
            return [future.result(timeout=10) for future in futures]
    finally:
        if blocker.in_transaction():
            blocker.rollback()
        blocker.close()


def _activate_in_worker(
    session_factory: sessionmaker[Session],
    command: ActivatePaidPeriodCommand,
) -> uuid.UUID:
    with session_factory() as session:
        return activate_paid_period(session, command).id


def _start_trial_in_worker(
    session_factory: sessionmaker[Session],
    command: StartTrialCommand,
) -> tuple[str, uuid.UUID | str]:
    with session_factory() as session:
        try:
            subscription = start_trial(session, command)
        except SubscriptionLifecycleError as exc:
            return "error", str(exc)
        return "ok", subscription.id


def test_parallel_enable_automatic_renewal_same_key_reuses_event_after_subscription_lock(
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 25, 14, 0, tzinfo=UTC)
    with postgres_session_factory() as session, session.begin():
        user, account = _add_billing_user_and_account(session, "concurrent-enable-automatic-renewal")
        plan = _plan_by_code(session, "document-summary-pro")
        plan.renewal_mode = SubscriptionRenewalMode.AUTOMATIC.value
        acceptance = _add_recurring_consent_acceptance(
            session,
            user=user,
            key="concurrent-enable-automatic-renewal",
        )
        subscription = Subscription(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=SubscriptionStatus.ACTIVE.value,
            renewal_mode=SubscriptionRenewalMode.MANUAL.value,
            current_period_start=now,
            current_period_end=now + timedelta(days=30),
        )
        session.add(subscription)
        session.flush()
        subscription_id = subscription.id
        provider_account_id = account.id
        acceptance_id = acceptance.id

    command = EnableAutomaticRenewalCommand(
        operation_idempotency_key="concurrent-enable-automatic-renewal",
        subscription_id=subscription_id,
        provider_account_id=provider_account_id,
        provider_subscription_id="provider-concurrent-enable-automatic-renewal",
        recurring_consent_acceptance_id=acceptance_id,
        occurred_at=now,
    )
    subscription_lock_hold_seconds = 0.2
    event_check_barrier = Barrier(3)
    original_event_for_key = lifecycle_operations._event_for_key
    synchronized_threads: set[int] = set()
    synchronized_threads_lock = Lock()

    def synchronized_event_for_key(session: Session, key: str) -> SubscriptionEvent | None:
        event = original_event_for_key(session, key)
        thread_id = get_ident()
        should_wait = False
        with synchronized_threads_lock:
            if key == command.operation_idempotency_key and event is None and thread_id not in synchronized_threads:
                synchronized_threads.add(thread_id)
                should_wait = True
        if should_wait:
            event_check_barrier.wait(timeout=5)
        return event

    monkeypatch.setattr(lifecycle_operations, "_event_for_key", synchronized_event_for_key)

    def submit(barrier: Barrier, _index: int) -> tuple[uuid.UUID, float]:
        barrier.wait(timeout=5)
        started_at = time.monotonic()
        with postgres_session_factory() as session:
            result = enable_automatic_renewal(session, command)
        return result.id, time.monotonic() - started_at

    blocker = postgres_session_factory()
    blocker.begin()
    try:
        assert get_subscription_by_id(blocker, subscription_id, for_update=True) is not None
        start_barrier = Barrier(3)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit, start_barrier, index) for index in range(2)]
            start_barrier.wait(timeout=5)
            event_check_barrier.wait(timeout=5)
            time.sleep(subscription_lock_hold_seconds)
            blocker.commit()
            results = [future.result(timeout=10) for future in futures]
    finally:
        if blocker.in_transaction():
            blocker.rollback()
        blocker.close()

    with postgres_session_factory() as session:
        refreshed_subscription = session.get(Subscription, subscription_id)
        events = (
            session.query(SubscriptionEvent)
            .filter(
                SubscriptionEvent.subscription_id == subscription_id,
                SubscriptionEvent.event_type == SubscriptionEventType.AUTOMATIC_RENEWAL_ENABLED.value,
            )
            .all()
        )
        operation_key_count = (
            session.query(SubscriptionEvent)
            .filter(SubscriptionEvent.operation_idempotency_key == command.operation_idempotency_key)
            .count()
        )

    assert {result[0] for result in results} == {subscription_id}
    assert len(synchronized_threads) == 2
    assert all(elapsed >= subscription_lock_hold_seconds for _, elapsed in results)
    assert refreshed_subscription is not None
    assert refreshed_subscription.renewal_mode == SubscriptionRenewalMode.AUTOMATIC.value
    assert refreshed_subscription.provider_account_id == provider_account_id
    assert refreshed_subscription.provider_subscription_id == command.provider_subscription_id
    assert refreshed_subscription.recurring_consent_acceptance_id == acceptance_id
    assert len(events) == 1
    assert operation_key_count == 1


def test_parallel_paid_orders_same_scope_share_one_subscription(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 25, 10, 0, tzinfo=UTC)
    user_id, order_contexts = _seed_paid_orders(
        postgres_session_factory,
        key="concurrent-paid-same-scope",
        plan_codes=("document-summary-pro", "document-summary-pro"),
        paid_at=now,
    )
    commands = [
        ActivatePaidPeriodCommand(
            operation_idempotency_key=f"concurrent-paid-same-scope-{index}",
            order_id=order_id,
            payment_id=payment_id,
            webhook_event_id=webhook_id,
            occurred_at=now + timedelta(minutes=index),
        )
        for index, (order_id, payment_id, webhook_id) in enumerate(order_contexts, start=1)
    ]

    def submit(barrier: Barrier, index: int) -> uuid.UUID:
        barrier.wait(timeout=5)
        return _activate_in_worker(postgres_session_factory, commands[index])

    subscription_ids = _with_user_lock_released_after_workers_start(
        postgres_session_factory,
        user_id=user_id,
        workers=2,
        submit=submit,
    )

    order_ids = tuple(context[0] for context in order_contexts)
    with postgres_session_factory() as session:
        subscriptions = (
            session.query(Subscription)
            .filter(Subscription.user_id == user_id, Subscription.status.in_(SubscriptionStatus.live_values()))
            .all()
        )
        events = (
            session.query(SubscriptionEvent)
            .filter(
                SubscriptionEvent.event_type == SubscriptionEventType.PAID_PERIOD_ACTIVATED.value,
                SubscriptionEvent.order_id.in_(order_ids),
            )
            .all()
        )
        entitlements = (
            session.query(Entitlement)
            .filter(Entitlement.order_id.in_(order_ids))
            .order_by(Entitlement.valid_from.asc())
            .all()
        )

    assert len(set(subscription_ids)) == 1
    assert len(subscriptions) == 1
    assert len(events) == 2
    assert {event.subscription_id for event in events} == {subscriptions[0].id}
    assert len(entitlements) == 2
    assert {entitlement.order_id for entitlement in entitlements} == set(order_ids)
    assert {entitlement.subscription_id for entitlement in entitlements} == {subscriptions[0].id}
    assert entitlements[0].valid_until == entitlements[1].valid_from


def test_parallel_paid_orders_same_plan_different_users_do_not_wait_on_plan_lock(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 25, 10, 30, tzinfo=UTC)
    with postgres_session_factory() as session, session.begin():
        plan = _plan_by_code(session, "document-summary-pro")
        user_one, account_one = _add_billing_user_and_account(session, "concurrent-same-plan-user-one")
        user_two, account_two = _add_billing_user_and_account(session, "concurrent-same-plan-user-two")
        first_order, first_payment, first_webhook = _add_verified_paid_order(
            session,
            key="concurrent-same-plan-user-one",
            user=user_one,
            account=account_one,
            plan=plan,
            paid_at=now,
        )
        second_order, second_payment, second_webhook = _add_verified_paid_order(
            session,
            key="concurrent-same-plan-user-two",
            user=user_two,
            account=account_two,
            plan=plan,
            paid_at=now + timedelta(minutes=1),
        )
        plan_id = plan.id
        order_contexts = (
            (first_order.id, first_payment.id, first_webhook.id),
            (second_order.id, second_payment.id, second_webhook.id),
        )
    commands = [
        ActivatePaidPeriodCommand(
            operation_idempotency_key=f"concurrent-same-plan-different-users-{index}",
            order_id=order_id,
            payment_id=payment_id,
            webhook_event_id=webhook_id,
            occurred_at=now + timedelta(minutes=index),
        )
        for index, (order_id, payment_id, webhook_id) in enumerate(order_contexts, start=1)
    ]

    def submit(barrier: Barrier, index: int) -> uuid.UUID:
        barrier.wait(timeout=5)
        return _activate_in_worker(postgres_session_factory, commands[index])

    blocker = postgres_session_factory()
    blocker.begin()
    try:
        assert blocker.query(Plan).filter(Plan.id == plan_id).with_for_update().one() is not None
        start_barrier = Barrier(3)
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(submit, start_barrier, index) for index in range(2)]
            start_barrier.wait(timeout=5)
            completed, not_done = wait(futures, timeout=2)
            if not_done:
                blocker.rollback()
            assert len(completed) == len(futures)
            results = [future.result() for future in futures]
    finally:
        if blocker.in_transaction():
            blocker.rollback()
        blocker.close()

    assert len(set(results)) == 2


def test_parallel_trials_same_scope_create_one_trial(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 25, 11, 0, tzinfo=UTC)
    with postgres_session_factory() as session, session.begin():
        user, _ = _add_billing_user_and_account(session, "concurrent-trial-same-scope")
        plan = _plan_by_code(session, "document-summary-pro")
        user_id = user.id
        plan_id = plan.id
    commands = [
        StartTrialCommand(
            tenant_id="anytoolai",
            region="ru",
            user_id=user_id,
            plan_id=plan_id,
            operation_idempotency_key=f"concurrent-trial-same-scope-{index}",
            occurred_at=now + timedelta(minutes=index),
        )
        for index in range(2)
    ]

    def submit(barrier: Barrier, index: int) -> tuple[str, uuid.UUID | str]:
        barrier.wait(timeout=5)
        return _start_trial_in_worker(postgres_session_factory, commands[index])

    results = _with_user_lock_released_after_workers_start(
        postgres_session_factory,
        user_id=user_id,
        workers=2,
        submit=submit,
    )

    with postgres_session_factory() as session:
        trial_subscriptions = (
            session.query(Subscription)
            .filter(
                Subscription.user_id == user_id,
                Subscription.status == SubscriptionStatus.TRIALING.value,
            )
            .all()
        )
        trial_entitlements = (
            session.query(Entitlement)
            .filter(
                Entitlement.user_id == user_id,
                Entitlement.source == EntitlementSource.TRIAL.value,
            )
            .all()
        )

    assert sorted(result[0] for result in results) == ["error", "ok"]
    assert {result[1] for result in results if result[0] == "error"} == {"trial_already_used_for_scope"}
    assert len(trial_subscriptions) == 1
    assert len(trial_entitlements) == 1
    assert trial_entitlements[0].subscription_id == trial_subscriptions[0].id


def test_parallel_paid_orders_different_scopes_create_two_subscriptions(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    user_id, order_contexts = _seed_paid_orders(
        postgres_session_factory,
        key="concurrent-paid-different-scopes",
        plan_codes=("document-summary-pro", "prompt-optimizer-pro"),
        paid_at=now,
    )
    commands = [
        ActivatePaidPeriodCommand(
            operation_idempotency_key=f"concurrent-paid-different-scopes-{index}",
            order_id=order_id,
            payment_id=payment_id,
            webhook_event_id=webhook_id,
            occurred_at=now + timedelta(minutes=index),
        )
        for index, (order_id, payment_id, webhook_id) in enumerate(order_contexts, start=1)
    ]

    def submit(barrier: Barrier, index: int) -> uuid.UUID:
        barrier.wait(timeout=5)
        return _activate_in_worker(postgres_session_factory, commands[index])

    subscription_ids = _with_user_lock_released_after_workers_start(
        postgres_session_factory,
        user_id=user_id,
        workers=2,
        submit=submit,
    )

    with postgres_session_factory() as session:
        subscriptions = (
            session.query(Subscription)
            .filter(Subscription.user_id == user_id, Subscription.status.in_(SubscriptionStatus.live_values()))
            .all()
        )
        entitlements = session.query(Entitlement).filter(Entitlement.user_id == user_id).all()

    assert len(set(subscription_ids)) == 2
    assert len(subscriptions) == 2
    assert len(entitlements) == 2
    assert {subscription.product_id for subscription in subscriptions} == {
        entitlement.product_id for entitlement in entitlements
    }


def test_terminal_subscription_allows_new_subscription_same_scope(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
    with postgres_session_factory() as session, session.begin():
        user, account = _add_billing_user_and_account(session, "terminal-then-new-same-scope")
        plan = _plan_by_code(session, "document-summary-pro")
        terminal = Subscription(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=SubscriptionStatus.CANCELED.value,
            renewal_mode=SubscriptionRenewalMode.MANUAL.value,
            current_period_start=now - timedelta(days=30),
            current_period_end=now - timedelta(days=1),
            canceled_at=now - timedelta(days=1),
        )
        session.add(terminal)
        session.flush()
        order, payment, webhook = _add_verified_paid_order(
            session,
            key="terminal-then-new-same-scope",
            user=user,
            account=account,
            plan=plan,
            paid_at=now,
        )
        user_id = user.id
        terminal_id = terminal.id
        command = ActivatePaidPeriodCommand(
            operation_idempotency_key="terminal-then-new-same-scope-activate",
            order_id=order.id,
            payment_id=payment.id,
            webhook_event_id=webhook.id,
            occurred_at=now,
        )

    with postgres_session_factory() as session:
        new_subscription = activate_paid_period(session, command)
        new_subscription_id = new_subscription.id

    with postgres_session_factory() as session:
        subscriptions = session.query(Subscription).filter(Subscription.user_id == user_id).all()
        live_count = (
            session.query(Subscription)
            .filter(Subscription.user_id == user_id, Subscription.status.in_(SubscriptionStatus.live_values()))
            .count()
        )

    assert len(subscriptions) == 2
    assert live_count == 1
    assert new_subscription_id != terminal_id


def test_parallel_paid_orders_after_canceled_paid_through_create_one_successor_subscription(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    now = datetime(2026, 8, 25, 13, 30, tzinfo=UTC)
    paid_through = now + timedelta(days=20)
    with postgres_session_factory() as session, session.begin():
        user, account = _add_billing_user_and_account(session, "concurrent-canceled-paid-through")
        plan = _plan_by_code(session, "document-summary-pro")
        old_order, _, _ = _add_verified_paid_order(
            session,
            key="concurrent-canceled-paid-through-old",
            user=user,
            account=account,
            plan=plan,
            paid_at=now - timedelta(days=10),
        )
        old_subscription = Subscription(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=SubscriptionStatus.CANCELED.value,
            renewal_mode=SubscriptionRenewalMode.MANUAL.value,
            current_period_start=now - timedelta(days=10),
            current_period_end=paid_through,
            canceled_at=now,
        )
        session.add(old_subscription)
        session.flush()
        old_entitlement = Entitlement(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            subscription_id=old_subscription.id,
            plan_id=plan.id,
            scope_type=plan.scope_type,
            product_id=plan.product_id,
            bundle_id=plan.bundle_id,
            status=EntitlementStatus.ACTIVE.value,
            valid_from=now - timedelta(days=10),
            valid_until=paid_through,
            source=EntitlementSource.ORDER.value,
            order_id=old_order.id,
        )
        session.add(old_entitlement)
        order_contexts = []
        for index in range(2):
            order, payment, webhook = _add_verified_paid_order(
                session,
                key=f"concurrent-canceled-paid-through-new-{index}",
                user=user,
                account=account,
                plan=plan,
                paid_at=now + timedelta(minutes=index),
            )
            order_contexts.append((order.id, payment.id, webhook.id))
        user_id = user.id
        old_subscription_id = old_subscription.id
        old_entitlement_id = old_entitlement.id
    commands = [
        ActivatePaidPeriodCommand(
            operation_idempotency_key=f"concurrent-canceled-paid-through-activate-{index}",
            order_id=order_id,
            payment_id=payment_id,
            webhook_event_id=webhook_id,
            occurred_at=now + timedelta(minutes=index),
        )
        for index, (order_id, payment_id, webhook_id) in enumerate(order_contexts)
    ]

    def submit(barrier: Barrier, index: int) -> uuid.UUID:
        barrier.wait(timeout=5)
        return _activate_in_worker(postgres_session_factory, commands[index])

    subscription_ids = _with_user_lock_released_after_workers_start(
        postgres_session_factory,
        user_id=user_id,
        workers=2,
        submit=submit,
    )

    order_ids = tuple(context[0] for context in order_contexts)
    with postgres_session_factory() as session:
        old_subscription = session.get(Subscription, old_subscription_id)
        old_entitlement = session.get(Entitlement, old_entitlement_id)
        live_subscriptions = (
            session.query(Subscription)
            .filter(Subscription.user_id == user_id, Subscription.status.in_(SubscriptionStatus.live_values()))
            .all()
        )
        new_entitlements = (
            session.query(Entitlement)
            .filter(Entitlement.order_id.in_(order_ids))
            .order_by(Entitlement.valid_from.asc())
            .all()
        )
        events = (
            session.query(SubscriptionEvent)
            .filter(
                SubscriptionEvent.event_type == SubscriptionEventType.PAID_PERIOD_ACTIVATED.value,
                SubscriptionEvent.order_id.in_(order_ids),
            )
            .all()
        )

    assert len(set(subscription_ids)) == 1
    assert old_subscription is not None
    assert old_subscription.status == SubscriptionStatus.CANCELED.value
    assert old_entitlement is not None
    assert old_entitlement.status == EntitlementStatus.ACTIVE.value
    assert old_entitlement.valid_until == paid_through
    assert len(live_subscriptions) == 1
    assert live_subscriptions[0].id in set(subscription_ids)
    assert len(new_entitlements) == 2
    assert {entitlement.subscription_id for entitlement in new_entitlements} == {live_subscriptions[0].id}
    assert new_entitlements[0].valid_from == paid_through
    assert old_entitlement.valid_until == new_entitlements[0].valid_from
    assert new_entitlements[0].valid_until == new_entitlements[1].valid_from
    assert len(events) == 2
