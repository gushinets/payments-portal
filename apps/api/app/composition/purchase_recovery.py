"""One GET-only original-operation proof and transactional binding path."""

from collections.abc import Awaitable, Callable
from dataclasses import replace
from typing import Any
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.composition.purchase_observation import prepared_subscription_observation
from app.composition.sources import SourceResources
from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.work_contracts import WorkClaim
from app.domains.billing.customer_conflicts import record_customer_conflict
from app.domains.billing.operator_contracts import OriginalOperationProof, ReviewResolution
from app.domains.billing.operator_review import digest
from app.domains.billing.reconciliation_contracts import CommercialProof, IdentityProof, SubscriptionCandidateSubject
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import FinancialOperation, FinancialRequestDocument, Purchase, PurchaseRefused
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.errors import LbxError, LbxScopeMismatch, LbxResponseInvalid
from app.integrations.lbx.financial import (
    Agreement,
    NewAgreement,
    NewSubscription,
    Subscription,
    agreement_is_closed,
    prove_agreement,
    prove_effective_terms,
)
from app.integrations.lbx.reconciliation import normalize_subscription, timely_point
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State


def original_command(
    purchase: Purchase, operation: FinancialOperation, customer: CustomerOpen
) -> FinancialRequestDocument:
    if operation.kind == Kind.AGREEMENT:
        if operation.agreement_create_date is None:
            raise PurchaseRefused("purchase_history_unproven", 409)
        return NewAgreement(
            user_id=int(customer.provider_id),
            organization_id=purchase.accepted.seller_id,
            agreement_number=operation.key,
            create_date=operation.agreement_create_date,
        ).request_document()
    agreement = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    if agreement.state != State.BOUND or agreement.bound_id is None:
        raise PurchaseRefused("purchase_pending", 409)
    selection = purchase.accepted.selection
    return NewSubscription(
        agreement_id=int(agreement.bound_id),
        tariff_id=selection.tariff_id,
        period_id=selection.period_id,
        tariff_service_id=selection.tariff_service_id,
        quantity=selection.quantity,
        outer_id=operation.key,
    ).request_document()


async def find_financial(
    client: LbxServerClient,
    purchase: Purchase,
    operation: FinancialOperation,
    customer: CustomerOpen,
    *,
    budget: PreflightBudget,
    require_discovery: bool = False,
) -> tuple[int, Agreement, Subscription | None] | None:
    """Discovery selects candidates; neither a receipt nor a listing binds them."""
    if operation.bound_id is not None:
        return None
    saved = operation.candidate_id
    if operation.kind == Kind.AGREEMENT:
        ids = (
            (int(saved),)
            if saved and not require_discovery
            else await timely_point(
                lambda: client.discover_agreements(
                    user_id=int(customer.provider_id), number=operation.key, budget=budget
                ),
                budget,
            )
        )
        if len(ids) > 1 or (require_discovery and saved and ids != (int(saved),)):
            raise LbxScopeMismatch()
        if not ids:
            return None
        agreement = await timely_point(lambda: client.get_agreement(agreement_id=ids[0], budget=budget), budget)
        prove_agreement(
            agreement, user_id=int(customer.provider_id), seller_id=purchase.accepted.seller_id, number=operation.key
        )
        if (
            operation.agreement_create_date is not None
            and agreement.create_date != operation.agreement_create_date.isoformat()
        ):
            raise LbxResponseInvalid()
        agreement_is_closed(agreement)
        return ids[0], agreement, None
    agreement_op = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
    if agreement_op.bound_id is None:
        raise PurchaseRefused("purchase_pending", 409)
    agreement_id = int(agreement_op.bound_id)
    agreement = await timely_point(lambda: client.get_agreement(agreement_id=agreement_id, budget=budget), budget)
    prove_agreement(
        agreement, user_id=int(customer.provider_id), seller_id=purchase.accepted.seller_id, number=agreement_op.key
    )
    if agreement_is_closed(agreement) and operation.state in {State.PENDING, State.PROVEN_NOT_SENT}:
        raise PurchaseRefused("purchase_not_prepared", 409)
    rows = await timely_point(
        lambda: client.discover_subscriptions(
            user_id=int(customer.provider_id), agreement_id=agreement_id, budget=budget
        ),
        budget,
    )
    ids = tuple(row.subscription_id for row in rows)
    if saved:
        if any(value != int(saved) for value in ids) or (require_discovery and ids != (int(saved),)):
            raise LbxScopeMismatch()
        ids = (int(saved),)
    if len(ids) > 1:
        raise LbxScopeMismatch()
    if not ids:
        return None
    point = await timely_point(lambda: client.get_subscription(subscription_id=ids[0], budget=budget), budget)
    if operation.state in {State.PENDING, State.PROVEN_NOT_SENT}:
        prove_effective_terms(
            point, agreement_id=agreement_id, selection=purchase.accepted.selection, offer=purchase.accepted.offer
        )
    return ids[0], agreement, point


