"""Bounded outer I/O for purchase preparation and GET-only financial recovery."""

from __future__ import annotations

from uuid import UUID

from starlette.concurrency import run_in_threadpool

from app.composition.billing import ensure_customer, recover_customer
from app.composition.catalog import catalog_preview
from app.composition.sources import SourceResources
from app.core.errors import AppError
from app.core.settings import Settings
from app.domains.billing.contracts import CustomerOpen
from app.domains.billing.customers import reserve_customer, recheck_widget_session
from app.domains.catalog.commercial_offer import canonical_decimal
from app.domains.catalog.link_publication import StoredProductLink
from app.domains.catalog.product_link import CurrentOffer, current_offer_fingerprint
from app.domains.catalog.preview import require_enabled_product
from app.domains.catalog.publication import SessionFactory
from app.domains.purchases.contracts import (
    FinancialOperation,
    LegalEvidence,
    Purchase,
    PurchaseMeaning,
    PurchaseRefused,
    PurchaseInventoryIncomplete,
)
from app.domains.purchases.contracts import EffectiveServiceEvidence, PreparedSubscriptionObservation
from app.domains.purchases import financial, service
from app.infrastructure.preflight import PreflightBudget
from app.integrations.lbx._transport import customer_diagnostics
from app.integrations.lbx.client import LbxServerClient
from app.integrations.lbx.current_offer import current_billing_date, read_current_offer
from app.integrations.lbx.errors import LbxCreateNotSent, LbxError, LbxScopeMismatch
from app.integrations.lbx.financial import (
    NewAgreement,
    NewSubscription,
    Subscription,
    prove_agreement,
    prove_subscription,
)
from app.models import ExternalCreateOperationKind as Kind, ExternalCreateOperationState as State, PurchaseIntentState


MAX_RELEVANT_SUBSCRIPTIONS = 20


async def review_purchase(
    sources: SourceResources, configuration: Settings, *, factory: SessionFactory, token: str, product_id: str
) -> tuple[StoredProductLink, CurrentOffer, tuple[LegalEvidence, ...]]:
    await run_in_threadpool(service.authenticate_user, factory, configuration, token)
    _configured_seller(configuration)
    products = await catalog_preview(sources, configuration, session_factory=factory, product_id=product_id)
    product = products[0]
    if product.link is None or product.offer is None:
        raise PurchaseRefused("purchase_offer_unavailable", 409)
    documents = await run_in_threadpool(service.read_legal, factory, configuration, token)
    return product.link, product.offer, documents


def _configured_seller(configuration: Settings) -> None:
    if configuration.lbx_purchase_configuration_error is not None:
        raise PurchaseRefused("purchase_billing_not_configured", 503)


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


async def _live_original(
    sources: SourceResources,
    configuration: Settings,
    purchase: Purchase,
    factory: SessionFactory,
    *,
    budget: PreflightBudget,
) -> bool:
    # One total deadline spans customer ensure, original-offer checks and financial I/O.
    _configured_seller(configuration)
    if purchase.accepted.seller_id != int(configuration.lbx_seller_organization_id):
        await run_in_threadpool(financial.changed_unsent_terms, factory, purchase)
        return False
    manifest = await sources.require_kernel().fetch_manifest(budget=budget)
    require_enabled_product(manifest, purchase.accepted.selection.product_id)
    offer = await read_current_offer(
        sources.require_lbx(), selection=purchase.accepted.selection, configuration=configuration, budget=budget
    )
    # Recompute from immutable historical fields under the current comparison
    # contract. Older stored digests included future scheduling metadata.
    if offer.fingerprint != current_offer_fingerprint(
        purchase.account_id, purchase.accepted.selection, purchase.accepted.offer
    ):
        await run_in_threadpool(financial.changed_unsent_terms, factory, purchase)
        return False
    return True


