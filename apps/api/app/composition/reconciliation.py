"""Shared claimed read/apply orchestration for HTTP, worker and operator."""

from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import replace
from datetime import datetime
from functools import partial
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.composition.purchase_late_objects import (
    AgreementRead,
    ClosedAgreementReads,
    LatePointReview,
    SubscriptionRedirect,
    review_late_subscription,
    review_observed_agreement,
)
from app.composition.purchase_recovery import is_live_original_subscription, original_command
from app.composition.sources import SourceResources
from app.core.settings import Settings
from app.domains.billing.contracts import BillingRefused, CustomerOpen
from app.domains.billing.late_purchase_reviews import ReleasedOriginal, released_owners
from app.domains.billing.paid_policy import MeteringPolicy
from app.domains.billing.reconciliation import apply_reconciliation, claim_reconciliation, read_source_time
from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    IdentityProof,
    ReconciliationClaimBusy,
    SubscriptionProof,
    ReconciliationResult,
    ReconciliationSubject,
    SubscriptionCandidateSubject,
)
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import service
from app.domains.purchases.contracts import FinancialOperation, Purchase, PurchaseRefused
from app.domains.purchases.inventory_contracts import InventoryStale
from app.domains.purchases.recovery_evidence import OriginalPointFact, retain_original_point
from app.infrastructure.preflight import (
    PreflightAdmission,
    PreflightBudget,
    PreflightCleanupPending,
    PreflightDeadlineExceeded,
)
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.operator_contracts import ReviewResolution
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxError
from app.integrations.lbx.financial import Subscription, agreement_explicitly_open, prove_agreement
from app.integrations.lbx.reconciliation import complete_subscription_proof
from app.integrations.lbx.subscription_points import SubscriptionPointReads, read_subscription_points
from app.models import ExternalCreateOperationKind as Kind


async def review_inventory_points(
    client: LbxServerClient,
    factory: SessionFactory,
    points: SubscriptionPointReads,
    *,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
    closed_agreements: ClosedAgreementReads,
    defer_redirect: Callable[[SubscriptionRedirect], None] | None = None,
) -> LatePointReview | None:
    subject = points.subject
    customer = subject.customer
    if points.user is None or points.user.outer_id != customer.outer_key:
        return None
    observed = None
    if points.agreement is not None and points.agreement_read_at is not None:
        observed = AgreementRead(points.agreement, points.agreement_read_at)
        await review_observed_agreement(
            factory, customer, observed, expected_number=subject.agreement_key, delegate=delegate
        )
    point, read_at = points.subscription, points.subscription_read_at
    if point is None or read_at is None:
        return None
    redirected = point.agreement_id != int(subject.agreement_id)
    if redirected and defer_redirect is not None:
        if str(point.subscription_id) == subject.provider_subscription_id:
            defer_redirect(SubscriptionRedirect(customer, point, read_at))
        return None
    return await review_late_subscription(
        client,
        factory,
        customer,
        subject.provider_subscription_id,
        point,
        read_finished_at=read_at,
        budget=budget,
        delegate=delegate,
        closed_agreements=closed_agreements,
        observed_agreement=observed,
        read_agreement=redirected,
    )


async def read_subscription_proof(
    client: LbxServerClient,
    subject: ReconciliationSubject | SubscriptionCandidateSubject,
    configuration: Settings,
    *,
    factory: SessionFactory,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
    check_agreement_inventory: bool = False,
    on_subscription_redirect: Callable[[SubscriptionRedirect], None] | None = None,
) -> SubscriptionProof:
    """Persist only the DB-clock interval surrounding this actual source read."""
    point_clock = partial(delegate, read_source_time, factory)
    points = await read_subscription_points(client, subject, budget=budget, read_time=point_clock)
    if on_subscription_redirect is not None:
        await review_inventory_points(
            client,
            factory,
            points,
            budget=budget,
            delegate=delegate,
            closed_agreements={},
            defer_redirect=on_subscription_redirect,
        )
    return await complete_subscription_proof(
        client,
        configuration,
        points,
        budget=budget,
        check_agreement_inventory=check_agreement_inventory,
        read_time=point_clock,
    )


