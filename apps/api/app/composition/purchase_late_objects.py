"""Review exact late objects from inventory and the original purchase's GET-only recovery."""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.core.errors import AppError
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.late_purchase_reviews import (
    LateObjectEvidence,
    ReleasedOriginal,
    record_late_object,
    released_owners,
)
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
from app.integrations.lbx.reconciliation import MAX_RELEVANT_SUBSCRIPTIONS
from app.integrations.lbx.subscription_points import timely_point
from app.models import ExternalCreateOperationKind as Kind, ExternalSubscriptionLifecycleStatus as Lifecycle


async def candidate_point[T](read: Callable[[], Awaitable[T]], budget: PreflightBudget) -> T | None:
    """Keep object-local failures distinct from scope and shared-budget errors."""
    try:
        return await timely_point(read, budget)
    except (LbxResponseInvalid, LbxUnavailable, LbxTimeout, LbxRateLimited, LbxAttemptsExhausted, LbxProviderRejected):
        return None


@dataclass(frozen=True)
class AgreementRead:
    point: Agreement
    read_finished_at: datetime


type ClosedAgreementReads = dict[int, AgreementRead]


@dataclass(frozen=True)
class SubscriptionRedirect:
    customer: CustomerOpen
    point: Subscription
    read_finished_at: datetime


def historical_subscription_matches(
    history: tuple[ReleasedOriginal, ...], provider_id: str, agreement_id: str | None
) -> list[ReleasedOriginal]:
    return [old for old in history if provider_id in old.subscription_ids] or [
        old for old in history if agreement_id in old.agreement_ids
    ]


def agreement_key(original: ReleasedOriginal) -> str:
    return next(op.key for op in original.purchase.operations if op.kind == Kind.AGREEMENT)


def unique_owner(matches: Sequence[ReleasedOriginal]) -> ReleasedOriginal | None:
    if len(matches) > 1:
        raise PurchaseInventoryIncomplete()
    return matches[0] if matches else None


@dataclass(frozen=True)
class LatePointReview:
    agreement: Agreement | None
    products: frozenset[str]
    complete: bool


async def review_late_subscription(
    client: LbxServerClient,
    factory: SessionFactory,
    customer: CustomerOpen,
    provider_id: str,
    point: Subscription,
    *,
    read_finished_at: datetime,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
    closed_agreements: ClosedAgreementReads,
    observed_agreement: AgreementRead | None = None,
    read_agreement: bool = True,
) -> LatePointReview:
    """Apply the same ownership proof to a first point, a redirect and a listed candidate."""
    if str(point.subscription_id) != provider_id:
        raise LbxScopeMismatch()
    agreement_read = closed_agreements.get(point.agreement_id)
    if (
        agreement_read is None
        and observed_agreement is not None
        and observed_agreement.point.agreement_id == point.agreement_id
    ):
        agreement_read = observed_agreement
    failure = None
    if agreement_read is None and read_agreement:
        try:
            agreement = await candidate_point(
                lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
            )
            if agreement is not None:
                agreement_read = AgreementRead(agreement, await delegate(read_source_time, factory))
        except LbxScopeMismatch:
            raise
        except AppError as error:
            failure = error  # Already-read points can still have a locally retained owner.
    agreement = agreement_read.point if agreement_read else None
    history = await point_owners(factory, customer, point, agreement, delegate)
    products = frozenset(item.purchase.accepted.selection.product_id for item in history)
    complete = agreement is not None
    try:
        await record_subscription(
            factory,
            customer,
            point,
            agreement,
            history=history,
            read_finished_at=read_finished_at,
            agreement_read_at=agreement_read.read_finished_at if agreement_read else None,
            closed_agreements=closed_agreements,
            delegate=delegate,
        )
    except (LbxResponseInvalid, LbxScopeMismatch, PurchaseInventoryIncomplete):
        complete = False  # Candidate-local proof cannot invalidate an independent product.
    if failure is not None:
        raise failure
    return LatePointReview(agreement, products, complete)


async def point_owners(
    factory: SessionFactory,
    customer: CustomerOpen,
    point: Subscription,
    agreement: Agreement | None,
    delegate: Callable[..., Awaitable[Any]],
) -> tuple[ReleasedOriginal, ...]:
    return await delegate(
        released_owners,
        factory,
        customer.customer_id,
        {str(point.agreement_id)},
        {str(point.subscription_id)},
        agreement_number=agreement.agreement_number if agreement else None,
    )


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


