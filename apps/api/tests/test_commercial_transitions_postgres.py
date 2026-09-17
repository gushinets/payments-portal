from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier, Lock, get_ident

import pytest
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.domains.billing.service import commercial_transitions
from app.domains.billing.service.commercial_transitions import (
    PaymentOutcome,
    PaymentTransitionCommand,
    RefundTransitionCommand,
    TransitionDisposition,
    apply_payment_transition,
    apply_refund_transition,
)
from app.infrastructure.persistence.commercial import establish_payment_identity
from app.models import (
    Order,
    OrderStatus,
    Payment,
    PaymentProviderAccount,
    PaymentStatus,
    Refund,
    RefundStatus,
    User,
    UserStatus,
)


pytestmark = pytest.mark.postgres

OCCURRED_AT = datetime(2026, 9, 16, 8, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _migrated_commercial_database(migrated_database: Engine) -> None:
    """Run each commercial concurrency test against migrated PostgreSQL."""


def _seed_orders(
    session_factory: sessionmaker[Session],
    *,
    key: str,
    count: int,
    status: OrderStatus = OrderStatus.PENDING_PAYMENT,
    amount_minor: int = 10_000,
    account_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, list[uuid.UUID]]:
    with session_factory() as session, session.begin():
        if account_id is None:
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
            session.add(account)
            session.flush()
        else:
            account = session.get(PaymentProviderAccount, account_id)
            assert account is not None
        order_ids = []
        for index in range(count):
            user = User(
                tenant_id="anytoolai",
                region="ru",
                email=f"{key}-{index}@example.com",
                email_normalized=f"{key}-{index}@example.com",
                status=UserStatus.ACTIVE,
            )
            session.add(user)
            session.flush()
            order = Order(
                tenant_id="anytoolai",
                region="ru",
                order_number=f"{key}-order-{index}",
                user_id=user.id,
                status=status,
                amount_minor=amount_minor,
                currency="RUB",
                provider=account.provider,
                provider_account_id=account.id,
                merchant_order_id=f"{key}-merchant-{index}",
                provider_invoice_id=f"{key}-invoice-{index}",
            )
            session.add(order)
            session.flush()
            order_ids.append(order.id)
        return account.id, order_ids


def _seed_paid_orders(
    session_factory: sessionmaker[Session],
    *,
    key: str,
    count: int,
    amount_minor: int = 10_000,
    account_id: uuid.UUID | None = None,
) -> tuple[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, str]]]:
    account_id, order_ids = _seed_orders(
        session_factory,
        key=key,
        count=count,
        status=OrderStatus.PAID,
        amount_minor=amount_minor,
        account_id=account_id,
    )
    contexts = []
    with session_factory() as session, session.begin():
        for index, order_id in enumerate(order_ids):
            order = session.get(Order, order_id)
            assert order is not None
            order.paid_at = OCCURRED_AT
            provider_payment_id = f"{key}-payment-{index}"
            payment = Payment(
                tenant_id=order.tenant_id,
                region=order.region,
                order_id=order.id,
                provider_account_id=order.provider_account_id,
                provider=order.provider,
                provider_payment_id=provider_payment_id,
                provider_invoice_id=order.provider_invoice_id,
                status=PaymentStatus.SUCCEEDED,
                amount_minor=order.amount_minor,
                currency=order.currency,
                authorized_at=OCCURRED_AT,
                captured_at=OCCURRED_AT,
                refunded_amount_minor=0,
                raw_summary={},
            )
            session.add(payment)
            session.flush()
            contexts.append((order.id, payment.id, provider_payment_id))
    return account_id, contexts


def _payment_command(
    *,
    order_id: uuid.UUID,
    account_id: uuid.UUID,
    payment_id: str,
    invoice_id: str,
) -> PaymentTransitionCommand:
    return PaymentTransitionCommand(
        order_id=order_id,
        provider="test-provider",
        provider_account_id=account_id,
        provider_payment_id=payment_id,
        provider_invoice_id=invoice_id,
        outcome=PaymentOutcome.SUCCEEDED,
        amount_minor=10_000,
        currency="RUB",
        occurred_at=OCCURRED_AT,
        payment_method_type="card",
    )


def _refund_command(
    *,
    order_id: uuid.UUID,
    account_id: uuid.UUID,
    payment_id: str,
    refund_id: str,
    amount_minor: int,
) -> RefundTransitionCommand:
    return RefundTransitionCommand(
        order_id=order_id,
        provider="test-provider",
        provider_account_id=account_id,
        provider_payment_id=payment_id,
        provider_refund_id=refund_id,
        amount_minor=amount_minor,
        currency="RUB",
        occurred_at=OCCURRED_AT,
        reason="customer_request",
    )


