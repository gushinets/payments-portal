"""One durable account-wide customer operation. HTTP never holds these transactions."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.contracts import CREATE_FAILURE_REASONS, CREATE_RESPONSE_SCHEMA, BillingRefused, CustomerOpen
from app.domains.catalog.publication import SessionFactory
from app.domains.identity.errors import InvalidAuthSessionError
from app.domains.identity.services.auth import as_utc, authenticate_session
from app.infrastructure.queries.billing_customers import (
    connection_accounts,
    customer_operation,
    customer_slot,
    foreign_customer,
    lock_customer,
    lock_user,
    overdue_customer_ids,
    open_customer_reviews,
    recovery_work,
)
from app.models import (
    BillingWorkItem,
    ExternalBillingCustomer,
    ExternalBillingCustomerBindingState as Binding,
    ExternalCreateOperation,
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    ManualReviewCase,
    User,
)


RECOVERY_WINDOW = timedelta(hours=2)
CUSTOMER_RECEIPT_SCHEMA = "customer-create-receipt:v1"


def _receipt_id(operation: ExternalCreateOperation) -> str | None:
    if operation.recovery_hint_schema_version is None and operation.recovery_hint_document is None:
        return None
    hint = operation.recovery_hint_document
    if operation.recovery_hint_schema_version != CUSTOMER_RECEIPT_SCHEMA or not isinstance(hint, dict):
        raise BillingRefused("billing_identity_unproven", 409)
    value = hint.get("provider_customer_candidate_id")
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or len(value) > 20
        or int(value) <= 0
        or str(int(value)) != value
    ):
        raise BillingRefused("billing_identity_unproven", 409)
    return value


def authenticate(db: Session, configuration: Settings, token: str) -> User:
    try:
        user, _ = authenticate_session(
            db, token=token, tenant_id=configuration.instance_tenant_id, region=configuration.instance_region
        )
    except InvalidAuthSessionError:
        raise BillingRefused("billing_session_required", 401) from None
    if user.email_verified_at is None:
        raise BillingRefused("billing_email_verification_required", 403)
    return user


def _snapshot(
    customer: ExternalBillingCustomer,
    operation: ExternalCreateOperation,
    user: User | None = None,
    *,
    may_create: bool = False,
) -> CustomerOpen:
    return CustomerOpen(
        customer.customer_id,
        operation.create_operation_id,
        operation.send_fence,
        customer.billing_customer_key,
        customer.provider_customer_id,
        may_create,
        user.email if user else "",
        user.first_name if user else None,
        user.surname if user else None,
        user.patronymic if user else None,
        _receipt_id(operation),
    )


def reserve_customer(factory: SessionFactory, configuration: Settings, token: str) -> CustomerOpen:
    with factory() as db:
        user = authenticate(db, configuration, token)
        user = lock_user(db, user.id)
        result = reserve_customer_in_transaction(db, configuration, user)
        db.commit()
        return result


def reserve_customer_in_transaction(db: Session, configuration: Settings, user: User) -> CustomerOpen:
    """Reuse the account slot inside purchase admission's caller-owned transaction.

    Caller has locked the user. No provider calls, consent or commit here.
    """
    accounts = connection_accounts(db, configuration.lbx_provider_origin)
    if len(accounts) > 1:
        raise BillingRefused("billing_connection_conflict", 409)
    account = next(iter(accounts), configuration.lbx_external_billing_account_id)
    if foreign_customer(db, user.id, account):
        raise BillingRefused("billing_connection_conflict", 409)
    customer = customer_slot(db, account, user.id)
    if customer is None:
        customer = ExternalBillingCustomer(
            customer_id=uuid4(),
            external_billing_account_id=account,
            user_id=user.id,
            provider_origin=configuration.lbx_provider_origin,
            billing_customer_key=secrets.token_urlsafe(32),
            binding_state=Binding.UNBOUND,
        )
        db.add(customer)
        db.flush()
    if customer.provider_origin != configuration.lbx_provider_origin:
        # Retained legacy rows lack provenance; never try old IDs at a new origin.
        raise BillingRefused("billing_connection_conflict", 409)
    operation = customer_operation(db, customer.customer_id)
    if operation is None:
        if customer.provider_customer_id is not None:
            raise BillingRefused("billing_legacy_identity_unproven", 409)
        operation = ExternalCreateOperation(
            create_operation_id=uuid4(),
            customer_id=customer.customer_id,
            operation_kind=Kind.CUSTOMER,
            request_correlation_key=customer.billing_customer_key,
            operation_state=State.PENDING,
        )
        db.add(operation)
        db.flush()
    if operation.request_correlation_key != customer.billing_customer_key:
        raise BillingRefused("billing_identity_conflict", 409)
    return _snapshot(customer, operation, user, may_create=operation.operation_state == State.PENDING)


def claim_customer_send(
    factory: SessionFactory, configuration: Settings, token: str, expected: CustomerOpen
) -> CustomerOpen:
    with factory() as db:
        user = authenticate(db, configuration, token)
        lock_user(db, user.id)
        customer = lock_customer(db, expected.customer_id)
        operation = customer_operation(db, customer.customer_id)
        if (
            customer.user_id != user.id
            or customer.provider_origin != configuration.lbx_provider_origin
            or customer.billing_customer_key != expected.outer_key
            or operation is None
            or operation.create_operation_id != expected.operation_id
            or operation.request_correlation_key != expected.outer_key
        ):
            raise BillingRefused("billing_identity_conflict", 409)
        if customer.provider_customer_id is not None or _receipt_id(operation) is not None:
            return _snapshot(customer, operation)
        if customer.binding_state == Binding.IDENTITY_CONFLICT:
            raise BillingRefused("billing_identity_conflict", 409)
        if operation.send_fence != expected.fence:
            return _snapshot(customer, operation)
        now = utc_now()
        work = recovery_work(db, operation.create_operation_id)
        if work is not None and work.lease_expires_at is not None and as_utc(work.lease_expires_at) > now:
            return _snapshot(customer, operation)
        # Called only after fresh, successful discovery found no customer.
        # The owner-approved account policy permits another explicit-open
        # attempt while retaining the original slot/key/operation and history.
        operation.send_fence = uuid4()
        operation.operation_state = State.POSSIBLE_SEND
        operation.unknown_since = now
        operation.unknown_recovery_deadline_at = now + RECOVERY_WINDOW
        if work is None:
            work = BillingWorkItem(
                work_kind="external_create_recovery",
                scope_kind="create_operation",
                scope_reference=str(operation.create_operation_id),
                coalescing_key=str(operation.create_operation_id),
                payload_schema_version="v1",
                payload_document={"create_operation_id": str(operation.create_operation_id)},
                next_attempt_at=operation.unknown_recovery_deadline_at,
                work_state="pending",
            )
            db.add(work)
        else:
            work.next_attempt_at = operation.unknown_recovery_deadline_at
            work.work_state = "pending"
        work.attempt_count = (work.attempt_count or 0) + 1
        work.lease_owner = f"customer-send:{operation.send_fence}"
        work.lease_expires_at = now + timedelta(
            seconds=configuration.preflight_total_timeout_seconds + configuration.preflight_cleanup_timeout_seconds
        )
        result = _snapshot(customer, operation, user, may_create=True)
        db.commit()  # Fence, active-send lease and recovery item precede POST.
        return result


def record_customer_receipt(factory: SessionFactory, expected: CustomerOpen, provider_id: int) -> CustomerOpen:
    """Durably retain the POST candidate before point-read I/O; this is not binding."""
    if type(provider_id) is not int or not 0 < provider_id < 10**20:
        raise BillingRefused("billing_identity_unproven", 409)
    with factory() as db:
        customer = lock_customer(db, expected.customer_id)
        operation = customer_operation(db, expected.customer_id)
        if (
            operation is None
            or not expected.may_create
            or expected.fence is None
            or operation.create_operation_id != expected.operation_id
            or operation.send_fence != expected.fence
            or operation.operation_state not in {State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW}
            or customer.billing_customer_key != expected.outer_key
            or operation.request_correlation_key != expected.outer_key
        ):
            raise BillingRefused("billing_customer_pending", 409)
        previous = _receipt_id(operation)
        if previous not in {None, str(provider_id)}:
            raise BillingRefused("billing_identity_conflict", 409)
        operation.recovery_hint_schema_version = CUSTOMER_RECEIPT_SCHEMA
        operation.recovery_hint_document = {"provider_customer_candidate_id": str(provider_id)}
        result = _snapshot(customer, operation)
        db.commit()
        return result


def record_customer_create_failure(
    factory: SessionFactory, expected: CustomerOpen, *, http_status: int, lbx_code: int | None, reason: str
) -> None:
    """Retain bounded safe response facts, never raw text or permission to retry."""
    if type(http_status) is not int or not 100 <= http_status <= 599:
        raise ValueError("invalid HTTP status")
    if lbx_code is not None and (type(lbx_code) is not int or not -(2**31) <= lbx_code < 2**31):
        raise ValueError("invalid LBX code")
    with factory() as db:
        customer = lock_customer(db, expected.customer_id)
        operation = customer_operation(db, expected.customer_id)
        if (
            operation is None
            or not expected.may_create
            or operation.create_operation_id != expected.operation_id
            or operation.send_fence != expected.fence
            or expected.fence is None
            or customer.billing_customer_key != expected.outer_key
            or operation.request_correlation_key != expected.outer_key
            or customer.provider_customer_id is not None
            or _receipt_id(operation) is not None
        ):
            return
        work = recovery_work(db, expected.operation_id)
        if work is not None:
            safe_reason = reason if reason in CREATE_FAILURE_REASONS else "unknown"
            work.last_error_classification = safe_reason
            work.payload_document = {
                **work.payload_document,
                "last_failed_create": {
                    "schema_version": CREATE_RESPONSE_SCHEMA,
                    "http_status": http_status,
                    "lbx_code": lbx_code,
                    "reason": safe_reason,
                    "recorded_at": utc_now().isoformat(),
                },
            }
        db.commit()


def release_unsent_claim(factory: SessionFactory, expected: CustomerOpen) -> None:
    """Only this owner's proven unsent result authorizes resetting its claim."""
    with factory() as db:
        customer = lock_customer(db, expected.customer_id)
        operation = customer_operation(db, expected.customer_id)
        if (
            operation is None
            or not expected.may_create
            or expected.fence is None
            or operation.create_operation_id != expected.operation_id
            or customer.billing_customer_key != expected.outer_key
            or operation.request_correlation_key != expected.outer_key
            or customer.provider_customer_id is not None
            or operation.send_fence != expected.fence
            or operation.operation_state != State.POSSIBLE_SEND
            or operation.recovery_hint_document is not None
        ):
            raise BillingRefused("billing_customer_pending", 409)
        operation.operation_state = State.PENDING
        operation.send_fence = uuid4()
        operation.unknown_since = None
        operation.unknown_recovery_deadline_at = None
        work = recovery_work(db, operation.create_operation_id)
        if work is not None:
            work.work_state = "done"
            work.lease_owner = None
            work.lease_expires_at = None
        db.commit()


