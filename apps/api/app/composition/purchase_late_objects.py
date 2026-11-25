"""Review exact late objects from inventory and the original purchase's GET-only recovery."""

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.late_purchase_reviews import LateObjectEvidence, ReleasedOriginal, record_late_object
from app.domains.billing.reconciliation import read_source_time
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import PurchaseInventoryIncomplete, PurchaseRefused
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import (
    LbxAttemptsExhausted,
    LbxProviderRejected,
    LbxRateLimited,
    LbxResponseInvalid,
    LbxScopeMismatch,
    LbxTimeout,
    LbxUnavailable,
)
from app.integrations.lbx.financial import (
    Agreement,
    Subscription,
    agreement_explicitly_open,
    agreement_is_closed,
    subscription_lifecycle,
)
from app.integrations.lbx.reconciliation import MAX_RELEVANT_SUBSCRIPTIONS, timely_point
from app.models import ExternalCreateOperationKind as Kind, ExternalSubscriptionLifecycleStatus as Lifecycle


async def candidate_point[T](read: Callable[[], Awaitable[T]], budget: PreflightBudget) -> T | None:
    """Keep object-local failures distinct from scope and shared-budget errors."""
    try:
        return await timely_point(read, budget)
    except (LbxResponseInvalid, LbxUnavailable, LbxTimeout, LbxRateLimited, LbxAttemptsExhausted, LbxProviderRejected):
        return None