async def read_inventory_original_subscription(
    client: LbxServerClient,
    subject: SubscriptionCandidateSubject,
    operation: FinancialOperation,
    configuration: Settings,
    *,
    factory: SessionFactory,
    budget: PreflightBudget,
    work_claim: WorkClaim | None,
    delegate: Callable[..., Awaitable[Any]],
    closed_agreements: ClosedAgreementReads,
) -> SubscriptionProof | None:
    """Retain the exact fact before tariff I/O. Return no proof on an ownership conflict."""
    point_clock = partial(delegate, read_source_time, factory)
    points = await read_subscription_points(client, subject, budget=budget, read_time=point_clock)
    customer = subject.customer

    async def retain(original: FinancialOperation, external_id: str, observed_at: datetime) -> bool:
        fact = OriginalPointFact(
            operation_id=original.id,
            operation_kind=original.kind,
            external_object_id=external_id,
            fact="open" if original.kind == Kind.AGREEMENT else "live",
            point_read_finished_at=observed_at,
        )
        return await delegate(
            retain_original_point,
            factory,
            subject.purchase,
            customer,
            fact,
            request_document=original_command(subject.purchase, original, customer)
            if original.kind != Kind.AGREEMENT or original.agreement_create_date
            else None,
            recovering_id=operation.id,
            work_claim=work_claim,
        )

    review = await review_inventory_points(
        client, factory, points, budget=budget, delegate=delegate, closed_agreements=closed_agreements
    )
    if review is not None and review.products:
        return None
    if points.user is not None and points.user.outer_id == customer.outer_key:
        agreement_id = int(subject.agreement_id)
        agreement = points.agreement
        agreement_matches = False
        if agreement is not None and agreement.agreement_id == agreement_id:
            original = next(op for op in subject.purchase.operations if op.kind == Kind.AGREEMENT)
            try:
                prove_agreement(
                    agreement,
                    user_id=int(customer.provider_id),
                    seller_id=subject.purchase.accepted.seller_id,
                    number=subject.agreement_key,
                )
                agreement_matches = (
                    original.agreement_create_date is None
                    or agreement.create_date == original.agreement_create_date.isoformat()
                )
                explicitly_open = agreement_explicitly_open(agreement)
            except LbxError:
                explicitly_open = False  # Full normalization classifies failed proof.
            if agreement_matches and explicitly_open and points.agreement_read_at is not None:
                if not await retain(original, subject.agreement_id, points.agreement_read_at):
                    return None

        point, read_at = points.subscription, points.subscription_read_at
        if point is not None and read_at is not None:
            if (
                point.agreement_id == agreement_id
                and agreement_matches
                and is_live_original_subscription(subject.purchase, agreement, point, agreement_id=agreement_id)
            ):
                if not await retain(operation, subject.provider_subscription_id, read_at):
                    return None
    return await complete_subscription_proof(client, configuration, points, budget=budget, read_time=point_clock)


async def inventory_released_owners(
    factory: SessionFactory,
    customer_id: UUID,
    rows: Sequence[Subscription],
    conflicting_bindings: set[str],
    delegate: Callable[..., Awaitable[Any]],
) -> tuple[ReleasedOriginal, ...]:
    if not rows and not conflicting_bindings:
        return ()
    return await delegate(
        released_owners,
        factory,
        customer_id,
        {str(row.agreement_id) for row in rows},
        {str(row.subscription_id) for row in rows} | conflicting_bindings,
    )