def finish_customer_attempt(factory: SessionFactory, expected: CustomerOpen) -> None:
    """A completed failed request releases only its own active-send lease."""
    with factory() as db:
        customer = lock_customer(db, expected.customer_id)
        operation = customer_operation(db, expected.customer_id)
        if (
            operation is None
            or operation.create_operation_id != expected.operation_id
            or operation.send_fence != expected.fence
            or expected.fence is None
        ):
            return
        work = recovery_work(db, expected.operation_id)
        if work is not None and work.lease_owner == f"customer-send:{expected.fence}":
            work.lease_owner = None
            work.lease_expires_at = None
        if operation.operation_state == State.POSSIBLE_SEND and customer.provider_customer_id is None:
            operation.operation_state = State.UNKNOWN
            # Invalidate searches/snapshots taken while this send was active.
            # A later attempt needs a fresh snapshot and fresh discovery.
            operation.send_fence = uuid4()
        db.commit()


def _manual_review(db: Session, operation: ExternalCreateOperation, reason: str) -> None:
    if operation.operation_state != State.MANUAL_REVIEW:
        db.add(
            ManualReviewCase(
                reason_code=reason,
                scope_kind="create_operation",
                scope_reference=str(operation.create_operation_id),
                evidence_schema_version="v1",
                evidence_document={"create_operation_id": str(operation.create_operation_id)},
                case_state="open",
            )
        )
    operation.operation_state = State.MANUAL_REVIEW


