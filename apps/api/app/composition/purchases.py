"""Bounded outer I/O for purchase preparation and GET-only financial recovery."""

from __future__ import annotations

from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.composition.billing import ensure_customer
from app.composition.catalog import catalog_preview
from app.composition.purchase_offer import live_original, require_configured_seller
from app.composition.purchase_terms import current_technical_terms
from app.composition.purchase_recovery import (
    recover_financial as recover_financial,
    find_financial as _find_financial,
    recover_one as _recover_one,
)
from app.composition.sources import SourceResources
from app.composition.reconciliation import reconcile_bound_purchase
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.contracts import BillingAccountFailure, BillingRefused, CustomerOpen
from app.domains.billing.reconciliation_contracts import (
    CommercialProof,
    IdentityProof,
    ReconciliationResult,
)
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
from app.domains.purchases.technical_terms import AcceptedTechnicalTerms
from app.domains.purchases.inventory import block_admission
from app.composition.purchase_inventory import collect_inventory
from app.infrastructure.preflight import PreflightBudget, PreflightDeadlineExceeded
from app.integrations.lbx._transport import customer_diagnostics
from app.integrations.lbx.current_offer import current_billing_date
from app.integrations.lbx.errors import LbxCreateNotSent, LbxError, LbxScopeMismatch
from app.integrations.lbx.financial import (
    NewAgreement,
    NewSubscription,
)
from app.models import (
    ExternalCreateOperationKind as Kind,
    ExternalCreateOperationState as State,
    PurchaseIntentState,
    ExternalSubscriptionLifecycleStatus as Lifecycle,
)