async def review_late_redirects(
    client: LbxServerClient,
    factory: SessionFactory,
    customer: CustomerOpen,
    redirects: Sequence[SubscriptionRedirect],
    *,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> ClosedAgreementReads:
    """Retain proven points and carry verified agreement closures through this inventory pass."""
    closed_agreements: ClosedAgreementReads = {}
    failure: PreflightDeadlineExceeded | PreflightCleanupPending | None = None
    for redirect in redirects:
        if redirect.customer != customer:
            continue
        try:
            await review_late_subscription(
                client,
                factory,
                customer,
                str(redirect.point.subscription_id),
                redirect.point,
                read_finished_at=redirect.read_finished_at,
                budget=budget,
                delegate=delegate,
                read_agreement=failure is None,
                closed_agreements=closed_agreements,
            )
        except (PreflightDeadlineExceeded, PreflightCleanupPending) as error:
            if failure is None:
                failure = error
        except PurchaseRefused:
            if failure is None:
                raise
            # A rejected local write must not prevent independent proven points from being retained.
    if failure is not None:
        raise failure
    return closed_agreements


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
    check_agreement_inventory: bool = False,
    on_subscription_redirect: Callable[[SubscriptionRedirect], None] | None = None,
) -> ReconciliationResult:
    if configuration.lbx_configuration_error is not None:
        raise BillingRefused("billing_not_configured")
    try:
        subject = await delegate(
            claim_reconciliation,
            factory,
            configuration,
            subscription_id,
            io_timeout_seconds=admission.policy.total_timeout_seconds,
            work_claim=work_claim,
        )
    except BillingRefused as error:
        if work_claim is not None and error.code == "billing_busy":
            raise ReconciliationClaimBusy(error.code, error.status) from error
        raise
    if expected is not None:
        from app.domains.purchases.inventory import same_purchase

        if not same_purchase(subject.purchase, expected):
            raise PurchaseRefused("purchase_inventory_incomplete", 409)
    # Claim is committed before admission/HTTP; each delegated unit owns its DB.
    # Failure/cancellation leaves a finite lease for safe subsequent reclaim.
    started = await delegate(read_source_time, factory)
    redirects: list[SubscriptionRedirect] = []
    try:
        async with _budget(admission, budget) as active_budget:
            proof = await read_subscription_proof(
                client,
                subject,
                configuration,
                factory=factory,
                budget=active_budget,
                delegate=delegate,
                check_agreement_inventory=check_agreement_inventory,
                on_subscription_redirect=redirects.append if on_subscription_redirect is not None else None,
            )
            if resolution is not None:
                if "customer_identity_conflict" in proof.reasons:
                    # Keep canonical owner/fence/time checks before any negative write.
                    # A timely customer negative survives later I/O budget exhaustion,
                    # but cannot authorize or audit a successful operator resolution.
                    await delegate(
                        apply_reconciliation,
                        factory,
                        subject,
                        proof,
                        work_claim=work_claim,
                        clock_skew_seconds=configuration.paid_access_clock_skew_seconds,
                        metering_policy=MeteringPolicy.for_environment(configuration.app_env),
                    )
                    raise InventoryStale()
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
                inventory.require_clear(
                    subject.purchase, original=True, primary=resolution.request.resolution == "select-primary"
                )
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
    result = await delegate(
        apply_reconciliation,
        factory,
        subject,
        proof,
        work_claim=work_claim,
        resolution=resolution,
        clock_skew_seconds=configuration.paid_access_clock_skew_seconds,
        metering_policy=MeteringPolicy.for_environment(configuration.app_env),
    )
    if on_subscription_redirect is not None and result.proof.identity == IdentityProof.CONFLICT:
        for redirect in redirects:
            on_subscription_redirect(redirect)
    return result


async def reconcile_bound_purchase(
    sources: SourceResources,
    configuration: Settings,
    factory: SessionFactory,
    purchase: Purchase,
    budget: PreflightBudget,
    *,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
    check_agreement_inventory: bool = False,
) -> ReconciliationResult:
    try:
        subscription_id = await delegate(service.linked_subscription_id, factory, purchase)
        return await reconcile_subscription(
            sources.require_lbx(),
            sources.billing,
            configuration,
            factory=factory,
            subscription_id=subscription_id,
            budget=budget,
            delegate=delegate,
            check_agreement_inventory=check_agreement_inventory,
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
