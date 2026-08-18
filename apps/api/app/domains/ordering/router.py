from fastapi import APIRouter, Depends
from app.core.client_info import ClientInfo, get_client_info
from app.core.database import get_db
from sqlalchemy.orm import Session
from app.core.observability import traced
from app.domains.ordering.schemas import CheckoutIntentRequest
from app.domains.identity.session import get_current_session
from app.domains.identity.models import User, AuthSession


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