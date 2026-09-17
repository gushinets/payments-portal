from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.domains.billing.service.commercial_transitions import (
    PaymentOutcome,
    PaymentTransitionCommand,
    RefundTransitionCommand,
    TransitionDisposition,
    apply_payment_transition,
    apply_refund_transition,
)
from app.models import (
    Entitlement,
    Order,
    OrderStatus,
    Payment,
    PaymentProviderAccount,
    PaymentStatus,
    Refund,
    RefundStatus,
    Subscription,
    User,
    UserStatus,
)


OCCURRED_AT = datetime(2026, 9, 16, 8, 0, tzinfo=timezone.utc)


def _seed_order(
    db: Session,
    *,
    key: str,
    status: OrderStatus = OrderStatus.PENDING_PAYMENT,
    amount_minor: int = 10_000,
    currency: str = "RUB",
    account: PaymentProviderAccount | None = None,
    provider_invoice_id: str | None = None,
    expires_at: datetime | None = None,
) -> tuple[Order, PaymentProviderAccount]:
    user = User(
        tenant_id="anytoolai",
        region="ru",
        email=f"{key}@example.com",
        email_normalized=f"{key}@example.com",
        status=UserStatus.ACTIVE,
    )
    db.add(user)
    db.flush()
    if account is None:
        account = PaymentProviderAccount(
            tenant_id="anytoolai",
            region="ru",
            provider="test-provider",
            public_identifier=f"{key}-account",
            default_currency=currency,
            enabled=True,
            test_mode=True,
            config={},
        )
        db.add(account)
        db.flush()
    order = Order(
        tenant_id="anytoolai",
        region="ru",
        order_number=f"{key}-order",
        user_id=user.id,
        status=status,
        amount_minor=amount_minor,
        currency=currency,
        provider=account.provider,
        provider_account_id=account.id,
        merchant_order_id=f"{key}-merchant",
        provider_invoice_id=provider_invoice_id,
        expires_at=expires_at,
    )
    db.add(order)
    db.flush()
    return order, account


def _payment_command(
    order: Order,
    *,
    payment_id: str,
    outcome: PaymentOutcome,
    occurred_at: datetime = OCCURRED_AT,
    amount_minor: int | None = None,
    currency: str | None = None,
    provider: str | None = None,
    provider_account_id: uuid.UUID | None = None,
    provider_invoice_id: str | None = None,
) -> PaymentTransitionCommand:
    return PaymentTransitionCommand(
        order_id=order.id,
        provider=provider or order.provider,
        provider_account_id=provider_account_id or order.provider_account_id,
        provider_payment_id=payment_id,
        provider_invoice_id=provider_invoice_id,
        outcome=outcome,
        amount_minor=amount_minor if amount_minor is not None else order.amount_minor,
        currency=currency or order.currency,
        occurred_at=occurred_at,
        failure_code="declined" if outcome == PaymentOutcome.FAILED else None,
        failure_message_safe="Payment declined" if outcome == PaymentOutcome.FAILED else None,
        payment_method_type="card",
    )


def _refund_command(
    order: Order,
    payment: Payment,
    *,
    refund_id: str,
    amount_minor: int,
    occurred_at: datetime = OCCURRED_AT,
) -> RefundTransitionCommand:
    assert payment.provider_payment_id is not None
    return RefundTransitionCommand(
        order_id=order.id,
        provider=order.provider,
        provider_account_id=order.provider_account_id,
        provider_payment_id=payment.provider_payment_id,
        provider_refund_id=refund_id,
        amount_minor=amount_minor,
        currency=payment.currency,
        occurred_at=occurred_at,
        reason="customer_request",
    )


def _add_payment(
    db: Session,
    order: Order,
    *,
    payment_id: str,
    status: PaymentStatus,
    amount_minor: int | None = None,
    refunded_amount_minor: int = 0,
    occurred_at: datetime = OCCURRED_AT,
) -> Payment:
    payment = Payment(
        tenant_id=order.tenant_id,
        region=order.region,
        order_id=order.id,
        provider_account_id=order.provider_account_id,
        provider=order.provider,
        provider_payment_id=payment_id,
        provider_invoice_id=order.provider_invoice_id,
        status=status,
        amount_minor=amount_minor if amount_minor is not None else order.amount_minor,
        currency=order.currency,
        authorized_at=occurred_at if status in {PaymentStatus.AUTHORIZED, PaymentStatus.SUCCEEDED} else None,
        captured_at=occurred_at if status == PaymentStatus.SUCCEEDED else None,
        failed_at=occurred_at if status == PaymentStatus.FAILED else None,
        refunded_amount_minor=refunded_amount_minor,
        raw_summary={},
    )
    db.add(payment)
    db.flush()
    return payment


