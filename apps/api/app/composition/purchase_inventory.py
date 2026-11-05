"""Typed bounded inventory findings, independent of strict competition admission."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID
from collections.abc import Awaitable, Callable
from typing import Any
from starlette.concurrency import run_in_threadpool
from app.core.errors import AppError
from app.core.time import utc_now
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.readback_contracts import BoundReadbackSubject, ScopedReadbackFinding
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import Purchase, FinancialOperation, PurchaseRefused, PurchaseInventoryIncomplete
from app.domains.purchases.inventory import deadline_only_inventory_recovery, other_inventory_purchase
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.customer import LbxUser
from app.integrations.lbx.errors import LbxScopeMismatch, LbxResponseInvalid
from app.integrations.lbx.financial import (
    Agreement,
    Subscription,
    inventory_terminal,
    prove_agreement,
    prove_effective_terms,
)
from app.integrations.lbx.readback import inspect_readback
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State

MAX_RELEVANT_SUBSCRIPTIONS = 20


def _operation(purchase: Purchase, kind: Kind) -> FinancialOperation:
    return next(op for op in purchase.operations if op.kind == kind)


@dataclass(frozen=True)
class InventoryRead:
    findings: tuple[ScopedReadbackFinding, ...]
    refusal: AppError | None = None

    def require_complete(self) -> None:
        if self.refusal is not None:
            raise self.refusal


async def _inventory(
    client: LbxServerClient,
    purchase: Purchase,
    customer: CustomerOpen,
    factory: SessionFactory,
    *,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
    inventory: tuple[Subscription, ...] | None = None,
    subscription_points: dict[int, Subscription] | None = None,
    agreement_points: dict[int, Agreement] | None = None,
    subjects: tuple[BoundReadbackSubject, ...] = (),
    user: LbxUser | None = None,
    read_started_at: datetime | None = None,
) -> InventoryRead:
    budget.check()
    findings: dict[UUID, ScopedReadbackFinding] = {}
    started = read_started_at or utc_now()
    refusal = None
    try:
        if subjects and user is None:
            user = await client.get_user(user_id=int(customer.provider_id), budget=budget)
        await _inspect_inventory(
            client,
            purchase,
            customer,
            factory,
            budget=budget,
            delegate=delegate,
            inventory=inventory,
            subscription_points=subscription_points,
            agreement_points=agreement_points,
            subjects=subjects,
            user=user,
            findings=findings,
            read_started_at=started,
        )
    except AppError as error:
        refusal = error
    return InventoryRead(tuple(findings.values()), refusal)


async def _inspect_inventory(
    client: LbxServerClient,
    purchase: Purchase,
    customer: CustomerOpen,
    factory: SessionFactory,
    *,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
    inventory: tuple[Subscription, ...] | None = None,
    subscription_points: dict[int, Subscription] | None = None,
    agreement_points: dict[int, Agreement] | None = None,
    subjects: tuple[BoundReadbackSubject, ...] = (),
    user: LbxUser | None = None,
    findings: dict[UUID, ScopedReadbackFinding],
    read_started_at: datetime,
) -> None:
    subscription_points = {} if subscription_points is None else subscription_points
    agreement_points = {} if agreement_points is None else agreement_points
    rows = inventory
    if rows is None:
        rows = await client.discover_subscriptions(user_id=int(customer.provider_id), budget=budget)
    relevant = [row for row in rows if row.tariff_id == purchase.accepted.selection.tariff_id]
    if len(relevant) > MAX_RELEVANT_SUBSCRIPTIONS:
        raise PurchaseInventoryIncomplete()
    subscription = _operation(purchase, Kind.SUBSCRIPTION)
    own = subscription.bound_id
    pending_binding = False
    for candidate in relevant:
        budget.check()
        point = subscription_points.get(candidate.subscription_id)
        if point is None:
            point = await client.get_subscription(subscription_id=candidate.subscription_id, budget=budget)
            subscription_points[candidate.subscription_id] = point
        if (point.agreement_id, point.tariff_id) != (
            candidate.agreement_id,
            candidate.tariff_id,
        ):
            raise PurchaseRefused("purchase_inventory_incomplete", 409)
        agreement = agreement_points.get(point.agreement_id)
        if agreement is None:
            agreement = await client.get_agreement(agreement_id=point.agreement_id, budget=budget)
            agreement_points[point.agreement_id] = agreement
        if agreement.user_id != int(customer.provider_id):
            raise LbxScopeMismatch()
        subject = next(
            (
                item
                for item in subjects
                if (item.provider_subscription_id, item.agreement_id)
                == (str(candidate.subscription_id), str(candidate.agreement_id))
            ),
            None,
        )
        if subject is not None:
            findings[subject.purchase.id] = inspect_readback(
                subject,
                user=user,
                agreement=agreement,
                subscription=point,
                window=(read_started_at, utc_now()),
                reads=("customer", "agreement", "subscription"),
            )
        try:
            terminal = inventory_terminal(point, agreement)
        except LbxResponseInvalid:
            raise PurchaseInventoryIncomplete() from None
        if not terminal and str(candidate.subscription_id) != own:
            agreement_op = _operation(purchase, Kind.AGREEMENT)
            original_candidate = (
                own is None
                and subscription.candidate_id in {None, str(candidate.subscription_id)}
                and agreement_op.state == State.BOUND
                and agreement_op.bound_id == str(point.agreement_id)
                and sum(row.agreement_id == point.agreement_id for row in rows) == 1
                and (
                    subscription.state in {State.POSSIBLE_SEND, State.UNKNOWN}
                    or await delegate(deadline_only_inventory_recovery, factory, purchase)
                )
            )
            other = (
                purchase
                if original_candidate
                else await delegate(
                    other_inventory_purchase, factory, purchase, candidate.subscription_id, point.agreement_id
                )
            )
            if other is not None:
                prove_agreement(
                    agreement,
                    user_id=int(customer.provider_id),
                    seller_id=other.accepted.seller_id,
                    number=_operation(other, Kind.AGREEMENT).key,
                )
                prove_effective_terms(
                    point,
                    agreement_id=point.agreement_id,
                    selection=other.accepted.selection,
                    offer=other.accepted.offer,
                )
                if _operation(other, Kind.SUBSCRIPTION).bound_id is None:
                    if sum(row.agreement_id == point.agreement_id for row in rows) != 1:
                        raise PurchaseRefused("purchase_existing_subscription_review", 409)
                    # Recovery alone can bind an original uncertain command.
                    # Check the remaining candidates before deferring so real
                    # competition is not hidden by that pending binding.
                    pending_binding = True
                continue
            raise PurchaseRefused("purchase_existing_subscription_review", 409)
    if pending_binding:
        raise PurchaseInventoryIncomplete()
    if inventory is not None:
        return
    again = await client.discover_subscriptions(user_id=int(customer.provider_id), budget=budget)

    def identity(row: Subscription) -> tuple[int, int, int]:
        return row.subscription_id, row.agreement_id, row.tariff_id

    if sorted(map(identity, rows)) != sorted(map(identity, again)):
        raise PurchaseRefused("purchase_inventory_incomplete", 409)
