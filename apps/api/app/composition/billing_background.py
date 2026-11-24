"""Worker entrypoints for bounded billing source work."""

from collections.abc import Awaitable, Callable
from typing import Any
from uuid import UUID

from app.composition.billing import recover_customer
from app.composition.purchases import recover_financial
from app.composition.purchase_inventory import collect_inventory
from app.composition.sources import SourceResources
from app.core.errors import AppError
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.paid_policy import MeteringPolicy
from app.core.settings import Settings
from app.domains.billing.discovery import persist_discoveries, apply_inventory
from app.domains.billing import background_recovery as recovery, work
from app.domains.billing.work_contracts import WorkAttemptOutcome, WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.widget_activation_poll import (
    MAX_READ_CLEANUP_SECONDS,
    WidgetActivationReadFailure,
    WidgetActivationResult,
    finish_widget_activation_read,
    prepare_widget_activation_read,
)
from app.infrastructure.preflight import (
    PreflightAdmission,
    PreflightBudget,
    PreflightDeadlineExceeded,
)
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxError
from app.integrations.lbx.financial import subscription_lifecycle
from app.integrations.lbx.reconciliation import timely_point
from app.infrastructure.sentry import report_billing_recovery_exhausted
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State


async def check_widget_activation(
    client: LbxServerClient,
    configuration: Settings,
    *,
    factory: SessionFactory,
    claim: WorkClaim,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> WorkAttemptOutcome:
    attempt = await delegate(prepare_widget_activation_read, factory, configuration, claim)
    if attempt is None:
        return WorkAttemptOutcome.COMPLETED
    budget.limit_deadline(attempt.monotonic_deadline, max_cleanup_seconds=MAX_READ_CLEANUP_SECONDS)
    result: WidgetActivationResult
    try:
        point = await timely_point(
            lambda: client.get_subscription(subscription_id=attempt.provider_subscription_id, budget=budget), budget
        )
        _, _, result = subscription_lifecycle(point)
        budget.check()
    except PreflightDeadlineExceeded as failure:
        result = WidgetActivationReadFailure(failure.code) if budget.source_scheduled else None
    except LbxError as failure:
        result = WidgetActivationReadFailure(failure.code)
    return await delegate(finish_widget_activation_read, factory, configuration, claim, attempt, result)


async def recover_operation(
    client: LbxServerClient,
    admission: PreflightAdmission,
    configuration: Settings,
    *,
    factory: SessionFactory,
    claim: WorkClaim,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    try:
        subject = await delegate(recovery.subject, factory, configuration, claim)
    except BillingRefused as error:
        if error.code == "billing_work_stale" and await delegate(recovery.recovery_paused, factory, claim):
            return  # Deadline can revoke a claim before its first source read.
        raise
    if subject is None:
        return  # Fixed deadline reached; provider-free escalation owns notification.
    kind, user_id, purchase_id, current, state = subject
    if state in {State.PENDING, State.PROVEN_NOT_SENT, State.BOUND}:
        await delegate(recovery.finish_recovery, factory, claim)
        return
    try:
        if kind == Kind.CUSTOMER:
            await recover_customer(client, factory, current, budget=budget, work_claim=claim, delegate=delegate)
        else:
            await recover_financial(
                SourceResources(admission, None, client, billing=admission),
                configuration,
                factory=factory,
                user_id=user_id,
                purchase_id=purchase_id,
                operation_id=UUID(claim.reference),
                work_claim=claim,
                budget=budget,
                delegate=delegate,
            )
    except AppError as error:
        # Local contention is retryable queue work, never a source result or
        # proof of no-send. Shared apply owns any authoritative conflict.
        saved = await delegate(
            work.retry_work, factory, claim, error=error.code if error.code == "billing_busy" else "recovery_incomplete"
        )
        if not saved:
            if await delegate(recovery.recovery_paused, factory, claim):
                return  # Deadline deliberately revoked this owner's late result.
            raise BillingRefused("billing_work_stale", 409) from error
        return
    await delegate(recovery.finish_recovery, factory, claim)


async def apply_deadline(factory: SessionFactory, claim: WorkClaim, *, delegate: Callable[..., Awaitable[Any]]) -> None:
    notice = await delegate(recovery.apply_deadline, factory, claim)
    if notice is not None:
        notified = await delegate(report_billing_recovery_exhausted, notice)
        await delegate(recovery.finish_deadline_notification, factory, claim, notified=notified)


async def inventory_customer(
    client: LbxServerClient,
    admission: PreflightAdmission,
    configuration: Settings,
    *,
    factory: SessionFactory,
    claim: WorkClaim,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    try:
        await _inventory_customer(
            client, admission, configuration, factory=factory, claim=claim, budget=budget, delegate=delegate
        )
    except AppError as error:
        saved = await delegate(
            work.retry_work,
            factory,
            claim,
            error="billing_busy" if error.code == "billing_busy" else "inventory_incomplete",
        )
        if not saved:
            raise BillingRefused("billing_work_stale", 409) from error


async def _inventory_customer(
    client: LbxServerClient,
    admission: PreflightAdmission,
    configuration: Settings,
    *,
    factory: SessionFactory,
    claim: WorkClaim,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> None:
    current, _ = await delegate(recovery.customer_snapshot, factory, configuration, UUID(claim.reference))
    result = await collect_inventory(
        client,
        admission,
        configuration,
        factory=factory,
        customer=current,
        budget=budget,
        work_claim=claim,
        delegate=delegate,
    )
    reason = (
        "inventory_conflict"
        if result.conflicts
        else ("inventory_incomplete" if not result.complete or result.pending else None)
    )
    result = await delegate(persist_discoveries, factory, claim, result)
    await delegate(
        apply_inventory,
        factory,
        claim,
        result,
        reason,
        clock_skew_seconds=configuration.paid_access_clock_skew_seconds,
        metering_policy=MeteringPolicy.for_environment(configuration.app_env),
    )