def test_commercial_commands_forbid_extra_fields_and_naive_occurrence() -> None:
    order_id = uuid.uuid4()
    account_id = uuid.uuid4()
    with pytest.raises(ValidationError):
        PaymentTransitionCommand(
            order_id=order_id,
            provider="test-provider",
            provider_account_id=account_id,
            provider_payment_id="payment-1",
            outcome=PaymentOutcome.SUCCEEDED,
            amount_minor=100,
            currency="RUB",
            occurred_at=datetime(2026, 9, 16, 8, 0),
        )
    with pytest.raises(ValidationError):
        RefundTransitionCommand(
            order_id=order_id,
            provider="test-provider",
            provider_account_id=account_id,
            provider_payment_id="payment-1",
            provider_refund_id="refund-1",
            amount_minor=100,
            currency="RUB",
            occurred_at=OCCURRED_AT,
            provider_payload={"Status": "Completed"},
        )


@pytest.mark.parametrize(
    ("outcome", "payment_status", "order_status", "timestamp_field", "order_timestamp_field"),
    (
        (PaymentOutcome.AUTHORIZED, PaymentStatus.AUTHORIZED, OrderStatus.PENDING_PAYMENT, "authorized_at", None),
        (PaymentOutcome.SUCCEEDED, PaymentStatus.SUCCEEDED, OrderStatus.PAID, "captured_at", "paid_at"),
        (PaymentOutcome.FAILED, PaymentStatus.FAILED, OrderStatus.PAYMENT_FAILED, "failed_at", "failed_at"),
        (PaymentOutcome.CANCELED, PaymentStatus.CANCELED, OrderStatus.CANCELED, None, "canceled_at"),
    ),
)
def test_new_payment_outcomes_apply_canonical_states_and_timestamps(
    db_session: Session,
    outcome: PaymentOutcome,
    payment_status: PaymentStatus,
    order_status: OrderStatus,
    timestamp_field: str | None,
    order_timestamp_field: str | None,
) -> None:
    order, _ = _seed_order(db_session, key=f"new-{outcome.value}")

    result = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id=f"payment-{outcome.value}", outcome=outcome),
    )

    payment = db_session.get(Payment, result.payment_id)
    assert payment is not None
    assert result.disposition == TransitionDisposition.APPLIED
    assert payment.status == payment_status
    assert order.status == order_status
    assert payment.raw_summary == {}
    if timestamp_field is not None:
        assert getattr(payment, timestamp_field) == OCCURRED_AT
    if outcome == PaymentOutcome.SUCCEEDED:
        assert payment.authorized_at == OCCURRED_AT
        assert result.order_became_paid is True
    if order_timestamp_field is not None:
        assert getattr(order, order_timestamp_field) == OCCURRED_AT


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    (
        (PaymentOutcome.SUCCEEDED, PaymentStatus.SUCCEEDED),
        (PaymentOutcome.FAILED, PaymentStatus.FAILED),
        (PaymentOutcome.CANCELED, PaymentStatus.CANCELED),
    ),
)
def test_authorized_payment_progresses_to_supported_outcome(
    db_session: Session,
    outcome: PaymentOutcome,
    expected_status: PaymentStatus,
) -> None:
    order, _ = _seed_order(db_session, key=f"authorized-{outcome.value}")
    authorized_at = OCCURRED_AT - timedelta(hours=1)
    first = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.AUTHORIZED, occurred_at=authorized_at),
    )

    result = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=outcome),
    )

    payment = db_session.get(Payment, first.payment_id)
    assert payment is not None
    assert result.disposition == TransitionDisposition.APPLIED
    assert payment.status == expected_status
    assert payment.authorized_at == authorized_at