async def recover_one(
    sources: SourceResources,
    configuration: Settings,
    purchase: Purchase,
    operation: FinancialOperation,
    customer: CustomerOpen,
    factory: SessionFactory,
    *,
    budget: PreflightBudget,
    work_claim: WorkClaim | None = None,
    delegate: Callable[..., Awaitable[Any]] = run_in_threadpool,
    resolution: ReviewResolution | None = None,
) -> bool:
    """Prove the original once; operator authorization/audit share its binder."""
    started = utc_now()
    command = original_command(purchase, operation, customer)
    pending = await delegate(financial.original_request, factory, purchase, operation, command, resolution=resolution)
    if not pending:
        return await _already_bound(sources, configuration, factory, purchase, operation, budget, delegate)
    client = sources.require_lbx()
    try:
        try:
            user = await timely_point(lambda: client.get_user(user_id=int(customer.provider_id), budget=budget), budget)
        except LbxScopeMismatch:
            await delegate(record_customer_conflict, factory, customer, work_claim)
            raise PurchaseRefused("billing_identity_conflict", 409) from None
        if user.outer_id is None:
            raise LbxResponseInvalid()
        if user.outer_id != customer.outer_key:
            await delegate(record_customer_conflict, factory, customer, work_claim, provider_id=customer.provider_id)
            raise PurchaseRefused("billing_identity_conflict", 409)
        found = await find_financial(
            client, purchase, operation, customer, budget=budget, require_discovery=resolution is not None
        )
        if found is None:
            if resolution is not None:
                raise PurchaseRefused("billing_review_proof_incomplete", 409)
            await delegate(financial.financial_pending, factory, purchase, operation, work_claim=work_claim)
            return False
        provider_id, agreement, point = found
        proof = None
        if point is not None:
            agreement_op = next(op for op in purchase.operations if op.kind == Kind.AGREEMENT)
            tariff = await timely_point(
                lambda: client.get_tariff(tariff_id=purchase.accepted.selection.tariff_id, budget=budget), budget
            )
            subject = SubscriptionCandidateSubject(
                purchase, customer, agreement_op.bound_id, agreement_op.key, str(provider_id)
            )
            proof = normalize_subscription(
                subject, configuration, user=user, agreement=agreement, tariff=tariff, subscription=point
            )
            if proof.identity == IdentityProof.CONFLICT or proof.commercial == CommercialProof.MISMATCH:
                raise LbxScopeMismatch()
            if (
                proof.identity != IdentityProof.MATCH
                or proof.commercial != CommercialProof.MATCH
                or proof.lifecycle is None
            ):
                raise LbxResponseInvalid()
            proof = replace(
                proof,
                read_started_at=started,
                read_finished_at=utc_now(),
                reads=("customer", "agreement", "subscription", "tariff_policy"),
            )
        budget.check()
        original = OriginalOperationProof(
            started,
            utc_now(),
            digest(command),
            customer,
            proof,
            agreement.close_date if agreement_is_closed(agreement) else None,
        )
        if resolution is not None:
            from app.composition.purchase_inventory import collect_inventory
            from app.domains.purchases.inventory_contracts import InventoryCandidateProof

            inventory = await collect_inventory(
                client,
                sources.billing,
                configuration,
                factory=factory,
                customer=customer,
                budget=budget,
                expected=purchase,
                reuse=InventoryCandidateProof(purchase, str(provider_id) if proof is not None else None, proof),
                delegate=delegate,
            )
            inventory.require_clear(purchase, original=True)
            resolution = replace(resolution, inventory=inventory)
        bound = await delegate(
            financial.bind_financial,
            factory,
            purchase,
            operation,
            provider_id,
            observation=prepared_subscription_observation(point, purchase) if point is not None else None,
            proof=original,
            work_claim=work_claim,
            resolution=resolution,
        )
        return (
            True
            if bound
            else await _already_bound(sources, configuration, factory, purchase, operation, budget, delegate)
        )
    except LbxError as error:
        if resolution is not None:
            raise
        facts = error.response_facts
        await delegate(
            financial.financial_pending,
            factory,
            purchase,
            operation,
            work_claim=work_claim,
            conflict=isinstance(error, LbxScopeMismatch),
            failure_facts={
                "code": error.code,
                "http_status": facts.http_status if facts else None,
                "lbx_code": facts.lbx_code if facts else None,
                "reason": facts.reason if facts else "unknown",
            },
        )
        return False


async def _already_bound(
    sources: SourceResources,
    configuration: Settings,
    factory: SessionFactory,
    purchase: Purchase,
    operation: FinancialOperation,
    budget: PreflightBudget,
    delegate: Callable[..., Awaitable[Any]],
) -> bool:
    from app.composition.reconciliation import reconcile_bound_purchase

    current = await delegate(service.read_purchase, factory, purchase.user_id, purchase.id)
    if next(op for op in current.operations if op.id == operation.id).bound_id is None:
        raise PurchaseRefused("purchase_pending", 409)
    if operation.kind == Kind.SUBSCRIPTION:
        await reconcile_bound_purchase(sources, configuration, factory, current, budget)
    return True


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
    """GET-only; completed recovery jobs do not re-observe bound subscriptions."""
    from app.composition.reconciliation import _budget
    from app.composition.purchases import _connection

    purchase = await delegate(service.inspect_purchase, factory, configuration, user_id, purchase_id)
    _connection(purchase, configuration)
    if not purchase.held or sources.billing is None:
        raise PurchaseRefused("purchase_scope_released", 409)
    await delegate(service.verify_original_consent, factory, purchase)
    async with _budget(sources.billing, budget) as active_budget:
        for kind in (Kind.AGREEMENT, Kind.SUBSCRIPTION):
            purchase = await delegate(service.read_purchase, factory, user_id, purchase_id)
            operation = next(op for op in purchase.operations if op.kind == kind)
            if operation_id is not None and operation.id != operation_id:
                continue
            if operation.bound_id is not None or operation.state in {State.PENDING, State.PROVEN_NOT_SENT}:
                continue
            current = await delegate(service.customer_for_purchase, factory, configuration, purchase)
            if not await recover_one(
                sources,
                configuration,
                purchase,
                operation,
                current,
                factory,
                budget=active_budget,
                work_claim=work_claim,
                delegate=delegate,
            ):
                break
        return await delegate(service.read_purchase, factory, user_id, purchase_id)
