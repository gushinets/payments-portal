"""Inspect late objects through the original purchase's GET-only recovery."""

from collections.abc import Awaitable, Callable
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
from app.integrations.lbx.errors import LbxResponseInvalid
from app.integrations.lbx.financial import (
    Agreement,
    Subscription,
    agreement_is_closed,
    prove_agreement,
    subscription_lifecycle,
)
from app.integrations.lbx.reconciliation import MAX_RELEVANT_SUBSCRIPTIONS, timely_point
from app.models import ExternalCreateOperationKind as Kind, ExternalSubscriptionLifecycleStatus as Lifecycle


def prove_original_agreement(original: ReleasedOriginal, customer: CustomerOpen, agreement: Agreement) -> None:
    purchase = original.purchase
    operation = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    prove_agreement(
        agreement, user_id=int(customer.provider_id), seller_id=purchase.accepted.seller_id, number=operation.key
    )
    if (
        operation.agreement_create_date is not None
        and agreement.create_date != operation.agreement_create_date.isoformat()
    ):
        raise LbxResponseInvalid()


async def record_subscription(
    factory: SessionFactory,
    original: ReleasedOriginal,
    customer: CustomerOpen,
    external_id: str,
    point: Subscription,
    agreement: Agreement | None,
    *,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    if subscription_lifecycle(point)[0] == Lifecycle.ENDED:
        return
    belongs_to_original = str(point.agreement_id) in original.agreement_ids
    if external_id not in original.subscription_ids:
        if agreement is None:
            raise PurchaseInventoryIncomplete()
        prove_original_agreement(original, customer, agreement)
        belongs_to_original = True
    if agreement is not None and agreement.user_id == int(customer.provider_id) and agreement_is_closed(agreement):
        return
    await delegate(
        record_late_object,
        factory,
        original,
        customer,
        LateObjectEvidence(
            kind=Kind.SUBSCRIPTION,
            external_object_id=external_id,
            competing_tariff_id=None if belongs_to_original else point.tariff_id,
            read_finished_at=await delegate(read_source_time, factory),
            agreement_id=str(point.agreement_id),
        ),
    )


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
            prove_original_agreement(original, customer, point)
            agreements[identity] = point
            if read_agreement and not agreement_is_closed(point):
                await delegate(
                    record_late_object,
                    factory,
                    original,
                    customer,
                    LateObjectEvidence(
                        kind=Kind.AGREEMENT,
                        external_object_id=str(identity),
                        read_finished_at=await delegate(read_source_time, factory),
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
                agreement = agreements.get(point.agreement_id)
                if point.agreement_id not in attempted_agreements:
                    attempted_agreements.add(point.agreement_id)
                    try:
                        agreement = await timely_point(
                            lambda: client.get_agreement(agreement_id=point.agreement_id, budget=budget), budget
                        )
                        agreements[point.agreement_id] = agreement
                    except AppError as error:
                        first_error = first_error or error
                await record_subscription(
                    factory, original, customer, str(identity), point, agreement, delegate=delegate
                )
            except AppError as error:
                first_error = first_error or error
    if first_error is not None:
        raise first_error
