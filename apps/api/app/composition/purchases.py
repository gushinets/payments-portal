"""Bounded outer I/O for purchase preparation and GET-only financial recovery."""

from __future__ import annotations

from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.composition.purchase_financial import _find_financial
from app.composition.purchase_inventory import (
    MAX_RELEVANT_SUBSCRIPTIONS as MAX_RELEVANT_SUBSCRIPTIONS,
    _inventory as _inventory,
)
from app.domains.billing.inventory_readback import capture_inventory, apply_inventory_findings
from app.core.time import utc_now
from datetime import timedelta
from app.composition.billing import ensure_customer
from app.composition.catalog import catalog_preview
from app.composition.purchase_offer import live_original, require_configured_seller
from app.composition.purchase_recovery import _recover_one, recover_financial as recover_financial
from app.composition.sources import SourceResources
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.contracts import BillingAccountFailure, CustomerOpen
from app.domains.billing.customers import reserve_customer, recheck_widget_session
from app.domains.catalog.link_publication import StoredProductLink
from app.domains.catalog.product_link import CurrentOffer
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import (
    FinancialOperation,
    LegalEvidence,
    Purchase,
    PurchaseMeaning,
    PurchaseRefused,
    PurchaseInventoryIncomplete,
)
from app.domains.purchases import financial, service
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx._transport import customer_diagnostics
from app.integrations.lbx.current_offer import current_billing_date
from app.integrations.lbx.errors import LbxCreateNotSent, LbxError, LbxScopeMismatch
from app.integrations.lbx.financial import (
    NewAgreement,
    NewSubscription,
)
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State, PurchaseIntentState


async def review_purchase(
    sources: SourceResources, configuration: Settings, *, factory: SessionFactory, token: str, product_id: str
) -> tuple[StoredProductLink, CurrentOffer, tuple[LegalEvidence, ...]]:
    await run_in_threadpool(service.authenticate_user, factory, configuration, token)
    require_configured_seller(configuration)
    products = await catalog_preview(sources, configuration, session_factory=factory, product_id=product_id)
    product = products[0]
    if product.link is None or product.offer is None:
        raise PurchaseRefused("purchase_offer_unavailable", 409)
    documents = await run_in_threadpool(service.read_legal, factory, configuration, token)
    return product.link, product.offer, documents


async def confirm_purchase(
    sources: SourceResources,
    configuration: Settings,
    *,
    factory: SessionFactory,
    token: str,
    key: str,
    meaning: PurchaseMeaning,
) -> Purchase:
    prior = await run_in_threadpool(service.prior_request, factory, configuration, token, key, meaning)
    if prior is not None:
        return prior
    link, offer, documents = await review_purchase(
        sources, configuration, factory=factory, token=token, product_id=meaning.product_id
    )
    return await run_in_threadpool(
        service.pin_purchase, factory, configuration, token, key, meaning, link, offer, documents
    )


def _operation(purchase: Purchase, kind: Kind) -> FinancialOperation:
    candidates = [op for op in purchase.operations if op.kind == kind]
    if len(candidates) != 1:
        raise PurchaseRefused("purchase_history_unproven", 409)
    return candidates[0]


def _connection(purchase: Purchase, configuration: Settings) -> None:
    if configuration.lbx_configuration_error is not None:
        raise PurchaseRefused("purchase_billing_not_configured", 503)
    if purchase.accepted.provider_origin != configuration.lbx_provider_origin:
        raise PurchaseRefused("billing_connection_conflict", 409)