async def _inventory(
    client: LbxServerClient,
    purchase: Purchase,
    customer: CustomerOpen,
    factory: SessionFactory,
    *,
    budget: PreflightBudget,
) -> None:
    rows = await client.discover_subscriptions(user_id=int(customer.provider_id), budget=budget)
    relevant = [row for row in rows if row.tariff_id == purchase.accepted.selection.tariff_id]
    if len(relevant) > MAX_RELEVANT_SUBSCRIPTIONS:
        raise PurchaseInventoryIncomplete()
    own = _operation(purchase, Kind.SUBSCRIPTION).bound_id
    for candidate in relevant:
        point = await client.get_subscription(subscription_id=candidate.subscription_id, budget=budget)
        agreement = await client.get_agreement(agreement_id=point.agreement_id, budget=budget)
        if agreement.user_id != int(customer.provider_id):
            raise LbxScopeMismatch()
        if point.state is None:
            raise PurchaseInventoryIncomplete()
        if point.state != 3 and str(point.subscription_id) != own:
            other = await run_in_threadpool(
                service.other_inventory_purchase, factory, purchase, point.subscription_id, point.agreement_id
            )
            if other is not None:
                prove_agreement(
                    agreement,
                    user_id=int(customer.provider_id),
                    seller_id=other.accepted.seller_id,
                    number=_operation(other, Kind.AGREEMENT).key,
                )
                prove_subscription(
                    point,
                    agreement_id=point.agreement_id,
                    selection=other.accepted.selection,
                    offer=other.accepted.offer,
                )
                continue
            raise PurchaseRefused("purchase_existing_subscription_review", 409)


async def _find_financial(
    client: LbxServerClient,
    purchase: Purchase,
    operation: FinancialOperation,
    customer: CustomerOpen,
    *,
    budget: PreflightBudget,
) -> tuple[int, Subscription | None] | None:
    user_id = int(customer.provider_id)
    agreement_op = _operation(purchase, Kind.AGREEMENT)
    if operation.kind == Kind.AGREEMENT:
        saved = operation.bound_id or operation.candidate_id
        ids = (
            (int(saved),)
            if saved
            else await client.discover_agreements(user_id=user_id, number=operation.key, budget=budget)
        )
        if len(ids) > 1:
            raise LbxScopeMismatch()
        if not ids:
            return None
        point = await client.get_agreement(agreement_id=ids[0], budget=budget)
        prove_agreement(point, user_id=user_id, seller_id=purchase.accepted.seller_id, number=operation.key)
        return point.agreement_id, None
    if agreement_op.bound_id is None:
        raise PurchaseRefused("purchase_pending", 409)
    agreement_id = int(agreement_op.bound_id)
    agreement = await client.get_agreement(agreement_id=agreement_id, budget=budget)
    prove_agreement(agreement, user_id=user_id, seller_id=purchase.accepted.seller_id, number=agreement_op.key)
    rows = await client.discover_subscriptions(user_id=user_id, agreement_id=agreement_id, budget=budget)
    ids = tuple(row.subscription_id for row in rows)
    saved = operation.bound_id or operation.candidate_id
    if saved:
        # A known ID remains authoritative when the non-unique outer hint changes.
        if any(value != int(saved) for value in ids):
            raise LbxScopeMismatch()
        ids = (int(saved),)
    if len(ids) > 1:
        raise LbxScopeMismatch()
    if not ids:
        return None
    point = await client.get_subscription(subscription_id=ids[0], budget=budget)
    prove_subscription(
        point, agreement_id=agreement_id, selection=purchase.accepted.selection, offer=purchase.accepted.offer
    )
    return point.subscription_id, point


