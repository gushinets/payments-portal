"""Interpret released-purchase history during live subscription inventory."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from uuid import UUID

from app.domains.billing.operator_contracts import LateObjectDisposition, LateSubscriptionPoint
from app.domains.billing.reconciliation import read_source_time
from app.domains.billing.terminal_resolution import ReleasedPurchase, record_late_object, released_object_owners
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import Purchase
from app.integrations.lbx.errors import LbxResponseInvalid
from app.integrations.lbx.financial import (
    Agreement,
    Subscription,
    agreement_is_closed,
    prove_agreement,
    subscription_lifecycle,
)
from app.models import ExternalCreateOperationKind as Kind, ExternalSubscriptionLifecycleStatus as Lifecycle


@dataclass
class ReleasedSubscriptionInventory:
    agreements: dict[str, ReleasedPurchase] = field(default_factory=dict)
    subscriptions: dict[str, ReleasedPurchase] = field(default_factory=dict)
    _checked_agreements: set[str] = field(default_factory=set, init=False)
    _checked_subscriptions: set[str] = field(default_factory=set, init=False)

    async def load(
        self,
        factory: SessionFactory,
        customer_id: UUID,
        rows: tuple[Subscription, ...],
        delegate: Callable[..., Awaitable[Any]],
    ) -> None:
        await self._load_ids(
            factory,
            customer_id,
            {str(row.agreement_id) for row in rows},
            {str(row.subscription_id) for row in rows},
            delegate,
        )

    async def owner_for_point(
        self,
        factory: SessionFactory,
        customer_id: UUID,
        subscription_id: str,
        agreement_id: str,
        delegate: Callable[..., Awaitable[Any]],
    ) -> ReleasedPurchase | None:
        await self._load_ids(factory, customer_id, {agreement_id}, {subscription_id}, delegate)
        return self.subscriptions.get(subscription_id) or self.agreements.get(agreement_id)

    async def _load_ids(
        self,
        factory: SessionFactory,
        customer_id: UUID,
        agreements: set[str],
        subscriptions: set[str],
        delegate: Callable[..., Awaitable[Any]],
    ) -> None:
        agreements = agreements - self._checked_agreements
        subscriptions = subscriptions - self._checked_subscriptions
        if not (agreements or subscriptions):
            return
        owners = await delegate(
            released_object_owners,
            factory,
            customer_id,
            tuple(agreements),
            tuple(subscriptions),
        )
        self._checked_agreements.update(agreements)
        self._checked_subscriptions.update(subscriptions)
        for owner in owners:
            self.agreements.update((identity, owner) for identity in owner.agreement_ids)
            self.subscriptions.update((identity, owner) for identity in owner.subscription_ids)

    def owner(self, row: Subscription) -> ReleasedPurchase | None:
        return self.subscriptions.get(str(row.subscription_id)) or self.agreements.get(str(row.agreement_id))


async def observe_released_subscription(
    purchase: Purchase,
    point: Subscription,
    read_agreement: Callable[[], Awaitable[Agreement | None]],
    *,
    read_started_at: datetime,
    read_finished_at: datetime,
    subscription_id: int,
    user_id: int,
    factory: SessionFactory,
    delegate: Callable[..., Awaitable[Any]],
) -> LateObjectDisposition:
    operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    observation = LateSubscriptionPoint(str(point.agreement_id), point.tariff_id)

    async def record(observed: LateSubscriptionPoint, finished: datetime) -> LateObjectDisposition:
        return await delegate(
            record_late_object,
            factory,
            purchase,
            operation.id,
            str(subscription_id),
            read_started_at,
            read_finished_at=finished,
            subscription_point=observed,
        )

    disposition = await record(observation, read_finished_at)
    if disposition != LateObjectDisposition.NEEDS_ORIGINAL_PROOF:
        return disposition
    # Confirmation of a possible original requires a provider read. The writer
    # rechecks the permanent binding after that read.
    agreement = await read_agreement()
    if agreement is None:
        raise LbxResponseInvalid()
    original = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    prove_agreement(agreement, user_id=user_id, seller_id=purchase.accepted.seller_id, number=original.key)
    if agreement_is_closed(agreement) or subscription_lifecycle(point)[0] == Lifecycle.ENDED:
        return LateObjectDisposition.CLEAR
    finished = await delegate(read_source_time, factory)
    return await record(replace(observation, original_live_proven=True), finished)