async def _prepare(
    sources: SourceResources,
    configuration: Settings,
    *,
    factory: SessionFactory,
    purchase: Purchase,
    customer: CustomerOpen,
    budget: PreflightBudget,
    token: str | None,
    recover_only: bool,
    require_payment_proof: bool = False,
) -> Purchase:
    client = sources.require_lbx()
    verified: set[Kind] = set()
    for kind in (Kind.AGREEMENT, Kind.SUBSCRIPTION):
        purchase = await run_in_threadpool(service.read_purchase, factory, purchase.user_id, purchase.id)
        operation = _operation(purchase, kind)
        with customer_diagnostics(str(operation.id)):
            if operation.state not in {State.PENDING, State.PROVEN_NOT_SENT}:
                try:
                    result = await _recover_one(
                        client,
                        purchase,
                        operation,
                        customer,
                        factory,
                        configuration=configuration,
                        budget=budget,
                    )
                except PurchaseRefused as error:
                    if error.code != "purchase_review_required":
                        raise
                    break
                if result.original_resolved:
                    verified.add(kind)
                if require_payment_proof and result.terminal:
                    raise PurchaseRefused("purchase_not_prepared", 409)
                if not result.original_resolved or not result.child_get_allowed:
                    break
                continue
            if recover_only or purchase.state == PurchaseIntentState.MANUAL_REVIEW:
                break
            if not await live_original(sources, configuration, purchase, factory, budget=budget):
                break
            try:
                # A bound agreement does not prove current subscription admission,
                # including when a proven-not-sent subscription is explicitly resumed.
                subjects = await run_in_threadpool(
                    capture_inventory,
                    factory,
                    configuration,
                    customer.customer_id,
                    deadline=utc_now() + timedelta(seconds=budget.remaining_seconds()),
                )
                inventory_read = await _inventory(client, purchase, customer, factory, budget=budget, subjects=subjects)
                await run_in_threadpool(apply_inventory_findings, factory, configuration, inventory_read.findings)
                inventory_read.require_complete()
            except PurchaseInventoryIncomplete:
                await run_in_threadpool(financial.financial_pending, factory, purchase, operation)
                raise
            except LbxScopeMismatch:
                # This command is still unsent. Inventory blocks admission but
                # must not manufacture an uncertain financial effect/review.
                raise PurchaseRefused("purchase_existing_subscription_review", 409) from None
            try:
                found = await _find_financial(client, purchase, operation, customer, budget=budget)
            except (LbxScopeMismatch, PurchaseRefused) as error:
                await run_in_threadpool(financial.financial_pending, factory, purchase, operation, conflict=True)
                if isinstance(error, PurchaseRefused):
                    raise
                break
            if found is not None:
                await run_in_threadpool(financial.financial_pending, factory, purchase, operation, conflict=True)
                break
            # Authenticate before the permanent possible-send claim; the shared POST
            # transport cannot reauthenticate/retry a financial command.
            await client.prepare_customer_create(budget=budget)
            if kind == Kind.AGREEMENT:
                command = NewAgreement(
                    user_id=int(customer.provider_id),
                    organization_id=purchase.accepted.seller_id,
                    agreement_number=operation.key,
                    create_date=operation.agreement_create_date or current_billing_date(),
                )
            else:
                command = NewSubscription(
                    agreement_id=int(_operation(purchase, Kind.AGREEMENT).bound_id),
                    tariff_id=purchase.accepted.selection.tariff_id,
                    period_id=purchase.accepted.selection.period_id,
                    tariff_service_id=purchase.accepted.selection.tariff_service_id,
                    quantity=purchase.accepted.selection.quantity,
                    outer_id=operation.key,
                )
            budget.check()
            operation = await run_in_threadpool(
                financial.claim_financial,
                factory,
                purchase,
                operation,
                command.request_document(),
                configuration=configuration,
                token=token,
            )
            if not operation.may_send:
                break
            try:
                if kind == Kind.AGREEMENT:
                    provider_id = await client.create_agreement(command, budget=budget)
                else:
                    provider_id = await client.create_subscription(command, budget=budget)
                await run_in_threadpool(financial.record_receipt, factory, purchase, operation, provider_id)
            except LbxCreateNotSent:
                await run_in_threadpool(financial.proven_not_sent, factory, purchase, operation)
                break  # Resume only on another explicit advance; never retry this attempt.
            except AppError as error:
                # HTTP 500, malformed replies and timeouts remain GET-only recovery.
                facts = error.response_facts if isinstance(error, LbxError) else None
                await run_in_threadpool(
                    financial.financial_pending,
                    factory,
                    purchase,
                    operation,
                    failure_facts={
                        "code": error.code,
                        "http_status": facts.http_status if facts else None,
                        "lbx_code": facts.lbx_code if facts else None,
                        "reason": facts.reason if facts else "unknown",
                    },
                )
            purchase = await run_in_threadpool(service.read_purchase, factory, purchase.user_id, purchase.id)
            operation = _operation(purchase, kind)
            result = await _recover_one(
                client, purchase, operation, customer, factory, configuration=configuration, budget=budget
            )
            if not result.original_resolved or not result.child_get_allowed:
                break
    if require_payment_proof and verified != {Kind.AGREEMENT, Kind.SUBSCRIPTION}:
        raise PurchaseRefused("purchase_not_prepared", 409)
    return await run_in_threadpool(service.read_purchase, factory, purchase.user_id, purchase.id)


