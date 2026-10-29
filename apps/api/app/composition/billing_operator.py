"""Privileged entrypoints reuse the worker's proof, fenced apply and bind paths."""

from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.composition.purchase_observation import prepared_subscription_observation
from app.composition.purchases import _connection, _find_financial, _operation
from app.composition.reconciliation import reconcile_subscription
from app.composition.sources import SourceResources
from app.core.settings import Settings
from app.core.time import utc_now
from app.domains.billing.operator_contracts import OriginalOperationProof, ResolutionRequest
from app.domains.billing.operator_diagnostics import purchase_subscription
from app.domains.billing.operator_review import digest, prepare_resolution
from app.domains.billing.reconciliation_contracts import SubscriptionCandidateSubject
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases import financial, service
from app.domains.purchases.contracts import PurchaseRefused
from app.integrations.lbx.errors import LbxScopeMismatch
from app.integrations.lbx.financial import NewAgreement, NewSubscription
from app.integrations.lbx.reconciliation import read_subscription_proof
from app.models import ExternalCreateOperationKind as Kind


async def reconcile_purchase(
    sources: SourceResources, configuration: Settings, *, factory: SessionFactory, user_id: UUID, purchase_id: UUID
) -> UUID:
    subscription_id = await run_in_threadpool(purchase_subscription, factory, configuration, user_id, purchase_id)
    return await reconcile_subscription(
        sources.require_lbx(), sources.billing, configuration, factory=factory, subscription_id=subscription_id
    )


async def resolve_review(
    sources: SourceResources,
    configuration: Settings,
    *,
    factory: SessionFactory,
    request: ResolutionRequest,
    principal: str,
) -> dict:
    if sources.billing is None:
        raise PurchaseRefused("purchase_billing_not_configured", 503)
    resolution = await run_in_threadpool(
        prepare_resolution,
        factory,
        configuration,
        request,
        principal,
        io_timeout_seconds=sources.billing.policy.total_timeout_seconds,
    )
    if isinstance(resolution, dict):
        return resolution
    purchase = resolution.purchase
    _connection(purchase, configuration)
    if request.resolution == "restore-original":
        observation_id = await reconcile_subscription(
            sources.require_lbx(),
            sources.billing,
            configuration,
            factory=factory,
            subscription_id=UUID(resolution.before["subscription_id"]),
            resolution=resolution,
        )
        return {"review_case_id": str(request.case_id), "outcome": "resolved", "observation_id": str(observation_id)}
    operation = next(op for op in purchase.operations if op.id == request.operation_id)
    async with sources.billing.operation() as budget:
        started = utc_now()
        customer = await run_in_threadpool(service.customer_for_purchase, factory, configuration, purchase)
        point = await sources.require_lbx().get_user(user_id=int(customer.provider_id), budget=budget)
        if str(point.user_id) != customer.provider_id or point.outer_id != customer.outer_key:
            raise LbxScopeMismatch()
        if operation.kind == Kind.AGREEMENT:
            if operation.agreement_create_date is None:
                raise PurchaseRefused("purchase_history_unproven", 409)
            expected = NewAgreement(
                user_id=int(customer.provider_id),
                organization_id=purchase.accepted.seller_id,
                agreement_number=operation.key,
                create_date=operation.agreement_create_date,
            ).request_document()
        else:
            agreement = _operation(purchase, Kind.AGREEMENT)
            expected = NewSubscription(
                agreement_id=int(agreement.bound_id),
                tariff_id=purchase.accepted.selection.tariff_id,
                period_id=purchase.accepted.selection.period_id,
                tariff_service_id=purchase.accepted.selection.tariff_service_id,
                quantity=purchase.accepted.selection.quantity,
                outer_id=operation.key,
            ).request_document()
        if resolution.saved_request != expected:
            raise PurchaseRefused("purchase_history_unproven", 409)
        found = await _find_financial(
            sources.require_lbx(), purchase, operation, customer, budget=budget, require_discovery=True
        )
        if found is None:
            raise PurchaseRefused("billing_review_proof_incomplete", 409)
        provider_id, subscription = found
        proof = None
        if subscription is not None:
            subject = SubscriptionCandidateSubject(
                purchase,
                customer,
                str(subscription.agreement_id),
                _operation(purchase, Kind.AGREEMENT).key,
                str(provider_id),
            )
            proof = await read_subscription_proof(sources.require_lbx(), subject, configuration, budget=budget)
        budget.check()
        binding_proof = OriginalOperationProof(started, utc_now(), digest(expected), proof)
    await run_in_threadpool(
        financial.bind_financial,
        factory,
        purchase,
        operation,
        provider_id,
        observation=prepared_subscription_observation(subscription, purchase) if subscription else None,
        resolution=resolution,
        resolution_proof=binding_proof,
    )
    return {"review_case_id": str(request.case_id), "outcome": "resolved"}