def apply_customer_read(
    factory: SessionFactory,
    expected: CustomerOpen,
    *,
    provider_id: str | None = None,
    outer_key: str | None = None,
    ambiguous: bool = False,
) -> CustomerOpen:
    """Apply point proof only against its current fence; lists alone never bind."""
    with factory() as db:
        customer = lock_customer(db, expected.customer_id)
        operation = customer_operation(db, customer.customer_id)
        if (
            operation is None
            or operation.create_operation_id != expected.operation_id
            or operation.send_fence != expected.fence
        ):
            raise BillingRefused("billing_customer_pending", 409)
        if (
            customer.billing_customer_key != expected.outer_key
            or operation.request_correlation_key != expected.outer_key
        ):
            raise BillingRefused("billing_identity_conflict", 409)
        if provider_id is not None and outer_key is None:
            raise BillingRefused("billing_identity_unproven", 409)
        conflict = ambiguous or (
            provider_id is not None
            and (outer_key != customer.billing_customer_key or customer.provider_customer_id not in {None, provider_id})
        )
        if conflict:
            customer.binding_state = Binding.IDENTITY_CONFLICT
            operation.send_fence = uuid4()  # Invalidate any delayed successful CREATE completion.
            _manual_review(db, operation, "customer_identity_conflict")
            db.commit()
            raise BillingRefused("billing_identity_conflict", 409)
        if provider_id is None:
            if operation.operation_state == State.PENDING:
                raise BillingRefused("billing_customer_pending", 409)
            if operation.unknown_recovery_deadline_at and utc_now() >= as_utc(operation.unknown_recovery_deadline_at):
                _manual_review(db, operation, "external_create_outcome_unknown:customer")
            elif operation.operation_state != State.MANUAL_REVIEW:
                operation.operation_state = State.UNKNOWN
            review_required = operation.operation_state == State.MANUAL_REVIEW
            db.commit()
            raise BillingRefused("billing_customer_review" if review_required else "billing_customer_pending", 409)
        already_bound = (
            customer.binding_state == Binding.BOUND
            and customer.provider_customer_id == provider_id
            and operation.operation_state == State.BOUND
        )
        customer.provider_customer_id = provider_id
        customer.binding_state = Binding.BOUND
        customer.binding_updated_at = utc_now()
        operation.operation_state = State.BOUND
        operation.bound_external_object_id = provider_id
        operation.resolved_at = operation.resolved_at or utc_now()
        if not already_bound:
            operation.send_fence = uuid4()
        work = recovery_work(db, operation.create_operation_id)
        if work is not None:
            work.work_state = "done"
            work.lease_owner = None
            work.lease_expires_at = None
        for review in open_customer_reviews(db, operation.create_operation_id):
            review.case_state = "resolved"
            review.resolved_at = utc_now()
            review.resolved_by_principal = "system:customer-point-read"
            review.resolution_schema_version = "v1"
            review.resolution_document = {
                "create_operation_id": str(operation.create_operation_id),
                "proof": "original_customer_point_read",
            }
        result = _snapshot(customer, operation)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            customer = lock_customer(db, expected.customer_id)
            operation = customer_operation(db, customer.customer_id)
            customer.binding_state = Binding.IDENTITY_CONFLICT
            if operation is not None:
                operation.send_fence = uuid4()
                _manual_review(db, operation, "customer_provider_id_already_bound")
            db.commit()
            raise BillingRefused("billing_identity_conflict", 409) from None
        return result


