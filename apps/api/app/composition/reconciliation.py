"""Shared claimed read/apply orchestration for HTTP, worker and operator."""

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import replace
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.composition.sources import SourceResources
from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused
from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation, read_source_time
from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    IdentityProof,
    SubscriptionProof,
    ReconciliationResult,
    ReconciliationSubject,
    SubscriptionCandidateSubject,
)
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.domains.purchases.contracts import Purchase, PurchaseRefused
from app.infrastructure.preflight import PreflightAdmission, PreflightBudget, PreflightDeadlineExceeded
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.operator_contracts import ReviewResolution
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.reconciliation import read_subscription_proof as read_lbx_subscription_proof


async def read_subscription_proof(
    client: LbxServerClient,
    subject: ReconciliationSubject | SubscriptionCandidateSubject,
    configuration: Settings,
    *,
    factory: SessionFactory,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
) -> SubscriptionProof:
    """Persist only the DB-clock interval surrounding this actual source read."""
    started = await delegate(read_source_time, factory)
    proof = await read_lbx_subscription_proof(client, subject, configuration, budget=budget)
    finished = await delegate(read_source_time, factory)
    return replace(proof, read_started_at=started, read_finished_at=finished)


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
    resolution: ReviewResolution | None = None,
    expected: Purchase | None = None,
) -> ReconciliationResult:
    if configuration.lbx_configuration_error is not None:
        raise BillingRefused("billing_not_configured")
    subject = await delegate(
        claim_reconciliation,
        factory,
        configuration,
        subscription_id,
        io_timeout_seconds=admission.policy.total_timeout_seconds,
    )
    if expected is not None:
        from app.domains.purchases.inventory import same_purchase

        if not same_purchase(subject.purchase, expected):
            raise PurchaseRefused("purchase_inventory_incomplete", 409)
    # Claim is committed before admission/HTTP; each delegated unit owns its DB.
    # Failure/cancellation leaves a finite lease for safe subsequent reclaim.
    started = await delegate(read_source_time, factory)
    try:
        async with _budget(admission, budget) as active_budget:
            proof = await read_subscription_proof(
                client, subject, configuration, factory=factory, budget=active_budget, delegate=delegate
            )
            if resolution is not None:
                from app.composition.purchase_inventory import collect_inventory
                from app.domains.purchases.inventory_contracts import InventoryCandidateProof

                inventory = await collect_inventory(
                    client,
                    admission,
                    configuration,
                    factory=factory,
                    customer=subject.customer,
                    budget=active_budget,
                    expected=resolution.purchase,
                    reuse=InventoryCandidateProof(subject.purchase, subject.provider_subscription_id, proof),
                    delegate=delegate,
                )
                inventory.require_clear(subject.purchase, original=True)
                resolution = replace(resolution, inventory=inventory)
    except PreflightDeadlineExceeded:
        # Record a failed attempt, never apply facts returned after its budget.
        # Preflight retains any unfinished HTTP/cleanup resource ownership.
        proof = SubscriptionProof(
            started,
            await delegate(read_source_time, factory),
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
    return await delegate(apply_reconciliation, factory, subject, proof, work_claim=work_claim, resolution=resolution)


async def reconcile_bound_purchase(
    sources: SourceResources,
    configuration: Settings,
    factory: SessionFactory,
    purchase: Purchase,
    budget: PreflightBudget,
) -> ReconciliationResult:
    try:
        subscription_id = await run_in_threadpool(service.linked_subscription_id, factory, purchase)
        return await reconcile_subscription(
            sources.require_lbx(),
            sources.billing,
            configuration,
            factory=factory,
            subscription_id=subscription_id,
            budget=budget,
        )
    except BillingRefused as error:
        if error.code in {
            "subscription_reconciliation_busy",
            "subscription_reconciliation_stale",
            "subscription_provenance_changed",
            "billing_busy",
        }:
            raise PurchaseRefused("purchase_pending", 409) from None
        raise


@asynccontextmanager
async def _budget(admission: PreflightAdmission, supplied: PreflightBudget | None) -> AsyncIterator[PreflightBudget]:
    if supplied is not None:
        supplied.check()
        yield supplied
    else:
        # Each source read checks this budget. Keep normalization of timely
        # negative facts outside a scope timeout that would discard them.
        async with admission.operation(bound_scope=False) as budget:
            yield budget