async def advance_purchase(
    sources: SourceResources, configuration: Settings, *, factory: SessionFactory, token: str, purchase_id: UUID
) -> Purchase:
    user_id = await run_in_threadpool(service.authenticate_user, factory, configuration, token)
    purchase = await run_in_threadpool(service.read_purchase, factory, user_id, purchase_id)
    _connection(purchase, configuration)
    if not purchase.held:
        return purchase
    await run_in_threadpool(service.verify_original_consent, factory, purchase)
    if sources.billing is None:
        raise PurchaseRefused("purchase_billing_not_configured", 503)
    customer_ready = False
    try:
        async with sources.billing.operation() as budget:
            current = await run_in_threadpool(reserve_customer, factory, configuration, token)
            if current.customer_id != purchase.customer_id:
                raise PurchaseRefused("billing_identity_conflict", 409)
            current = await ensure_customer(
                sources.require_lbx(), configuration, factory=factory, token=token, current=current, budget=budget
            )
            customer_ready = True
            result = await _prepare(
                sources,
                configuration,
                factory=factory,
                purchase=purchase,
                customer=current,
                budget=budget,
                token=token,
                recover_only=False,
            )
            await run_in_threadpool(recheck_widget_session, factory, configuration, token, current)
            return result
    except PreflightDeadlineExceeded:
        # The admission context distinguishes its own expiry from caller cancellation.
        # Preserve the phase-specific errors after customer proof completes.
        if customer_ready:
            raise
        raise BillingAccountFailure("billing_customer_pending", 409) from None


async def verify_payment_purchase(
    sources: SourceResources,
    configuration: Settings,
    *,
    factory: SessionFactory,
    token: str,
    purchase_id: UUID,
    customer: CustomerOpen,
    budget: PreflightBudget,
) -> Purchase:
    user_id = await run_in_threadpool(service.authenticate_user, factory, configuration, token)
    purchase = await run_in_threadpool(service.read_purchase, factory, user_id, purchase_id)
    _connection(purchase, configuration)
    if (
        purchase.customer_id != customer.customer_id
        or not purchase.held
        or purchase.state != PurchaseIntentState.LINKED
    ):
        raise PurchaseRefused("purchase_not_prepared", 409)
    await run_in_threadpool(service.verify_original_consent, factory, purchase)
    result = await _prepare(
        sources,
        configuration,
        factory=factory,
        purchase=purchase,
        customer=customer,
        budget=budget,
        token=token,
        recover_only=True,
        require_payment_proof=True,
    )
    if result.state != PurchaseIntentState.LINKED or any(op.state != State.BOUND for op in result.operations):
        raise PurchaseRefused("purchase_not_prepared", 409)
    return result
