import logging
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.client_info import ClientInfo, get_client_info
from app.core.database import get_db
from app.core.observability import record_checkout, traced
from app.domains.identity.models import AuthSession, User
from app.domains.identity.session import get_current_session, utc_now
from app.domains.ordering.exceptions import (
    MissingRequiredDocumentsError,
    SellablePlanResolutionError,
)
from app.domains.ordering.schemas import CheckoutIntentRequest, ResolveSellablePlanInput
from app.domains.ordering.services import (
    create_checkout_intent_artifacts,
    ensure_user_has_accepted_required_documents,
    make_invoice_id,
    resolve_checkout_sellable_plan,
)
from app.domains.ordering.utils import (
    build_required_document_acceptance_text,
    hash_text,
)
from app.payment_providers import (
    CheckoutProviderUnavailableError,
    PaymentProviderConfigurationError,
    PaymentProviderRegistry,
    get_or_create_checkout_provider_account,
    get_payment_provider_registry,
)
from app.payment_providers.contracts import PrepareCheckoutActionInput


logger = logging.getLogger("Ordering")

ordering_router = APIRouter(prefix="/ordering", tags=["Ordering"])


@ordering_router.post("/checkout/intent")
@traced("billing.checkout_intent.create")
def create_checkout_intent(
    payload: CheckoutIntentRequest,
    client_info: ClientInfo = Depends(get_client_info),
    current: tuple[User, AuthSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
    providers: PaymentProviderRegistry = Depends(get_payment_provider_registry),
):
    user, _ = current

    try:
        sellable_plan = resolve_checkout_sellable_plan(
            db,
            payload=ResolveSellablePlanInput(
                tenant_id=user.tenant_id,
                region=user.region,
                entrypoint_code=payload.product,
                plan_code=payload.plan_code,
            ),
        )
    except SellablePlanResolutionError as exc:
        logger.warning(
            "checkout intent sellable plan resolution failed",
            extra={"structured": exc.log_context()},
        )
        raise HTTPException(status_code=400, detail=exc.code) from exc

    try:
        ensure_user_has_accepted_required_documents(db, user=user)
    except MissingRequiredDocumentsError as exc:
        logger.warning(
            "checkout intent blocked by missing required documents",
            extra={"structured": exc.log_context()},
        )
        raise HTTPException(
            status_code=409,
            detail={
                "code": exc.code,
                "documents": [
                    {
                        "document_version_id": str(document.id),
                        "doc_type": document.doc_type,
                        "version": document.version,
                        "title": document.title,
                        "url_path": document.url_path,
                        "acceptance_text": build_required_document_acceptance_text(
                            title=document.title
                        ),
                        "acceptance_text_hash": hash_text(
                            build_required_document_acceptance_text(
                                title=document.title
                            )
                        ),
                    }
                    for document in exc.documents
                ],
            },
        ) from exc

    try:
        provider_account, provider_adapter = get_or_create_checkout_provider_account(
            db,
            user=user,
            registry=providers,
        )
    except CheckoutProviderUnavailableError as exc:
        logger.warning(
            "checkout intent payment provider unavailable",
            extra={"structured": exc.log_context()},
        )
        raise HTTPException(status_code=503, detail=exc.code) from exc

    invoice_id = make_invoice_id(sellable_plan.entrypoint_value)
    if sellable_plan.currency != provider_account.default_currency:
        record_checkout("provider_currency_mismatch")
        logger.warning("checkout intent provider currency mismatch")
        raise HTTPException(status_code=409, detail="provider_currency_mismatch")

    expires_at = utc_now() + timedelta(minutes=30)
    try:
        checkout_action = provider_adapter.prepare_checkout_action(
            provider_account=provider_account,
            checkout=PrepareCheckoutActionInput(
                amount_minor=sellable_plan.price_amount_minor,
                currency=sellable_plan.currency,
                merchant_order_id=invoice_id,
                provider_invoice_id=invoice_id,
                account_id=user.email,
                description=sellable_plan.name,
                metadata={
                    "product_code": payload.product,
                    "plan_code": sellable_plan.code,
                },
            ),
        )
    except PaymentProviderConfigurationError as exc:
        record_checkout("provider_configuration_error")
        raise HTTPException(status_code=409, detail=exc.code) from exc

    create_checkout_intent_artifacts(
        db,
        payload=payload,
        user=user,
        client_info=client_info,
        sellable_plan=sellable_plan,
        provider_account=provider_account,
        invoice_id=invoice_id,
        expires_at=expires_at,
        checkout_action=checkout_action,
    )
    record_checkout("created")

    amount_minor = sellable_plan.price_amount_minor
    return {
        "status": "pending",
        "product_state": {
                "product_code": payload.product,
                "status": "pending",
            },
        "checkout": {
            "amount_minor": amount_minor,
            "amount": round(amount_minor / 100, 2),
            "currency": sellable_plan.currency,
            "action": checkout_action.as_response(),
        },
    }