def test_exact_payment_replay_preserves_first_confirmation_fields(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="payment-replay")
    first = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.SUCCEEDED),
    )
    payment = db_session.get(Payment, first.payment_id)
    assert payment is not None

    replay = apply_payment_transition(
        db_session,
        _payment_command(
            order,
            payment_id="payment-1",
            outcome=PaymentOutcome.SUCCEEDED,
            occurred_at=OCCURRED_AT + timedelta(days=1),
        ),
    )

    assert replay.disposition == TransitionDisposition.DUPLICATE
    assert payment.authorized_at == OCCURRED_AT
    assert payment.captured_at == OCCURRED_AT
    assert order.paid_at == OCCURRED_AT


@pytest.mark.parametrize(
    ("amount_minor", "currency", "expected_reason"),
    (
        (9_999, "RUB", "amount_mismatch"),
        (10_000, "USD", "currency_mismatch"),
    ),
)
def test_new_payment_financial_identity_must_match_order(
    db_session: Session,
    amount_minor: int,
    currency: str,
    expected_reason: str,
) -> None:
    order, _ = _seed_order(db_session, key=f"new-financial-{expected_reason}")

    result = apply_payment_transition(
        db_session,
        _payment_command(
            order,
            payment_id="payment-1",
            outcome=PaymentOutcome.SUCCEEDED,
            amount_minor=amount_minor,
            currency=currency,
        ),
    )

    assert result.disposition == TransitionDisposition.CONFLICT
    assert result.reason_code == expected_reason
    assert db_session.query(Payment).count() == 0


@pytest.mark.parametrize(
    ("amount_minor", "currency"),
    (
        (9_999, "RUB"),
        (10_000, "USD"),
    ),
)
def test_existing_payment_financial_identity_cannot_be_rewritten(
    db_session: Session,
    amount_minor: int,
    currency: str,
) -> None:
    order, _ = _seed_order(db_session, key=f"existing-financial-{currency}-{amount_minor}")
    payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.AUTHORIZED)

    result = apply_payment_transition(
        db_session,
        _payment_command(
            order,
            payment_id="payment-1",
            outcome=PaymentOutcome.SUCCEEDED,
            amount_minor=amount_minor,
            currency=currency,
        ),
    )

    assert result.disposition == TransitionDisposition.CONFLICT
    assert result.reason_code == "payment_context_mismatch"
    assert payment.amount_minor == order.amount_minor
    assert payment.currency == order.currency
    assert payment.status == PaymentStatus.AUTHORIZED


def test_payment_provider_account_and_invoice_correlation_fail_closed(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="payment-correlation", provider_invoice_id="invoice-1")

    account_result = apply_payment_transition(
        db_session,
        _payment_command(
            order,
            payment_id="payment-1",
            outcome=PaymentOutcome.SUCCEEDED,
            provider_account_id=uuid.uuid4(),
        ),
    )
    invoice_result = apply_payment_transition(
        db_session,
        _payment_command(
            order,
            payment_id="payment-2",
            outcome=PaymentOutcome.SUCCEEDED,
            provider_invoice_id="invoice-2",
        ),
    )
    provider_result = apply_payment_transition(
        db_session,
        _payment_command(
            order,
            payment_id="payment-3",
            outcome=PaymentOutcome.SUCCEEDED,
            provider="other-provider",
        ),
    )

    assert account_result.reason_code == "provider_context_mismatch"
    assert invoice_result.reason_code == "provider_invoice_mismatch"
    assert provider_result.reason_code == "provider_context_mismatch"
    assert db_session.query(Payment).count() == 0


def test_partial_cancel_amount_is_not_a_canonical_payment_semantic(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="partial-cancel")

    partial = apply_payment_transition(
        db_session,
        _payment_command(
            order,
            payment_id="payment-1",
            outcome=PaymentOutcome.CANCELED,
            amount_minor=order.amount_minor // 2,
        ),
    )
    normalized = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.CANCELED),
    )

    payment = db_session.get(Payment, normalized.payment_id)
    assert payment is not None
    assert partial.disposition == TransitionDisposition.CONFLICT
    assert normalized.disposition == TransitionDisposition.APPLIED
    assert payment.amount_minor == order.amount_minor