def _observation(point: Subscription, purchase: Purchase) -> PreparedSubscriptionObservation:
    # Deliberately excludes balance, provider text and PII. Dates remain provider calendar evidence.
    return PreparedSubscriptionObservation(
        subscription_id=str(point.subscription_id),
        agreement_id=str(point.agreement_id),
        state=point.state,
        current_blocking=point.current_blocking,
        accepted_fingerprint=purchase.accepted.offer.fingerprint,
        period_id=point.period_id,
        period_type=point.period_type,
        period_length=point.period_length,
        currency=purchase.accepted.offer.money.currency,
        effective_recurring_amount=canonical_decimal(point.total_price),
        services=tuple(
            EffectiveServiceEvidence(
                service.tariff_service_id, canonical_decimal(service.multiplicator), canonical_decimal(service.price)
            )
            for service in point.services
        ),
        calendar={
            field: getattr(point, field)
            for field in (
                "subscription_start_date",
                "subscription_end_date",
                "subscription_instance_start_date",
                "subscription_instance_end_date",
                "last_tariffication_period_start",
                "last_tariffication_period_end",
            )
        },
    )


async def _recover_one(
    client: LbxServerClient,
    purchase: Purchase,
    operation: FinancialOperation,
    customer: CustomerOpen,
    factory: SessionFactory,
    *,
    budget: PreflightBudget,
) -> bool:
    try:
        found = await _find_financial(client, purchase, operation, customer, budget=budget)
    except LbxScopeMismatch:
        await run_in_threadpool(financial.financial_pending, factory, purchase, operation, conflict=True)
        return False
    except LbxError as error:
        facts = error.response_facts
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
        return False
    if found is None:
        if operation.state not in {State.PENDING, State.PROVEN_NOT_SENT}:
            await run_in_threadpool(financial.financial_pending, factory, purchase, operation)
        return False
    # No absent/unsent financial operation is adopted from a coincidental object.
    if operation.state in {State.PENDING, State.PROVEN_NOT_SENT}:
        await run_in_threadpool(financial.financial_pending, factory, purchase, operation, conflict=True)
        return False
    provider_id, point = found
    await run_in_threadpool(
        financial.bind_financial,
        factory,
        purchase,
        operation,
        provider_id,
        observation=_observation(point, purchase) if point else None,
    )
    return True


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
                if not await _recover_one(client, purchase, operation, customer, factory, budget=budget):
                    break
                verified.add(kind)
                continue
            if recover_only or purchase.state == PurchaseIntentState.MANUAL_REVIEW:
                break
            if not await _live_original(sources, configuration, purchase, factory, budget=budget):
                break
            try:
                if kind == Kind.AGREEMENT:
                    await _inventory(client, purchase, customer, factory, budget=budget)
                found = await _find_financial(client, purchase, operation, customer, budget=budget)
            except PurchaseInventoryIncomplete:
                await run_in_threadpool(financial.financial_pending, factory, purchase, operation)
                raise
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
            if not await _recover_one(client, purchase, operation, customer, factory, budget=budget):
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
    async with sources.billing.operation() as budget:
        current = await run_in_threadpool(reserve_customer, factory, configuration, token)
        if current.customer_id != purchase.customer_id:
            raise PurchaseRefused("billing_identity_conflict", 409)
        current = await ensure_customer(
            sources.require_lbx(), configuration, factory=factory, token=token, current=current, budget=budget
        )
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


async def recover_financial(
    sources: SourceResources, configuration: Settings, *, factory: SessionFactory, user_id: UUID, purchase_id: UUID
) -> Purchase:
    """Privileged/request-driven Step 8 seam: GET only; no customer ensure or JWT."""
    purchase = await run_in_threadpool(service.inspect_purchase, factory, configuration, user_id, purchase_id)
    _connection(purchase, configuration)
    if not purchase.held or sources.billing is None:
        raise PurchaseRefused("purchase_scope_released", 409)
    await run_in_threadpool(service.verify_original_consent, factory, purchase)
    async with sources.billing.operation() as budget:
        current = await run_in_threadpool(service.customer_for_purchase, factory, configuration, purchase)
        current = await recover_customer(sources.require_lbx(), factory, current, budget=budget)
        return await _prepare(
            sources,
            configuration,
            factory=factory,
            purchase=purchase,
            customer=current,
            budget=budget,
            token=None,
            recover_only=True,
        )
