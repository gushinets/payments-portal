"""Typed GET-only original recovery and BOUND readback; no financial send authority."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.concurrency import run_in_threadpool

from app.composition.purchase_financial import _find_financial
from app.composition.purchase_observation import prepared_subscription_observation
from app.composition.readback import apply_bound_readback
from app.composition.sources import SourceResources
from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.customer_conflicts import record_customer_conflict
from app.domains.billing.readback import capture_readback
from app.domains.billing.readback_contracts import BoundReadbackSubject, ReadbackApplyResult, ReadbackRecheck
from app.domains.billing.work_contracts import WorkClaim
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import financial, financial_readback, service
from app.domains.purchases.contracts import FinancialOperation, Purchase, PurchaseRefused
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxError, LbxScopeMismatch, LbxResponseInvalid
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State


@dataclass(frozen=True)
class FinancialRecoveryResult:
    original_resolved: bool = False
    terminal: bool = False
    child_get_allowed: bool = False
    readback: ReadbackApplyResult | None = None


async def _recover_one(
    client: LbxServerClient,
    purchase: Purchase,
    operation: FinancialOperation,
    customer: CustomerOpen,
    factory: SessionFactory,
    *,
    configuration: Settings,
    budget: PreflightBudget,
    work_claim: WorkClaim | None = None,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
) -> FinancialRecoveryResult:
    allowed, canonical = await delegate(financial_readback.recovery_route, factory, configuration, purchase, operation)
    if not allowed:
        return FinancialRecoveryResult()
    if operation.kind == Kind.AGREEMENT and canonical:
        # The child's common read set proves the same original agreement.
        return FinancialRecoveryResult(True, child_get_allowed=True)
    subject = None
    if operation.kind == Kind.SUBSCRIPTION:
        subject = await delegate(
            capture_readback,
            factory,
            configuration,
            purchase,
            deadline=utc_now() + timedelta(seconds=budget.remaining_seconds()),
        )
        purchase, customer = subject.purchase, subject.customer
        operation = next(op for op in purchase.operations if op.kind == Kind.SUBSCRIPTION)
    found = None
    try:
        found = await _find_financial(
            client,
            purchase,
            operation,
            customer,
            budget=budget,
            subject=subject,
            require_discovery=operation.kind == Kind.SUBSCRIPTION and operation.state != State.BOUND,
        )
        if found is None:
            await delegate(financial.financial_pending, factory, purchase, operation, work_claim=work_claim)
            return FinancialRecoveryResult()
        outcome = None
        if isinstance(subject, BoundReadbackSubject) and (
            found.finding.negative is not None or found.failure is not None
        ):
            outcome = await apply_bound_readback(
                client,
                configuration,
                factory=factory,
                finding=found.finding,
                budget=budget,
                delegate=delegate,
                work_claim=work_claim,
            )
            if found.finding.negative is not None and outcome != ReadbackApplyResult.APPLIED_NEGATIVE:
                raise PurchaseRefused("purchase_pending", 409)
        # Strict original terms cannot discard the already committed BOUND negative.
        found.require_original_terms(purchase, operation, customer)
        if isinstance(subject, BoundReadbackSubject) and found.finding.negative is None:
            await delegate(financial_readback.ensure_bound_enrollment, factory, configuration, subject)
        terminal = found.terminal
        if subject is not None and not isinstance(subject, BoundReadbackSubject):
            proof = found.original_proof(subject)
            try:
                outcome = await delegate(
                    financial_readback.bind_original_readback,
                    factory,
                    configuration,
                    subject,
                    proof,
                    prepared_subscription_observation(found.subscription, purchase, terminal=terminal),
                    work_claim=work_claim,
                )
            except ReadbackRecheck:
                # Foreign canonical creation is not this binder's own output.
                outcome = await apply_bound_readback(
                    client,
                    configuration,
                    factory=factory,
                    finding=found.finding,
                    budget=budget,
                    delegate=delegate,
                    work_claim=work_claim,
                )
            if proof.negative is not None and outcome != ReadbackApplyResult.APPLIED_NEGATIVE:
                raise PurchaseRefused("purchase_pending", 409)
        elif subject is None and operation.state != State.BOUND:
            await delegate(
                financial.bind_financial, factory, purchase, operation, found.provider_id, work_claim=work_claim
            )
        child_get = operation.kind == Kind.AGREEMENT and any(
            op.kind == Kind.SUBSCRIPTION
            and op.state in {State.POSSIBLE_SEND, State.UNKNOWN, State.MANUAL_REVIEW, State.BOUND}
            for op in purchase.operations
        )
        return FinancialRecoveryResult(True, terminal, not terminal or child_get, outcome)
    except PreflightDeadlineExceeded:
        await delegate(financial.financial_pending, factory, purchase, operation, work_claim=work_claim)
        raise
    except LbxScopeMismatch:
        if (
            work_claim is None
            and found is not None
            and (
                found.agreement.user_id,
                found.agreement.organization_id,
                found.agreement.agreement_number,
                found.agreement.is_offer,
            )
            != (
                int(customer.provider_id),
                purchase.accepted.seller_id,
                next(op.key for op in purchase.operations if op.kind == Kind.AGREEMENT),
                False,
            )
        ):
            operation = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
        await delegate(financial.financial_pending, factory, purchase, operation, conflict=True, work_claim=work_claim)
    except LbxError as error:
        facts = error.response_facts
        await delegate(
            financial.financial_pending,
            factory,
            purchase,
            operation,
            work_claim=work_claim,
            failure_facts={
                "code": error.code,
                "http_status": facts.http_status if facts else None,
                "lbx_code": facts.lbx_code if facts else None,
                "reason": facts.reason if facts else "unknown",
            },
        )
    return FinancialRecoveryResult()


async def recover_financial(
    sources: SourceResources,
    configuration: Settings,
    *,
    factory: SessionFactory,
    user_id: UUID,
    purchase_id: UUID,
    operation_id: UUID | None = None,
    work_claim: WorkClaim | None = None,
    budget: PreflightBudget | None = None,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
) -> Purchase:
    """Shared GET-only recovery; background callers cannot acquire send authority."""
    from app.composition.reconciliation import _budget
    from app.composition.purchases import _connection, _operation

    purchase = await delegate(service.inspect_purchase, factory, configuration, user_id, purchase_id)
    _connection(purchase, configuration)
    if not purchase.held or sources.billing is None:
        raise PurchaseRefused("purchase_scope_released", 409)
    await delegate(service.verify_original_consent, factory, purchase)
    async with _budget(sources.billing, budget) as active_budget:
        current = await delegate(service.customer_for_purchase, factory, configuration, purchase)
        point = await sources.require_lbx().get_user(user_id=int(current.provider_id), budget=active_budget)
        if point.outer_id is None:
            raise LbxResponseInvalid()
        if str(point.user_id) != current.provider_id or point.outer_id != current.outer_key:
            await delegate(record_customer_conflict, factory, current, work_claim, provider_id=str(point.user_id))
            raise LbxScopeMismatch()
        for kind in (Kind.AGREEMENT, Kind.SUBSCRIPTION):
            purchase = await delegate(service.read_purchase, factory, user_id, purchase_id)
            operation = _operation(purchase, kind)
            if operation_id is not None and operation.id != operation_id:
                continue
            if operation.state in {State.PENDING, State.PROVEN_NOT_SENT}:
                continue
            result = await _recover_one(
                sources.require_lbx(),
                purchase,
                operation,
                current,
                factory,
                configuration=configuration,
                budget=active_budget,
                work_claim=work_claim,
                delegate=delegate,
            )
            if not result.original_resolved or not result.child_get_allowed:
                break
        return await delegate(service.read_purchase, factory, user_id, purchase_id)
