from fastapi import APIRouter, Depends, HTTPException
from app.core.client_info import ClientInfo, get_client_info
from app.core.database import get_db
from sqlalchemy.orm import Session
from app.core.observability import traced
from app.domains.ordering.schemas import CheckoutIntentRequest, ResolveSellablePlanInput
from app.domains.ordering.exceptions import SellablePlanResolutionError
from app.domains.identity.session import get_current_session
from app.domains.identity.models import User, AuthSession
from app.domains.ordering.services import resolve_checkout_sellable_plan
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