async def review_purchase(
    sources: SourceResources, configuration: Settings, *, factory: SessionFactory, token: str, product_id: str
) -> tuple[StoredProductLink, CurrentOffer, tuple[LegalEvidence, ...], AcceptedTechnicalTerms | None]:
    await run_in_threadpool(service.authenticate_user, factory, configuration, token)
    require_configured_seller(configuration)
    products = await catalog_preview(sources, configuration, session_factory=factory, product_id=product_id)
    product = products[0]
    if product.link is None or product.offer is None or product.manifest is None:
        raise PurchaseRefused("purchase_offer_unavailable", 409)
    documents = await run_in_threadpool(service.read_legal, factory, configuration, token)
    terms = await run_in_threadpool(
        current_technical_terms, configuration, product.manifest, product.link, product.offer
    )
    return product.link, product.offer, documents, terms


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
    link, offer, documents, terms = await review_purchase(
        sources, configuration, factory=factory, token=token, product_id=meaning.product_id
    )
    return await run_in_threadpool(
        service.pin_purchase, factory, configuration, token, key, meaning, link, offer, documents, terms
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
    token: str,
) -> Purchase:
    client = sources.require_lbx()
    for kind in (Kind.AGREEMENT, Kind.SUBSCRIPTION):
        purchase = await run_in_threadpool(service.read_purchase, factory, purchase.user_id, purchase.id)
        # A concurrent first binder has already completed preparation. Do not
        # replay known-subscription reads through the financial binder.
        if _operation(purchase, Kind.SUBSCRIPTION).bound_id is not None:
            await reconcile_bound_purchase(sources, configuration, factory, purchase, budget)
            return await run_in_threadpool(service.read_purchase, factory, purchase.user_id, purchase.id)
        operation = _operation(purchase, kind)
        if operation.bound_id is not None:
            if operation.state != State.BOUND:
                break
            continue
        if operation.state == State.MANUAL_REVIEW and operation.deadline is None:
            break  # A pre-send review has no original possible-send operation to recover.
        with customer_diagnostics(str(operation.id)):
            if operation.state not in {State.PENDING, State.PROVEN_NOT_SENT}:
                try:
                    recovered = await _recover_one(
                        sources, configuration, purchase, operation, customer, factory, budget=budget
                    )
                except PurchaseRefused as error:
                    if error.code != "purchase_review_required":
                        raise
                    break  # Preserve advance's review result; only the operator may resolve it.
                if not recovered:
                    break
                continue
            if (
                purchase.state == PurchaseIntentState.MANUAL_REVIEW
                or _operation(purchase, Kind.AGREEMENT).agreement_closed
            ):
                break
            if not await live_original(sources, configuration, purchase, factory, budget=budget):
                break
            # Check all local/source inventory evidence before entering the
            # original financial candidate lookup. Failed collection has no
            # complete result whose admission fences can be invalidated.
            inventory = await collect_inventory(
                client,
                sources.billing,
                configuration,
                factory=factory,
                customer=customer,
                expected=purchase,
                budget=budget,
            )
            try:
                inventory.require_clear(purchase)
            except PurchaseRefused:
                await run_in_threadpool(block_admission, factory, inventory, purchase)
                raise
            try:
                found = await _find_financial(client, purchase, operation, customer, budget=budget)
            except PurchaseInventoryIncomplete:
                await run_in_threadpool(financial.financial_pending, factory, purchase, operation)
                raise
            except (LbxScopeMismatch, PurchaseRefused) as error:
                if isinstance(error, PurchaseRefused) and error.code == "purchase_not_prepared":
                    break  # A recovered closed agreement never authorizes a new subscription.
                if isinstance(error, PurchaseRefused) and error.code == "purchase_existing_subscription_review":
                    raise
                await run_in_threadpool(block_admission, factory, inventory, purchase)
                if isinstance(error, PurchaseRefused):
                    raise
                raise PurchaseInventoryIncomplete() from None
            if found is not None:
                await run_in_threadpool(block_admission, factory, inventory, purchase)
                raise PurchaseInventoryIncomplete()
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
                inventory=inventory,
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
            if not await _recover_one(sources, configuration, purchase, operation, customer, factory, budget=budget):
                break
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
    bound = _operation(purchase, Kind.SUBSCRIPTION).bound_id is not None
    customer_ready = False
    try:
        # Source calls own the I/O deadline; a short first-bind transaction or
        # raced known-subscription apply must finish outside that timeout.
        async with sources.billing.operation(bound_scope=False) as budget:
            current = await run_in_threadpool(reserve_customer, factory, configuration, token)
            if current.customer_id != purchase.customer_id:
                raise PurchaseRefused("billing_identity_conflict", 409)
            if bound:
                customer_ready = True
                verification = await reconcile_bound_purchase(sources, configuration, factory, purchase, budget)
                current = verification.subject.customer
                result = await run_in_threadpool(service.read_purchase, factory, user_id, purchase.id)
                if result.state == PurchaseIntentState.MANUAL_REVIEW:
                    raise PurchaseRefused("purchase_review_required", 409)
            else:
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
                )
            budget.check()
            await run_in_threadpool(recheck_widget_session, factory, configuration, token, current)
            return result
    except BillingRefused as error:
        if bound and error.code == "billing_busy":
            raise PurchaseRefused("purchase_pending", 409) from None
        raise
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
) -> ReconciliationResult:
    user_id = await run_in_threadpool(service.authenticate_user, factory, configuration, token)
    purchase = await run_in_threadpool(service.read_purchase, factory, user_id, purchase_id)
    _connection(purchase, configuration)
    if (
        purchase.customer_id != customer.customer_id
        or not purchase.held
        or purchase.state != PurchaseIntentState.LINKED
    ):
        raise PurchaseRefused("purchase_not_prepared", 409)
    result = await reconcile_bound_purchase(sources, configuration, factory, purchase, budget)
    proof = result.proof
    if (
        proof.identity != IdentityProof.MATCH
        or proof.commercial != CommercialProof.MATCH
        # A retained block can be authoritative despite an unknown agreement
        # closure; that negative alone cannot prove this agreement payable.
        or "agreement_calendar_incomplete" in proof.reasons
        or proof.lifecycle not in {Lifecycle.ACTIVE, Lifecycle.INACTIVE}
        or any(op.state != State.BOUND for op in result.subject.purchase.operations)
    ):
        raise PurchaseRefused("purchase_not_prepared", 409)
    return result
