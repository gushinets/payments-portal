"""One bounded reread after a closed synchronous apply unit; no SQL over HTTP."""

from starlette.concurrency import run_in_threadpool
from collections.abc import Callable, Awaitable
from typing import Any

from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.readback import apply_readback, capture_readback
from app.domains.billing.readback_contracts import (
    BoundReadbackSubject,
    ReadbackApplyResult,
    ReadbackRecheck,
    ScopedReadbackFinding,
)
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.preflight import (
    PreflightBudget,
    PreflightDeadlineExceeded,
    PreflightClosed,
    PreflightSaturated,
    PreflightCleanupPending,
)
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.readback import read_bound_finding


async def apply_bound_readback(
    client: LbxServerClient,
    configuration: Settings,
    *,
    factory: SessionFactory,
    finding: ScopedReadbackFinding,
    budget: PreflightBudget,
    work_claim: WorkClaim | None = None,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
) -> ReadbackApplyResult:
    try:
        return await delegate(apply_readback, factory, configuration, finding, work_claim=work_claim)
    except ReadbackRecheck:
        pass
    # The failed unit has rolled back and closed before either capture or HTTP.
    try:
        budget.check()
        subject = await delegate(
            capture_readback,
            factory,
            configuration,
            finding.subject.purchase,
            deadline=finding.subject.deadline,
            expected=finding.subject,
            candidate_id=finding.negative.provider_subscription_id if finding.negative else finding.candidate_id,
        )
        if not isinstance(subject, BoundReadbackSubject):
            raise BillingRefused("subscription_reconciliation_stale", 409)
        reread = await read_bound_finding(client, subject, budget=budget)
    except (PreflightDeadlineExceeded, PreflightClosed, PreflightSaturated, PreflightCleanupPending):
        return await delegate(apply_readback, factory, configuration, finding, hint_only=True, work_claim=work_claim)
    except BillingRefused as error:
        if error.code != "subscription_reconciliation_stale":
            raise
        return await delegate(apply_readback, factory, configuration, finding, hint_only=True, work_claim=work_claim)
    try:
        return await delegate(apply_readback, factory, configuration, reread, work_claim=work_claim)
    except ReadbackRecheck:
        return await delegate(apply_readback, factory, configuration, reread, hint_only=True, work_claim=work_claim)
