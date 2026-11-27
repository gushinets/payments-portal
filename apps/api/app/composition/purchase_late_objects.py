"""Review exact late objects from inventory and the original purchase's GET-only recovery."""

from collections.abc import Awaitable, Callable
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
class InventoryAgreementRead:
    point: Agreement
    read_finished_at: datetime


type ClosedAgreementReads = dict[int, InventoryAgreementRead]


@dataclass(frozen=True)
class SubscriptionRedirect:
    customer: CustomerOpen
    point: Subscription
    read_finished_at: datetime


async def read_inventory_agreement(
    client: LbxServerClient,
    factory: SessionFactory,
    subscription: Subscription,
    *,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
    closed_agreements: ClosedAgreementReads | None = None,
    read_agreement: bool = True,
    user_id: int | None = None,
) -> InventoryAgreementRead | None:
    """Keep the agreement's own point-read time before evaluating the subscription or its owner."""
    cached = closed_agreements.get(subscription.agreement_id) if closed_agreements is not None else None
    if cached is not None:
        agreement = cached.point
    elif read_agreement:
        agreement = await candidate_point(
            lambda: client.get_agreement(agreement_id=subscription.agreement_id, budget=budget), budget
        )
    else:
        return None
    if agreement is None or (
        user_id is not None and (agreement.agreement_id, agreement.user_id) != (subscription.agreement_id, user_id)
    ):
        return None
    return cached or InventoryAgreementRead(agreement, await delegate(read_source_time, factory))


def historical_subscription_matches(
    history: tuple[ReleasedOriginal, ...], provider_id: str, agreement_id: str | None
) -> list[ReleasedOriginal]:
    return [old for old in history if provider_id in old.subscription_ids] or [
        old for old in history if agreement_id in old.agreement_ids
    ]


def historical_subscription_owner(
    history: tuple[ReleasedOriginal, ...], provider_id: str, agreement_id: str | None
) -> ReleasedOriginal | None:
    matches = historical_subscription_matches(history, provider_id, agreement_id)
    if len(matches) > 1:
        raise PurchaseInventoryIncomplete()
    return matches[0] if matches else None


async def released_subscription_owner(
    factory: SessionFactory,
    customer: CustomerOpen,
    point: Subscription,
    delegate: Callable[..., Awaitable[Any]],
    *,
    agreement_number: str | None = None,
) -> ReleasedOriginal | None:
    agreement_id, provider_id = str(point.agreement_id), str(point.subscription_id)
    owners = await delegate(
        released_owners, factory, customer.customer_id, {agreement_id}, {provider_id}, agreement_number=agreement_number
    )
    original = historical_subscription_owner(owners, provider_id, agreement_id)
    if original is not None or agreement_number is None:
        return original
    if len(owners) > 1:
        raise PurchaseInventoryIncomplete()
    return owners[0] if owners else None


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
    closed_agreements: ClosedAgreementReads | None = None,
) -> ReleasedOriginal | None:
    """Check whether the exact subscription point belongs to a released purchase."""
    if str(point.subscription_id) != provider_id:
        raise LbxScopeMismatch()
    original = await released_subscription_owner(factory, customer, point, delegate)
    if original is None:
        agreement_read = await read_inventory_agreement(
            client, factory, point, budget=budget, delegate=delegate, closed_agreements=closed_agreements
        )
        if agreement_read is None:
            return None
        return await record_inventory_late_subscription(
            factory,
            customer,
            point,
            agreement_read,
            read_finished_at=read_finished_at,
            delegate=delegate,
            closed_agreements=closed_agreements,
        )
    await review_historical_subscription(
        client,
        factory,
        original,
        customer,
        point,
        read_finished_at=read_finished_at,
        budget=budget,
        delegate=delegate,
        closed_agreements=closed_agreements,
    )
    return original


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
    read_agreement: bool = True,
    closed_agreements: ClosedAgreementReads | None = None,
) -> bool:
    """Keep the exact subscription fact when follow-up evidence is unavailable."""
    agreement_read, failure = None, None
    try:
        agreement_read = await read_inventory_agreement(
            client,
            factory,
            point,
            budget=budget,
            delegate=delegate,
            closed_agreements=closed_agreements,
            read_agreement=read_agreement,
        )
    except LbxScopeMismatch:
        raise
    except AppError as error:
        failure = error
    try:
        await record_subscription(
            factory,
            original,
            customer,
            point,
            agreement_read.point if agreement_read else None,
            read_finished_at=read_finished_at,
            agreement_read_at=agreement_read.read_finished_at if agreement_read else None,
            delegate=delegate,
            closed_agreements=closed_agreements,
        )
    except (LbxResponseInvalid, LbxScopeMismatch):
        return False  # This historical object could not be verified for its customer.
    if failure is not None:
        raise failure
    return agreement_read is not None


