"""Reusable outer I/O seam for future HTTP, worker and operator entrypoints."""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation
from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof, SubscriptionProof
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.preflight import PreflightAdmission, PreflightBudget, PreflightDeadlineExceeded
from app.domains.billing.work_contracts import WorkClaim
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.reconciliation import read_subscription_proof


async def reconcile_subscription(
    client: LbxServerClient,
    admission: PreflightAdmission,
    configuration: Settings,
    *,
    factory: SessionFactory,
    subscription_id: UUID,
    work_claim: WorkClaim | None = None,
    budget: PreflightBudget | None = None,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
) -> UUID:
    if configuration.lbx_configuration_error is not None:
        raise BillingRefused("billing_not_configured")
    subject = await delegate(
        claim_reconciliation,
        factory,
        configuration,
        subscription_id,
        io_timeout_seconds=admission.policy.total_timeout_seconds,
    )
    # Claim is committed before admission/HTTP; each delegated unit owns its DB.
    # Failure/cancellation leaves a finite lease for safe subsequent reclaim.
    started = utc_now()
    try:
        async with _budget(admission, budget) as active_budget:
            proof = await read_subscription_proof(client, subject, configuration, budget=active_budget)
            active_budget.check()
    except PreflightDeadlineExceeded:
        # Record a failed attempt, never apply facts returned after its budget.
        # Preflight retains any unfinished HTTP/cleanup resource ownership.
        proof = SubscriptionProof(
            started,
            utc_now(),
            IdentityProof.INCOMPLETE,
            CommercialProof.INCOMPLETE,
            None,
            None,
            {},
            False,
            False,
            ("read_budget_exhausted",),
            (),
        )
    return await delegate(apply_reconciliation, factory, subject, proof, work_claim=work_claim)


@asynccontextmanager
async def _budget(admission: PreflightAdmission, supplied: PreflightBudget | None) -> AsyncIterator[PreflightBudget]:
    if supplied is not None:
        supplied.check()
        yield supplied
    else:
        async with admission.operation() as budget:
            yield budget