@pytest.mark.parametrize("initial_status", (PaymentStatus.FAILED, PaymentStatus.CANCELED))
def test_same_payment_identity_rejects_contradictory_success(
    db_session: Session,
    initial_status: PaymentStatus,
) -> None:
    order, _ = _seed_order(db_session, key=f"contradictory-{initial_status.value}")
    payment = _add_payment(db_session, order, payment_id="payment-1", status=initial_status)

    result = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.SUCCEEDED),
    )

    assert result.disposition == TransitionDisposition.CONFLICT
    assert result.reason_code == "payment_outcome_conflict"
    assert payment.status == initial_status


@pytest.mark.parametrize(
    ("status", "refunded_amount_minor"),
    (
        (PaymentStatus.SUCCEEDED, 0),
        (PaymentStatus.PARTIALLY_REFUNDED, 1_000),
        (PaymentStatus.REFUNDED, 10_000),
    ),
)
def test_late_weaker_payment_fact_cannot_downgrade_success_or_refund(
    db_session: Session,
    status: PaymentStatus,
    refunded_amount_minor: int,
) -> None:
    order, _ = _seed_order(db_session, key=f"stale-{status.value}", status=OrderStatus.PAID)
    payment = _add_payment(
        db_session,
        order,
        payment_id="payment-1",
        status=status,
        refunded_amount_minor=refunded_amount_minor,
    )

    result = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.FAILED),
    )

    assert result.disposition == TransitionDisposition.IGNORED
    assert payment.status == status
    assert order.status == OrderStatus.PAID


def test_failed_attempt_can_be_followed_by_distinct_successful_attempt(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="distinct-after-failure")
    failed = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.FAILED),
    )
    succeeded = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-2", outcome=PaymentOutcome.SUCCEEDED),
    )

    assert failed.disposition == TransitionDisposition.APPLIED
    assert succeeded.disposition == TransitionDisposition.APPLIED
    assert succeeded.order_became_paid is True
    assert order.status == OrderStatus.PAID
    assert order.failed_at is None
    assert order.paid_at == OCCURRED_AT
    assert db_session.query(Payment).count() == 2


def test_distinct_authorized_payment_ids_remain_distinct_attempts(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="distinct-authorizations")

    first = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.AUTHORIZED),
    )
    second = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-2", outcome=PaymentOutcome.AUTHORIZED),
    )

    assert first.disposition == TransitionDisposition.APPLIED
    assert second.disposition == TransitionDisposition.APPLIED
    assert order.status == OrderStatus.PENDING_PAYMENT
    assert db_session.query(Payment).count() == 2


def test_same_payment_identity_cannot_move_between_orders(db_session: Session) -> None:
    first_order, account = _seed_order(db_session, key="identity-first")
    second_order, _ = _seed_order(db_session, key="identity-second", account=account)
    apply_payment_transition(
        db_session,
        _payment_command(first_order, payment_id="shared-payment", outcome=PaymentOutcome.AUTHORIZED),
    )

    result = apply_payment_transition(
        db_session,
        _payment_command(second_order, payment_id="shared-payment", outcome=PaymentOutcome.AUTHORIZED),
    )

    assert result.disposition == TransitionDisposition.CONFLICT
    assert result.reason_code == "payment_context_mismatch"
    assert db_session.query(Payment).count() == 1


def test_existing_payment_on_another_terminal_order_conflicts_with_cancel(
    db_session: Session,
) -> None:
    first_order, account = _seed_order(db_session, key="cancel-identity-first")
    payment = _add_payment(
        db_session,
        first_order,
        payment_id="shared-cancel-payment",
        status=PaymentStatus.AUTHORIZED,
    )
    second_order, _ = _seed_order(
        db_session,
        key="cancel-identity-second",
        status=OrderStatus.PAID,
        account=account,
    )
    order_state = (second_order.status, second_order.paid_at, second_order.failed_at, second_order.canceled_at)

    result = apply_payment_transition(
        db_session,
        _payment_command(
            second_order,
            payment_id="shared-cancel-payment",
            outcome=PaymentOutcome.CANCELED,
        ),
    )

    assert result.disposition == TransitionDisposition.CONFLICT
    assert result.reason_code == "payment_context_mismatch"
    assert payment.order_id == first_order.id
    assert payment.status == PaymentStatus.AUTHORIZED
    assert payment.authorized_at == OCCURRED_AT
    assert payment.refunded_amount_minor == 0
    assert (second_order.status, second_order.paid_at, second_order.failed_at, second_order.canceled_at) == order_state
    assert db_session.query(Payment).count() == 1
    assert db_session.query(Payment).filter(Payment.order_id == second_order.id).count() == 0