async def record_open_agreement(
    factory: SessionFactory,
    original: ReleasedOriginal,
    customer: CustomerOpen,
    agreement: Agreement,
    read_finished_at: datetime,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    await delegate(
        record_late_object,
        factory,
        original,
        customer,
        LateObjectEvidence(
            kind=Kind.AGREEMENT,
            external_object_id=str(agreement.agreement_id),
            read_finished_at=read_finished_at,
        ),
    )


async def review_observed_agreement(
    factory: SessionFactory,
    customer: CustomerOpen,
    observed: AgreementRead,
    *,
    expected_number: str,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    """Identify a released owner's agreement and persist an explicitly open point before continuing."""
    agreement = observed.point
    number = agreement.agreement_number
    if not number or number == expected_number or agreement.user_id != int(customer.provider_id):
        return
    # The original request number is mandatory in the ownership proof.
    owners = await delegate(released_owners, factory, customer.customer_id, set(), set(), agreement_number=number)
    original = unique_owner(owners)
    if original is None:
        return
    try:
        prove_original_agreement(original, customer, agreement)
        explicitly_open = agreement_explicitly_open(agreement)
    except (LbxResponseInvalid, LbxScopeMismatch):
        return
    if explicitly_open:
        await record_open_agreement(factory, original, customer, agreement, observed.read_finished_at, delegate)


async def record_subscription(
    factory: SessionFactory,
    customer: CustomerOpen,
    point: Subscription,
    agreement: Agreement | None,
    *,
    history: tuple[ReleasedOriginal, ...],
    read_finished_at: datetime,
    delegate: Callable[..., Awaitable[Any]],
    agreement_read_at: datetime | None = None,
    closed_agreements: ClosedAgreementReads | None = None,
    require_owner: bool = False,
) -> None:
    if agreement is not None and (agreement.agreement_id, agreement.user_id) != (
        point.agreement_id,
        int(customer.provider_id),
    ):
        raise LbxScopeMismatch()
    if not history and not require_owner:
        return

    external_id, agreement_id = str(point.subscription_id), str(point.agreement_id)
    agreement_owner = None
    agreement_error = None
    closed = False
    try:
        agreement_owner = unique_owner(
            [
                old
                for old in history
                if agreement_id in old.agreement_ids
                or (agreement is not None and agreement_key(old) == agreement.agreement_number)
            ]
        )
        if agreement is not None:
            if agreement_owner is not None:
                prove_original_agreement(agreement_owner, customer, agreement)
            closed = agreement_is_closed(agreement)
            if closed and closed_agreements is not None and agreement_read_at is not None:
                closed_agreements[agreement.agreement_id] = AgreementRead(agreement, agreement_read_at)
            elif agreement_owner is not None and agreement_read_at is not None and agreement_explicitly_open(agreement):
                await record_open_agreement(factory, agreement_owner, customer, agreement, agreement_read_at, delegate)
    except (PurchaseInventoryIncomplete, LbxScopeMismatch, LbxResponseInvalid) as error:
        agreement_error = error  # An exact subscription can prove its own owner independently.

    if subscription_lifecycle(point)[0] == Lifecycle.ENDED:
        if agreement_error is not None:
            raise agreement_error
        return
    original = unique_owner([old for old in history if external_id in old.subscription_ids]) or agreement_owner
    if original is None:
        raise agreement_error or PurchaseInventoryIncomplete()
    if closed:
        return
    known_subscription = external_id in original.subscription_ids
    belongs_to_original = agreement_id in original.agreement_ids or (
        agreement is not None
        and agreement_error is None
        and agreement_owner is not None
        and agreement_owner.purchase.id == original.purchase.id
    )
    scope_conflict = isinstance(agreement_error, (LbxScopeMismatch, PurchaseInventoryIncomplete))
    if not known_subscription and (not belongs_to_original or scope_conflict):
        raise agreement_error or PurchaseInventoryIncomplete()
    scope_proven = not scope_conflict and (belongs_to_original or (agreement is not None and agreement_error is None))
    await delegate(
        record_late_object,
        factory,
        original,
        customer,
        LateObjectEvidence(
            kind=Kind.SUBSCRIPTION,
            external_object_id=external_id,
            competing_tariff_id=point.tariff_id
            if scope_proven
            and (not belongs_to_original or point.tariff_id != original.purchase.accepted.selection.tariff_id)
            else None,
            read_finished_at=read_finished_at,
            agreement_id=agreement_id if scope_proven else None,
        ),
        unverified_relationship=None if scope_proven else (agreement_id, point.tariff_id),
    )
    if agreement_error is not None:
        raise agreement_error


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
            read_finished_at = await delegate(read_source_time, factory)
            agreements[identity] = point
            if point.agreement_id != identity:
                raise LbxScopeMismatch()
            prove_original_agreement(original, customer, point)
            if agreement_explicitly_open(point):
                await record_open_agreement(factory, original, customer, point, read_finished_at, delegate)
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
                agreement_read_at = None
                if point.agreement_id not in attempted_agreements:
                    attempted_agreements.add(point.agreement_id)
                    try:
                        agreement = await timely_point(
                            lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
                        )
                        agreement_read_at = await delegate(read_source_time, factory)
                        agreements[point.agreement_id] = agreement
                    except LbxScopeMismatch:
                        raise
                    except AppError as error:
                        first_error = first_error or error
                history = await point_owners(factory, customer, point, agreement, delegate)
                await record_subscription(
                    factory,
                    customer,
                    point,
                    agreement,
                    read_finished_at=read_finished_at,
                    delegate=delegate,
                    agreement_read_at=agreement_read_at,
                    history=history,
                    require_owner=True,
                )
            except LbxScopeMismatch:
                raise
            except AppError as error:
                first_error = first_error or error
    if first_error is not None:
        raise first_error
