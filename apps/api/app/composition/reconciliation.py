"""Reusable outer I/O seam for future HTTP, worker and operator entrypoints."""

from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation
from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof, SubscriptionProof
from app.domains.catalog.publication import SessionFactory
from app.infrastructure.preflight import PreflightAdmission, PreflightDeadlineExceeded
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.reconciliation import read_subscription_proof


async def reconcile_subscription(
    client: LbxServerClient,
    admission: PreflightAdmission,
    configuration: Settings,
    *,
    factory: SessionFactory,
    subscription_id: UUID,
) -> UUID:
    if configuration.lbx_configuration_error is not None:
        raise BillingRefused("billing_not_configured")
    subject = await run_in_threadpool(
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
        async with admission.operation() as budget:
            proof = await read_subscription_proof(client, subject, configuration, budget=budget)
            budget.check()
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
    return await run_in_threadpool(apply_reconciliation, factory, subject, proof)