def test_existing_provider_summary_is_not_rewritten_by_progression(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="historical-summary")
    payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.AUTHORIZED)
    payment.raw_summary = {"historical": "provider evidence"}
    db_session.flush()

    result = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.SUCCEEDED),
    )

    assert result.disposition == TransitionDisposition.APPLIED
    assert payment.raw_summary == {"historical": "provider evidence"}


@pytest.mark.parametrize("terminal_status", (OrderStatus.PAID, OrderStatus.CANCELED))
def test_distinct_successful_attempt_does_not_reopen_or_reapply_terminal_order(
    db_session: Session,
    terminal_status: OrderStatus,
) -> None:
    order, _ = _seed_order(db_session, key=f"terminal-{terminal_status.value}", status=terminal_status)
    if terminal_status == OrderStatus.PAID:
        _add_payment(db_session, order, payment_id="first-payment", status=PaymentStatus.SUCCEEDED)

    result = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="late-payment", outcome=PaymentOutcome.SUCCEEDED),
    )

    payment = db_session.get(Payment, result.payment_id)
    assert payment is not None
    assert result.disposition == TransitionDisposition.APPLIED
    assert result.order_became_paid is False
    assert payment.status == PaymentStatus.SUCCEEDED
    assert order.status == terminal_status
    assert db_session.query(Payment).count() == (2 if terminal_status == OrderStatus.PAID else 1)


@pytest.mark.parametrize(
    "terminal_status",
    (
        OrderStatus.PAID,
        OrderStatus.CANCELED,
        OrderStatus.PARTIALLY_REFUNDED,
        OrderStatus.REFUNDED,
    ),
)
def test_uncorrelated_cancel_on_terminal_order_is_stale_without_payment(
    db_session: Session,
    terminal_status: OrderStatus,
) -> None:
    order, _ = _seed_order(db_session, key=f"unknown-cancel-{terminal_status.value}", status=terminal_status)
    order_state = (order.status, order.paid_at, order.failed_at, order.canceled_at)

    result = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="unknown-payment", outcome=PaymentOutcome.CANCELED),
    )

    assert result.disposition == TransitionDisposition.IGNORED
    assert result.reason_code == "stale_payment_fact"
    assert result.payment_id is None
    assert result.order_became_paid is False
    assert result.refund_created is False
    assert (order.status, order.paid_at, order.failed_at, order.canceled_at) == order_state
    assert db_session.query(Payment).count() == 0


@pytest.mark.parametrize(
    ("refund_amount_minor", "payment_status", "order_status"),
    (
        (4_000, PaymentStatus.PARTIALLY_REFUNDED, OrderStatus.PARTIALLY_REFUNDED),
        (10_000, PaymentStatus.REFUNDED, OrderStatus.REFUNDED),
    ),
)
def test_succeeded_replay_after_refund_is_stale_without_downstream_effects(
    db_session: Session,
    refund_amount_minor: int,
    payment_status: PaymentStatus,
    order_status: OrderStatus,
) -> None:
    order, _ = _seed_order(db_session, key=f"succeeded-after-{payment_status.value}", status=OrderStatus.PAID)
    payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.SUCCEEDED)
    refund_result = apply_refund_transition(
        db_session,
        _refund_command(order, payment, refund_id="refund-1", amount_minor=refund_amount_minor),
    )
    assert refund_result.disposition == TransitionDisposition.APPLIED

    payment_state = (
        payment.status,
        payment.authorized_at,
        payment.captured_at,
        payment.failed_at,
        payment.refunded_amount_minor,
    )
    order_state = (order.status, order.paid_at, order.failed_at, order.canceled_at)
    result = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.SUCCEEDED),
    )

    assert result.disposition == TransitionDisposition.IGNORED
    assert result.reason_code == "stale_payment_fact"
    assert result.order_became_paid is False
    assert result.refund_created is False
    assert payment_state == (
        payment_status,
        payment.authorized_at,
        payment.captured_at,
        payment.failed_at,
        refund_amount_minor,
    )
    assert order_state == (order_status, order.paid_at, order.failed_at, order.canceled_at)
    assert db_session.query(Payment).count() == 1


