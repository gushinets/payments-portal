from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime
from app.core.observability import record_checkout
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.client_info import ClientInfo
from app.domains.billing.models import ProductAccessState
from app.domains.billing.schemas import BundleStatus, PlanScopeType, ProductStatus
from app.domains.identity.models import User
from app.domains.identity.session import utc_now
from app.domains.ordering.exceptions import (
    CheckoutIntentPersistenceError,
    MissingRequiredDocumentsError,
    SellablePlanResolutionError,
)
from app.domains.ordering.schemas import (
    CheckoutIntentRequest,
    CreateCheckoutSessionInput,
    CreateEntrypointSessionInput,
    CreateOrderInput,
    CreateOrderItemInput,
    ResolveSellablePlanInput,
    SellablePlan,
)
from app.infrastructure.queries.document import (
    get_accepted_document_version_ids_for_user,
    get_active_required_documents,
)
from app.infrastructure.queries.plan import (
    get_active_plan_by_code,
    get_bundle_by_id,
    get_product_by_id,
)
from app.models import CheckoutSession, EntrypointSession, Order, OrderItem, PaymentProviderAccount
from app.payment_providers.contracts import CheckoutAction


@dataclass(frozen=True)
class CheckoutIntentArtifacts:
    entrypoint_session: EntrypointSession
    checkout_session: CheckoutSession
    order: Order
    order_item: OrderItem
    product_state: ProductAccessState


def make_invoice_id(product_code: str) -> str:
    return f"{product_code}-{secrets.token_hex(8)}"


def make_order_number(region: str) -> str:
    return f"{region.upper()}-{utc_now().strftime('%Y%m%d')}-{secrets.token_hex(4).upper()}"


def resolve_checkout_sellable_plan(
    db: Session,
    *,
    payload: ResolveSellablePlanInput,
) -> SellablePlan:
    plan = get_active_plan_by_code(
        db,
        tenant_id=payload.tenant_id,
        region=payload.region,
        plan_code=payload.plan_code,
    )
    if plan is None:
        raise SellablePlanResolutionError(
            reason="plan_not_found",
            payload=payload,
        )

    entrypoint_value = plan.code
    if plan.scope_type == PlanScopeType.PRODUCT.value:
        product = get_product_by_id(db, product_id=plan.product_id)
        if product is None or product.status != ProductStatus.ACTIVE.value or product.code != payload.entrypoint_code:
            raise SellablePlanResolutionError(
                reason="invalid_product_plan",
                payload=payload,
                plan=plan,
            )
        entrypoint_value = product.code
    elif plan.scope_type == PlanScopeType.BUNDLE.value:
        bundle = get_bundle_by_id(db, bundle_id=plan.bundle_id)
        if bundle is None or bundle.status != BundleStatus.ACTIVE.value or bundle.code != payload.entrypoint_code:
            raise SellablePlanResolutionError(
                reason="invalid_bundle_plan",
                payload=payload,
                plan=plan,
            )
        entrypoint_value = bundle.code
    elif plan.scope_type == PlanScopeType.ALL_ACCESS.value:
        if payload.entrypoint_code not in {PlanScopeType.ALL_ACCESS.value, plan.code}:
            raise SellablePlanResolutionError(
                reason="entrypoint_scope_mismatch",
                payload=payload,
                plan=plan,
            )
        entrypoint_value = PlanScopeType.ALL_ACCESS.value
    else:
        raise SellablePlanResolutionError(
            reason="unsupported_scope_type",
            payload=payload,
            plan=plan,
        )

    return SellablePlan.create(
        plan=plan,
        entrypoint_value=entrypoint_value,
    )


def ensure_user_has_accepted_required_documents(
    db: Session,
    *,
    user: User,
) -> None:
    required_documents = get_active_required_documents(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
    )
    if not required_documents:
        return

    accepted_version_ids = get_accepted_document_version_ids_for_user(
        db,
        user=user,
        document_version_ids=[document.id for document in required_documents],
    )
    missing_documents = [
        document
        for document in required_documents
        if document.id not in accepted_version_ids
    ]
    if missing_documents:
        record_checkout("missing_required_documents")
        raise MissingRequiredDocumentsError(
            user_id=str(user.id),
            documents=missing_documents,
        )


def create_checkout_intent_artifacts(
    db: Session,
    *,
    payload: CheckoutIntentRequest,
    user: User,
    client_info: ClientInfo,
    sellable_plan: SellablePlan,
    provider_account: PaymentProviderAccount,
    invoice_id: str,
    expires_at: datetime,
    checkout_action: CheckoutAction,
) -> CheckoutIntentArtifacts:
    try:
        entrypoint_session_input = CreateEntrypointSessionInput.create(
            payload=payload,
            user=user,
            client_info=client_info,
            sellable_plan=sellable_plan,
        )
        entrypoint_session = EntrypointSession(**entrypoint_session_input.model_dump())
        db.add(entrypoint_session)
        db.flush()

        checkout_session_input = CreateCheckoutSessionInput.create(
            payload=payload,
            user=user,
            sellable_plan=sellable_plan,
            entrypoint_session_id=entrypoint_session.id,
            expires_at=expires_at,
        )
        checkout_session = CheckoutSession(**checkout_session_input.model_dump())
        db.add(checkout_session)
        db.flush()

        order_input = CreateOrderInput.create(
            payload=payload,
            user=user,
            sellable_plan=sellable_plan,
            provider_account_id=provider_account.id,
            provider=provider_account.provider,
            order_number=make_order_number(user.region),
            merchant_order_id=invoice_id,
            checkout_session_id=checkout_session.id,
            entrypoint_session_id=entrypoint_session.id,
            expires_at=expires_at,
        )
        order = Order(**order_input.model_dump())
        order.metadata_ = {
            **order.metadata_,
            "payment_mode": checkout_action.mode,
        }
        db.add(order)
        db.flush()

        order_item_input = CreateOrderItemInput.create(
            payload=payload,
            sellable_plan=sellable_plan,
            order_id=order.id,
        )
        order_item = OrderItem(**order_item_input.model_dump())
        db.add(order_item)

        now = utc_now()
        product_state = (
            db.query(ProductAccessState)
            .filter(
                ProductAccessState.user_id == user.id,
                ProductAccessState.product_code == payload.product,
            )
            .first()
        )
        if product_state is None:
            product_state = ProductAccessState(
                user_id=user.id,
                product_code=payload.product,
                plan_code=sellable_plan.code,
                last_invoice_id=invoice_id,
                status="pending",
                starts_at=now,
            )
        else:
            product_state.plan_code = sellable_plan.code
            product_state.last_invoice_id = invoice_id
            product_state.last_transaction_id = None
            product_state.status = "pending"
            product_state.starts_at = now
        db.add(product_state)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise CheckoutIntentPersistenceError() from exc

    return CheckoutIntentArtifacts(
        entrypoint_session=entrypoint_session,
        checkout_session=checkout_session,
        order=order,
        order_item=order_item,
        product_state=product_state,
    )