async def record_inventory_late_subscription(
    factory: SessionFactory,
    customer: CustomerOpen,
    point: Subscription,
    agreement_read: InventoryAgreementRead,
    *,
    read_finished_at: datetime,
    delegate: Callable[..., Awaitable[Any]],
    closed_agreements: ClosedAgreementReads | None = None,
) -> ReleasedOriginal | None:
    agreement = agreement_read.point
    if agreement.agreement_number is None:
        return None
    original = await released_subscription_owner(
        factory, customer, point, delegate, agreement_number=agreement.agreement_number
    )
    if original is None:
        return None
    await record_subscription(
        factory,
        original,
        customer,
        point,
        agreement,
        read_finished_at=read_finished_at,
        agreement_read_at=agreement_read.read_finished_at,
        delegate=delegate,
        closed_agreements=closed_agreements,
    )
    return original


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


async def record_subscription(
    factory: SessionFactory,
    original: ReleasedOriginal,
    customer: CustomerOpen,
    point: Subscription,
    agreement: Agreement | None,
    *,
    read_finished_at: datetime,
    delegate: Callable[..., Awaitable[Any]],
    agreement_read_at: datetime | None = None,
    closed_agreements: ClosedAgreementReads | None = None,
) -> None:
    if agreement is not None and (agreement.agreement_id, agreement.user_id) != (
        point.agreement_id,
        int(customer.provider_id),
    ):
        raise LbxScopeMismatch()
    incomplete: AppError | None = None
    try:
        lifecycle, _, _ = subscription_lifecycle(point)
    except LbxResponseInvalid as error:
        # The agreement point can still prove an independently open object.
        lifecycle = None
        incomplete = error
    nonterminal_subscription = lifecycle not in (None, Lifecycle.ENDED)
    external_id = str(point.subscription_id)
    agreement_id = str(point.agreement_id)
    belongs_to_original = agreement_id in original.agreement_ids
    known_subscription = external_id in original.subscription_ids
    if agreement is not None:
        requires_original_proof = belongs_to_original or not known_subscription
        prove_for_subscription = nonterminal_subscription and requires_original_proof
        try:
            if prove_for_subscription:
                prove_original_agreement(original, customer, agreement)
                belongs_to_original = True
            if (nonterminal_subscription or closed_agreements is not None) and agreement_is_closed(agreement):
                if closed_agreements is not None and agreement_read_at is not None:
                    if requires_original_proof and not prove_for_subscription:
                        prove_original_agreement(original, customer, agreement)
                    closed_agreements[agreement.agreement_id] = InventoryAgreementRead(agreement, agreement_read_at)
                if nonterminal_subscription:
                    return
            elif agreement_read_at is not None:
                operation = next(op for op in original.purchase.operations if op.kind == Kind.AGREEMENT)
                if (belongs_to_original or agreement.agreement_number == operation.key) and agreement_explicitly_open(
                    agreement
                ):
                    if not prove_for_subscription:
                        prove_original_agreement(original, customer, agreement)
                    await record_open_agreement(factory, original, customer, agreement, agreement_read_at, delegate)
        except PurchaseInventoryIncomplete as error:
            # Only a retained subscription ID proves ownership independently of the conflicting agreement.
            if not known_subscription:
                raise
            incomplete = incomplete or error
        except LbxScopeMismatch as error:
            if not nonterminal_subscription or prove_for_subscription:
                raise
            incomplete = error
        except LbxResponseInvalid as error:
            # Missing follow-up evidence can leave inventory incomplete while
            # the exact subscription and its retained owner are already proven.
            if not nonterminal_subscription or not (belongs_to_original or known_subscription):
                raise
            incomplete = error
    if not nonterminal_subscription:
        if incomplete is not None:
            raise incomplete
        return
    if not (belongs_to_original or known_subscription):
        raise PurchaseInventoryIncomplete()
    scope_proven = belongs_to_original or agreement is not None
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
                await record_subscription(
                    factory,
                    original,
                    customer,
                    point,
                    agreement,
                    read_finished_at=read_finished_at,
                    delegate=delegate,
                    agreement_read_at=agreement_read_at,
                )
            except LbxScopeMismatch:
                raise
            except AppError as error:
                first_error = first_error or error
    if first_error is not None:
        raise first_error