def test_elapsed_expiry_does_not_reject_authoritative_payment(db_session: Session) -> None:
    order, _ = _seed_order(
        db_session,
        key="elapsed-expiry",
        expires_at=OCCURRED_AT - timedelta(days=1),
    )

    result = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.SUCCEEDED),
    )

    assert result.disposition == TransitionDisposition.APPLIED
    assert order.status == OrderStatus.PAID


def test_unsupported_order_and_payment_states_fail_closed(db_session: Session) -> None:
    expired_order, account = _seed_order(db_session, key="expired-order", status=OrderStatus.EXPIRED)
    expired_result = apply_payment_transition(
        db_session,
        _payment_command(expired_order, payment_id="payment-expired", outcome=PaymentOutcome.SUCCEEDED),
    )
    paid_order, _ = _seed_order(
        db_session,
        key="unsupported-payment",
        status=OrderStatus.PAID,
        account=account,
    )
    payment = _add_payment(db_session, paid_order, payment_id="payment-disputed", status=PaymentStatus.DISPUTED)
    disputed_result = apply_payment_transition(
        db_session,
        _payment_command(paid_order, payment_id="payment-disputed", outcome=PaymentOutcome.SUCCEEDED),
    )

    assert expired_result.disposition == TransitionDisposition.CONFLICT
    assert expired_result.reason_code == "unsupported_order_status"
    assert disputed_result.disposition == TransitionDisposition.CONFLICT
    assert payment.status == PaymentStatus.DISPUTED


def test_new_payment_keeps_provider_payload_out_of_raw_summary(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="raw-summary")

    result = apply_payment_transition(
        db_session,
        _payment_command(order, payment_id="payment-1", outcome=PaymentOutcome.AUTHORIZED),
    )

    payment = db_session.get(Payment, result.payment_id)
    assert payment is not None
    assert payment.raw_summary == {}


def test_partial_refund_updates_payment_and_order_without_access_dependencies(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="partial-refund", status=OrderStatus.PAID)
    payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.SUCCEEDED)

    result = apply_refund_transition(
        db_session,
        _refund_command(order, payment, refund_id="refund-1", amount_minor=4_000),
    )

    refund = db_session.get(Refund, result.refund_id)
    assert refund is not None
    assert result.disposition == TransitionDisposition.APPLIED
    assert result.refund_created is True
    assert refund.status == RefundStatus.SUCCEEDED
    assert payment.status == PaymentStatus.PARTIALLY_REFUNDED
    assert payment.refunded_amount_minor == 4_000
    assert order.status == OrderStatus.PARTIALLY_REFUNDED
    assert db_session.query(Subscription).count() == 0
    assert db_session.query(Entitlement).count() == 0


def test_full_refund_uses_occurrence_for_requested_and_succeeded_timestamps(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="full-refund", status=OrderStatus.PAID)
    payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.SUCCEEDED)

    result = apply_refund_transition(
        db_session,
        _refund_command(order, payment, refund_id="refund-1", amount_minor=payment.amount_minor),
    )

    refund = db_session.get(Refund, result.refund_id)
    assert refund is not None
    assert refund.requested_at == OCCURRED_AT
    assert refund.succeeded_at == OCCURRED_AT
    assert payment.status == PaymentStatus.REFUNDED
    assert order.status == OrderStatus.REFUNDED


def test_multiple_partial_refunds_apply_each_identity_once(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="multiple-refunds", status=OrderStatus.PAID)
    payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.SUCCEEDED)

    first = apply_refund_transition(
        db_session,
        _refund_command(order, payment, refund_id="refund-1", amount_minor=3_000),
    )
    second = apply_refund_transition(
        db_session,
        _refund_command(order, payment, refund_id="refund-2", amount_minor=7_000),
    )

    assert first.disposition == TransitionDisposition.APPLIED
    assert second.disposition == TransitionDisposition.APPLIED
    assert payment.refunded_amount_minor == payment.amount_minor
    assert payment.status == PaymentStatus.REFUNDED
    assert order.status == OrderStatus.REFUNDED
    assert db_session.query(Refund).count() == 2