def _apply_payment_in_worker(
    session_factory: sessionmaker[Session],
    command: PaymentTransitionCommand,
    start: Barrier,
) -> tuple[TransitionDisposition, str | None, bool]:
    start.wait(timeout=5)
    with session_factory() as session, session.begin():
        result = apply_payment_transition(session, command)
        transaction_usable = session.query(Order).count() > 0
    return result.disposition, result.reason_code, transaction_usable


def _apply_refund_in_worker(
    session_factory: sessionmaker[Session],
    command: RefundTransitionCommand,
    start: Barrier,
) -> tuple[TransitionDisposition, str | None, bool]:
    start.wait(timeout=5)
    with session_factory() as session, session.begin():
        result = apply_refund_transition(session, command)
        transaction_usable = session.query(Order).count() > 0
    return result.disposition, result.reason_code, transaction_usable


def _run_payment_workers(
    session_factory: sessionmaker[Session],
    commands: tuple[PaymentTransitionCommand, PaymentTransitionCommand],
) -> list[tuple[TransitionDisposition, str | None, bool]]:
    start = Barrier(3)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_apply_payment_in_worker, session_factory, command, start) for command in commands]
        start.wait(timeout=5)
        return [future.result(timeout=10) for future in futures]


def _run_refund_workers(
    session_factory: sessionmaker[Session],
    commands: tuple[RefundTransitionCommand, RefundTransitionCommand],
) -> list[tuple[TransitionDisposition, str | None, bool]]:
    start = Barrier(3)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(_apply_refund_in_worker, session_factory, command, start) for command in commands]
        start.wait(timeout=5)
        return [future.result(timeout=10) for future in futures]


def _synchronize_missing_identity_lookup(
    monkeypatch: pytest.MonkeyPatch,
    *,
    attribute: str,
    identity_keyword: str,
    identity_value: str,
) -> None:
    original_lookup = getattr(commercial_transitions, attribute)
    lookup_barrier = Barrier(2)
    synchronized_threads: set[int] = set()
    synchronized_threads_lock = Lock()

    def synchronized_lookup(*args, **kwargs):
        row = original_lookup(*args, **kwargs)
        thread_id = get_ident()
        should_wait = False
        with synchronized_threads_lock:
            if kwargs.get(identity_keyword) == identity_value and row is None and thread_id not in synchronized_threads:
                synchronized_threads.add(thread_id)
                should_wait = True
        if should_wait:
            lookup_barrier.wait(timeout=5)
        return row

    monkeypatch.setattr(commercial_transitions, attribute, synchronized_lookup)


