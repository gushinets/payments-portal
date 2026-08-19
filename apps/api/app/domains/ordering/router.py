from fastapi import APIRouter, Depends, HTTPException
from app.core.client_info import ClientInfo, get_client_info
from app.core.database import get_db
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.core.observability import traced, record_checkout
from app.domains.ordering.schemas import CheckoutIntentRequest, ResolveSellablePlanInput
from app.domains.ordering.exceptions import (
    MissingRequiredDocumentsError,
    SellablePlanResolutionError,
)
from app.domains.identity.session import get_current_session, utc_now
from app.domains.identity.models import User, AuthSession
from app.domains.ordering.services import (
    ensure_user_has_accepted_required_documents,
    resolve_checkout_sellable_plan,
    make_invoice_id
)
from app.domains.ordering.utils import (
    build_required_document_acceptance_text,
    hash_text,
)
from app.payment_providers import (
    CheckoutProviderUnavailableError,
    PaymentProviderRegistry,
    get_or_create_checkout_provider_account,
    get_payment_provider_registry,
)
import logging

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

    invoice_id = make_invoice_id(sellable_plan["entrypoint_value"])
    # amount_minor = int(sellable_plan["amount_minor"])
    # currency = str(sellable_plan["currency"])
    if sellable_plan.currency != provider_account.default_currency:
        record_checkout("provider_currency_mismatch")
        logger.warning("checkout intent provider currency mismatch")
        raise HTTPException(status_code=409, detail="provider_currency_mismatch")
    expires_at = utc_now() + timedelta(minutes=30)