def test_aggregate_refund_state_counts_multiple_successful_payments(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="aggregate-refunds", status=OrderStatus.PAID)
    first_payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.SUCCEEDED)
    second_payment = _add_payment(db_session, order, payment_id="payment-2", status=PaymentStatus.SUCCEEDED)

    apply_refund_transition(
        db_session,
        _refund_command(order, first_payment, refund_id="refund-1", amount_minor=first_payment.amount_minor),
    )
    assert order.status == OrderStatus.PARTIALLY_REFUNDED
    apply_refund_transition(
        db_session,
        _refund_command(order, second_payment, refund_id="refund-2", amount_minor=second_payment.amount_minor),
    )

    assert order.status == OrderStatus.REFUNDED


def test_exact_refund_replay_is_duplicate_after_payment_is_fully_refunded(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="refund-replay", status=OrderStatus.PAID)
    payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.SUCCEEDED)
    command = _refund_command(order, payment, refund_id="refund-1", amount_minor=payment.amount_minor)
    first = apply_refund_transition(db_session, command)

    replay = apply_refund_transition(db_session, command)

    assert first.disposition == TransitionDisposition.APPLIED
    assert replay.disposition == TransitionDisposition.DUPLICATE
    assert replay.refund_created is False
    assert payment.refunded_amount_minor == payment.amount_minor
    assert db_session.query(Refund).count() == 1


def test_same_refund_identity_with_different_payment_is_conflict(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="refund-conflict", status=OrderStatus.PAID)
    first_payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.SUCCEEDED)
    second_payment = _add_payment(db_session, order, payment_id="payment-2", status=PaymentStatus.SUCCEEDED)
    apply_refund_transition(
        db_session,
        _refund_command(order, first_payment, refund_id="refund-1", amount_minor=1_000),
    )

    result = apply_refund_transition(
        db_session,
        _refund_command(order, second_payment, refund_id="refund-1", amount_minor=1_000),
    )

    assert result.disposition == TransitionDisposition.CONFLICT
    assert result.reason_code == "refund_identity_conflict"
    assert second_payment.refunded_amount_minor == 0
    assert db_session.query(Refund).count() == 1


def test_new_refund_rejects_over_refund_and_non_refundable_payment(db_session: Session) -> None:
    order, account = _seed_order(db_session, key="over-refund", status=OrderStatus.PAID)
    payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.SUCCEEDED)
    over_refund = apply_refund_transition(
        db_session,
        _refund_command(order, payment, refund_id="refund-over", amount_minor=payment.amount_minor + 1),
    )
    failed_order, _ = _seed_order(
        db_session,
        key="non-refundable",
        status=OrderStatus.PAID,
        account=account,
    )
    failed_payment = _add_payment(
        db_session,
        failed_order,
        payment_id="payment-failed",
        status=PaymentStatus.FAILED,
    )
    non_refundable = apply_refund_transition(
        db_session,
        _refund_command(failed_order, failed_payment, refund_id="refund-failed", amount_minor=1_000),
    )

    assert over_refund.reason_code == "refund_amount_exceeds_payment"
    assert non_refundable.reason_code == "payment_not_refundable"
    assert db_session.query(Refund).count() == 0


def test_refund_currency_must_match_target_payment(db_session: Session) -> None:
    order, _ = _seed_order(db_session, key="refund-currency", status=OrderStatus.PAID)
    payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.SUCCEEDED)
    command = _refund_command(order, payment, refund_id="refund-1", amount_minor=1_000)

    result = apply_refund_transition(
        db_session,
        command.model_copy(update={"currency": "USD"}),
    )

    assert result.disposition == TransitionDisposition.CONFLICT
    assert result.reason_code == "payment_context_mismatch"
    assert payment.refunded_amount_minor == 0
    assert db_session.query(Refund).count() == 0


@pytest.mark.parametrize("order_status", (OrderStatus.CANCELED, OrderStatus.REFUNDED))
def test_refund_preserves_canceled_and_already_refunded_order_status(
    db_session: Session,
    order_status: OrderStatus,
) -> None:
    order, _ = _seed_order(db_session, key=f"refund-order-{order_status.value}", status=order_status)
    payment = _add_payment(db_session, order, payment_id="payment-1", status=PaymentStatus.SUCCEEDED)

    result = apply_refund_transition(
        db_session,
        _refund_command(order, payment, refund_id="refund-1", amount_minor=1_000),
    )

    assert result.disposition == TransitionDisposition.APPLIED
    assert order.status == order_status