def test_concurrent_same_payment_fact_applies_once_and_preserves_timestamps(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    account_id, (order_id,) = _seed_orders(
        postgres_session_factory,
        key="same-payment",
        count=1,
    )
    command = _payment_command(
        order_id=order_id,
        account_id=account_id,
        payment_id="same-payment-identity",
        invoice_id="same-payment-invoice-0",
    )
    later_command = command.model_copy(update={"occurred_at": OCCURRED_AT + timedelta(minutes=5)})

    results = _run_payment_workers(postgres_session_factory, (command, later_command))

    with postgres_session_factory() as session:
        order = session.get(Order, order_id)
        payment = session.query(Payment).one()

    assert sorted(result[0] for result in results) == [
        TransitionDisposition.APPLIED,
        TransitionDisposition.DUPLICATE,
    ]
    assert all(result[2] for result in results)
    assert order is not None
    assert order.status is OrderStatus.PAID
    assert payment.status is PaymentStatus.SUCCEEDED
    assert order.paid_at in {command.occurred_at, later_command.occurred_at}
    assert payment.authorized_at == order.paid_at
    assert payment.captured_at == order.paid_at


def test_different_orders_racing_for_same_payment_identity_return_conflict_without_partial_state(
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id, order_ids = _seed_orders(
        postgres_session_factory,
        key="cross-order-payment",
        count=2,
    )
    provider_payment_id = "shared-payment-identity"
    commands = tuple(
        _payment_command(
            order_id=order_id,
            account_id=account_id,
            payment_id=provider_payment_id,
            invoice_id=f"cross-order-payment-invoice-{index}",
        )
        for index, order_id in enumerate(order_ids)
    )
    _synchronize_missing_identity_lookup(
        monkeypatch,
        attribute="get_payment_by_provider_identity",
        identity_keyword="provider_payment_id",
        identity_value=provider_payment_id,
    )

    results = _run_payment_workers(postgres_session_factory, commands)

    with postgres_session_factory() as session:
        payment = session.query(Payment).one()
        orders = {order.id: order for order in session.query(Order).all()}

    assert sorted(result[0] for result in results) == [
        TransitionDisposition.APPLIED,
        TransitionDisposition.CONFLICT,
    ]
    assert [result[1] for result in results].count("payment_identity_conflict") == 1
    assert all(result[2] for result in results)
    assert payment.provider_payment_id == provider_payment_id
    assert orders[payment.order_id].status is OrderStatus.PAID
    losing_order_id = next(order_id for order_id in order_ids if order_id != payment.order_id)
    assert orders[losing_order_id].status is OrderStatus.PENDING_PAYMENT
    assert orders[losing_order_id].paid_at is None


def test_concurrent_same_refund_identity_applies_once_and_replays_after_full_refund(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    account_id, (context,) = _seed_paid_orders(
        postgres_session_factory,
        key="same-refund",
        count=1,
    )
    order_id, payment_id, provider_payment_id = context
    command = _refund_command(
        order_id=order_id,
        account_id=account_id,
        payment_id=provider_payment_id,
        refund_id="same-refund-identity",
        amount_minor=10_000,
    )
    later_command = command.model_copy(update={"occurred_at": OCCURRED_AT + timedelta(minutes=5)})

    results = _run_refund_workers(postgres_session_factory, (command, later_command))

    with postgres_session_factory() as session:
        order = session.get(Order, order_id)
        payment = session.get(Payment, payment_id)
        refunds = session.query(Refund).all()

    assert sorted(result[0] for result in results) == [
        TransitionDisposition.APPLIED,
        TransitionDisposition.DUPLICATE,
    ]
    assert all(result[2] for result in results)
    assert order is not None and order.status is OrderStatus.REFUNDED
    assert payment is not None and payment.status is PaymentStatus.REFUNDED
    assert payment.refunded_amount_minor == 10_000
    assert len(refunds) == 1
    assert refunds[0].status is RefundStatus.SUCCEEDED
    assert refunds[0].requested_at in {command.occurred_at, later_command.occurred_at}
    assert refunds[0].succeeded_at == refunds[0].requested_at


@pytest.mark.parametrize(
    ("amounts", "expected_applied", "expected_refund_count"),
    (
        ((4_000, 6_000), 2, 2),
        ((6_000, 5_000), 1, 1),
    ),
)
def test_distinct_concurrent_partial_refunds_are_serialized_without_lost_update_or_over_refund(
    postgres_session_factory: sessionmaker[Session],
    amounts: tuple[int, int],
    expected_applied: int,
    expected_refund_count: int,
) -> None:
    account_id, (context,) = _seed_paid_orders(
        postgres_session_factory,
        key=f"partial-refunds-{amounts[0]}-{amounts[1]}",
        count=1,
    )
    order_id, payment_id, provider_payment_id = context
    commands = tuple(
        _refund_command(
            order_id=order_id,
            account_id=account_id,
            payment_id=provider_payment_id,
            refund_id=f"partial-refund-{index}",
            amount_minor=amount,
        )
        for index, amount in enumerate(amounts)
    )

    results = _run_refund_workers(postgres_session_factory, commands)

    with postgres_session_factory() as session:
        order = session.get(Order, order_id)
        payment = session.get(Payment, payment_id)
        refunds = session.query(Refund).all()

    assert sum(result[0] == TransitionDisposition.APPLIED for result in results) == expected_applied
    assert all(result[2] for result in results)
    assert payment is not None
    assert payment.refunded_amount_minor == sum(refund.amount_minor for refund in refunds)
    assert payment.refunded_amount_minor <= payment.amount_minor
    assert len(refunds) == expected_refund_count
    assert order is not None
    if expected_applied == 2:
        assert payment.refunded_amount_minor == 10_000
        assert payment.status is PaymentStatus.REFUNDED
        assert order.status is OrderStatus.REFUNDED
    else:
        assert payment.refunded_amount_minor in amounts
        assert payment.status is PaymentStatus.PARTIALLY_REFUNDED
        assert order.status is OrderStatus.PARTIALLY_REFUNDED
        assert [result[1] for result in results].count("refund_amount_exceeds_payment") == 1


def test_different_payments_racing_for_same_refund_identity_return_conflict_without_double_accounting(
    postgres_session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account_id, contexts = _seed_paid_orders(
        postgres_session_factory,
        key="cross-payment-refund",
        count=2,
    )
    provider_refund_id = "shared-refund-identity"
    commands = tuple(
        _refund_command(
            order_id=order_id,
            account_id=account_id,
            payment_id=provider_payment_id,
            refund_id=provider_refund_id,
            amount_minor=2_000,
        )
        for order_id, _, provider_payment_id in contexts
    )
    _synchronize_missing_identity_lookup(
        monkeypatch,
        attribute="get_refund_by_provider_identity",
        identity_keyword="provider_refund_id",
        identity_value=provider_refund_id,
    )

    results = _run_refund_workers(postgres_session_factory, commands)

    with postgres_session_factory() as session:
        refund = session.query(Refund).one()
        payments = {payment.id: payment for payment in session.query(Payment).all()}
        orders = {order.id: order for order in session.query(Order).all()}

    assert sorted(result[0] for result in results) == [
        TransitionDisposition.APPLIED,
        TransitionDisposition.CONFLICT,
    ]
    assert [result[1] for result in results].count("refund_identity_conflict") == 1
    assert all(result[2] for result in results)
    assert refund.status is RefundStatus.SUCCEEDED
    winning_payment = payments[refund.payment_id]
    assert winning_payment.refunded_amount_minor == 2_000
    assert winning_payment.status is PaymentStatus.PARTIALLY_REFUNDED
    assert orders[winning_payment.order_id].status is OrderStatus.PARTIALLY_REFUNDED
    losing_payment = next(payment for payment in payments.values() if payment.id != refund.payment_id)
    assert losing_payment.refunded_amount_minor == 0
    assert losing_payment.status is PaymentStatus.SUCCEEDED
    assert orders[losing_payment.order_id].status is OrderStatus.PAID


def test_caller_rollback_removes_applied_payment_and_refund_mutations(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    account_id, (pending_order_id,) = _seed_orders(
        postgres_session_factory,
        key="rollback-payment",
        count=1,
    )
    payment_command = _payment_command(
        order_id=pending_order_id,
        account_id=account_id,
        payment_id="rollback-payment-identity",
        invoice_id="rollback-payment-invoice-0",
    )
    with postgres_session_factory() as session:
        result = apply_payment_transition(session, payment_command)
        assert result.disposition is TransitionDisposition.APPLIED
        session.rollback()

    with postgres_session_factory() as session:
        order = session.get(Order, pending_order_id)
        assert order is not None and order.status is OrderStatus.PENDING_PAYMENT
        assert session.query(Payment).filter(Payment.order_id == pending_order_id).count() == 0

    refund_account_id, (context,) = _seed_paid_orders(
        postgres_session_factory,
        key="rollback-refund",
        count=1,
        account_id=account_id,
    )
    order_id, payment_id, provider_payment_id = context
    refund_command = _refund_command(
        order_id=order_id,
        account_id=refund_account_id,
        payment_id=provider_payment_id,
        refund_id="rollback-refund-identity",
        amount_minor=4_000,
    )
    with postgres_session_factory() as session:
        result = apply_refund_transition(session, refund_command)
        assert result.disposition is TransitionDisposition.APPLIED
        session.rollback()

    with postgres_session_factory() as session:
        order = session.get(Order, order_id)
        payment = session.get(Payment, payment_id)
        assert order is not None and order.status is OrderStatus.PAID
        assert payment is not None and payment.status is PaymentStatus.SUCCEEDED
        assert payment.refunded_amount_minor == 0
        assert session.query(Refund).filter(Refund.payment_id == payment_id).count() == 0


def test_unrelated_identity_insert_integrity_failure_is_not_swallowed(
    postgres_session_factory: sessionmaker[Session],
) -> None:
    account_id, _ = _seed_orders(
        postgres_session_factory,
        key="unrelated-integrity",
        count=1,
    )
    candidate = Payment(
        tenant_id="anytoolai",
        region="ru",
        order_id=uuid.uuid4(),
        provider_account_id=account_id,
        provider="test-provider",
        provider_payment_id="unrelated-integrity-payment",
        status=PaymentStatus.CREATED,
        amount_minor=10_000,
        currency="RUB",
        refunded_amount_minor=0,
        raw_summary={},
    )

    with postgres_session_factory() as session:
        session.begin()
        with pytest.raises(IntegrityError):
            establish_payment_identity(session, candidate)
        assert session.query(Order).count() == 1
        session.rollback()
