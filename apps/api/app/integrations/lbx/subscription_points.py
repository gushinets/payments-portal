"""Bounded LBX customer, agreement and subscription point reads."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from app.domains.billing.reconciliation_contracts import ReconciliationSubject, SubscriptionCandidateSubject
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.customer import LbxUser
from app.integrations.lbx.errors import LbxError
from app.integrations.lbx.financial import Agreement, Subscription


@dataclass(frozen=True)
class SubscriptionPointReads:
    subject: ReconciliationSubject | SubscriptionCandidateSubject
    started_at: datetime
    user: LbxUser | None
    agreement: Agreement | None
    subscription: Subscription | None
    agreement_read_at: datetime | None
    subscription_read_at: datetime | None
    reads: tuple[str, ...]
    failures: tuple[str, ...]


async def timely_point[T](read: Callable[[], Awaitable[T]], budget: PreflightBudget) -> T:
    """Reject both values and scope errors returned after the read deadline."""
    budget.check()
    try:
        value = await read()
    except LbxError:
        budget.check()
        raise
    budget.check()
    return value


async def read_subscription_points(
    client: LbxServerClient,
    subject: ReconciliationSubject | SubscriptionCandidateSubject,
    *,
    budget: PreflightBudget,
    read_time: Callable[[], Awaitable[datetime]],
) -> SubscriptionPointReads:
    started = await read_time()
    user, agreement, subscription = None, None, None
    agreement_read_at, subscription_read_at = None, None
    reads: list[str] = []
    failures: list[str] = []
    # Read owner and lifecycle before potentially slow policy. Timely negatives
    # survive an unavailable policy, while every late point result is rejected.
    try:
        user = await timely_point(
            lambda: client.get_user(user_id=int(subject.customer.provider_id), budget=budget), budget
        )
        reads.append("customer")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("customer:" + error.code)
    try:
        agreement = await timely_point(
            lambda: client.get_agreement(agreement_id=int(subject.agreement_id), budget=budget), budget
        )
        agreement_read_at = await read_time()
        reads.append("agreement")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("agreement:" + error.code)
    try:
        subscription = await timely_point(
            lambda: client.get_subscription(subscription_id=int(subject.provider_subscription_id), budget=budget),
            budget,
        )
        subscription_read_at = await read_time()
        reads.append("subscription")
    except (LbxError, PreflightDeadlineExceeded) as error:
        failures.append("subscription:" + error.code)
    return SubscriptionPointReads(
        subject=subject,
        started_at=started,
        user=user,
        agreement=agreement,
        subscription=subscription,
        agreement_read_at=agreement_read_at,
        subscription_read_at=subscription_read_at,
        reads=tuple(reads),
        failures=tuple(failures),
    )