async def review_historical_subscription(
    client: LbxServerClient,
    factory: SessionFactory,
    original: ReleasedOriginal,
    customer: CustomerOpen,
    point: Subscription,
    *,
    read_finished_at: datetime,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> bool:
    """Keep the exact subscription fact when follow-up evidence is unavailable."""
    agreement, failure = None, None
    try:
        agreement = await candidate_point(
            lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
        )
    except LbxScopeMismatch:
        raise
    except AppError as error:
        failure = error
    try:
        await record_subscription(
            factory, original, customer, point, agreement, read_finished_at=read_finished_at, delegate=delegate
        )
    except LbxResponseInvalid:
        return False
    if failure is not None:
        raise failure
    return agreement is not None


def prove_original_agreement(original: ReleasedOriginal, customer: CustomerOpen, agreement: Agreement) -> None:
    purchase = original.purchase
    operation = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    fields: tuple[tuple[object, object], ...] = (
        (agreement.user_id, int(customer.provider_id)),
        (agreement.organization_id, purchase.accepted.seller_id),
        (agreement.agreement_number, operation.key),
        (agreement.is_offer, False),
    )
    if operation.agreement_create_date is not None:
        fields += ((agreement.create_date, operation.agreement_create_date.isoformat()),)
    if any(value is not None and value != expected for value, expected in fields):
        raise LbxScopeMismatch()
    if any(value is None for value, _ in fields):
        raise LbxResponseInvalid()


async def record_subscription(
    factory: SessionFactory,
    original: ReleasedOriginal,
    customer: CustomerOpen,
    point: Subscription,
    agreement: Agreement | None,
    *,
    read_finished_at: datetime,
    delegate: Callable[..., Awaitable[Any]],
    agreement_read_after_point: bool = True,
) -> None:
    if agreement is not None and (agreement.agreement_id, agreement.user_id) != (
        point.agreement_id,
        int(customer.provider_id),
    ):
        raise LbxScopeMismatch()
    if subscription_lifecycle(point)[0] == Lifecycle.ENDED:
        return
    external_id = str(point.subscription_id)
    belongs_to_original = str(point.agreement_id) in original.agreement_ids
    known_subscription = external_id in original.subscription_ids
    incomplete: LbxResponseInvalid | None = None
    if agreement is not None:
        try:
            if belongs_to_original or not known_subscription:
                prove_original_agreement(original, customer, agreement)
                belongs_to_original = True
            if agreement_read_after_point and agreement_is_closed(agreement):
                return
        except LbxResponseInvalid as error:
            # Missing follow-up evidence can leave inventory incomplete while
            # the exact subscription and its retained owner are already proven.
            if not (belongs_to_original or known_subscription):
                raise
            incomplete = error
    if not (belongs_to_original or known_subscription):
        raise PurchaseInventoryIncomplete()
    await delegate(
        record_late_object,
        factory,
        original,
        customer,
        LateObjectEvidence(
            kind=Kind.SUBSCRIPTION,
            external_object_id=external_id,
            competing_tariff_id=None if belongs_to_original else point.tariff_id,
            read_finished_at=read_finished_at,
            agreement_id=str(point.agreement_id),
        ),
    )
    if incomplete is not None:
        raise incomplete


async def recover_released(
    client: LbxServerClient,
    factory: SessionFactory,
    original: ReleasedOriginal,
    customer: CustomerOpen,
    *,
    operation_id: UUID | None,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
) -> None:
    purchase = original.purchase
    user = await timely_point(lambda: client.get_user(user_id=int(customer.provider_id), budget=budget), budget)
    if user.outer_id != customer.outer_key:
        raise PurchaseRefused("billing_identity_unproven", 409)

    agreement_op = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    subscription_op = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    read_agreement = operation_id in {None, agreement_op.id}
    read_subscription = operation_id in {None, subscription_op.id}
    agreement_ids = {int(value) for value in original.agreement_ids}
    subscription_ids = {int(value) for value in original.subscription_ids}
    if agreement_op.candidate_id:
        agreement_ids.add(int(agreement_op.candidate_id))
    if subscription_op.candidate_id:
        subscription_ids.add(int(subscription_op.candidate_id))
    agreements: dict[int, Agreement] = {}
    attempted_agreements: set[int] = set()
    first_error: AppError | None = None
    try:
        if (read_agreement or read_subscription) and not agreement_ids:
            agreement_ids.update(
                await timely_point(
                    lambda: client.discover_agreements(
                        user_id=int(customer.provider_id), number=agreement_op.key, budget=budget
                    ),
                    budget,
                )
            )
        if len(agreement_ids) > MAX_RELEVANT_SUBSCRIPTIONS:
            raise PurchaseInventoryIncomplete()
        for identity in sorted(agreement_ids):
            attempted_agreements.add(identity)
            point = await timely_point(lambda: client.get_agreement(agreement_id=identity, budget=budget), budget)
            read_finished_at = await delegate(read_source_time, factory) if read_agreement else None
            agreements[identity] = point
            if point.agreement_id != identity:
                raise LbxScopeMismatch()
            prove_original_agreement(original, customer, point)
            if read_finished_at is not None and agreement_explicitly_open(point):
                await delegate(
                    record_late_object,
                    factory,
                    original,
                    customer,
                    LateObjectEvidence(
                        kind=Kind.AGREEMENT,
                        external_object_id=str(identity),
                        read_finished_at=read_finished_at,
                    ),
                )
            if read_subscription:
                rows = await timely_point(
                    lambda: client.discover_subscriptions(
                        user_id=int(customer.provider_id), agreement_id=identity, budget=budget
                    ),
                    budget,
                )
                subscription_ids.update(row.subscription_id for row in rows)
    except LbxScopeMismatch:
        raise
    except AppError as error:
        first_error = error  # Exact retained subscription IDs can still be read independently.

    if read_subscription:
        if len(subscription_ids) > MAX_RELEVANT_SUBSCRIPTIONS:
            raise PurchaseInventoryIncomplete()
        for identity in sorted(subscription_ids):
            try:
                point = await timely_point(
                    lambda: client.get_subscription(subscription_id=identity, budget=budget), budget
                )
                read_finished_at = await delegate(read_source_time, factory)
                if point.subscription_id != identity:
                    raise LbxScopeMismatch()
                agreement = agreements.get(point.agreement_id)
                agreement_read_after_point = point.agreement_id not in attempted_agreements
                if agreement_read_after_point:
                    attempted_agreements.add(point.agreement_id)
                    try:
                        agreement = await timely_point(
                            lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
                        )
                        agreements[point.agreement_id] = agreement
                    except LbxScopeMismatch:
                        raise
                    except AppError as error:
                        first_error = first_error or error
                await record_subscription(
                    factory,
                    original,
                    customer,
                    point,
                    agreement,
                    read_finished_at=read_finished_at,
                    delegate=delegate,
                    agreement_read_after_point=agreement_read_after_point,
                )
            except LbxScopeMismatch:
                raise
            except AppError as error:
                first_error = first_error or error
    if first_error is not None:
        raise first_error