def recheck_widget_session(
    factory: SessionFactory, configuration: Settings, token: str, expected: CustomerOpen
) -> None:
    with factory() as db:
        user = authenticate(db, configuration, token)
        lock_user(db, user.id)
        customer = lock_customer(db, expected.customer_id)
        operation = customer_operation(db, customer.customer_id)
        if (
            customer.user_id != user.id
            or customer.binding_state != Binding.BOUND
            or customer.provider_customer_id != expected.provider_id
            or customer.billing_customer_key != expected.outer_key
            or operation is None
            or operation.send_fence != expected.fence
            or operation.request_correlation_key != expected.outer_key
            or operation.operation_state != State.BOUND
        ):
            raise BillingRefused("billing_identity_conflict", 409)


def escalate_overdue_customers(factory: SessionFactory, *, now: datetime | None = None, limit: int = 100) -> int:
    """Callable by later recovery work; no scheduler and no scope release."""
    instant = now or utc_now()
    if not 1 <= limit <= 100:
        raise ValueError("invalid recovery batch limit")
    with factory() as db:
        ids = overdue_customer_ids(db, instant, limit)
    count = 0
    for customer_id in ids:
        with factory() as db:
            lock_customer(db, customer_id)
            operation = customer_operation(db, customer_id)
            if (
                operation
                and operation.operation_state in {State.POSSIBLE_SEND, State.UNKNOWN}
                and operation.unknown_recovery_deadline_at
                and as_utc(operation.unknown_recovery_deadline_at) <= instant
            ):
                _manual_review(db, operation, "external_create_outcome_unknown:customer")
                count += 1
                db.commit()
    return count
