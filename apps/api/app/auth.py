from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ProductAccessState, User, UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_TTL_DAYS = 30
PBKDF2_ITERATIONS = 120_000
PRODUCT_DEFAULTS = {
    "document-summary": {
        "plan_code": "document-summary-pro",
        "plan_name": "Document Summary Pro",
    },
    "prompt-optimizer": {
        "plan_code": "prompt-optimizer-pro",
        "plan_name": "Prompt Optimizer Pro",
    },
}


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    personal_consent: bool
    offer_consent: bool


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class CheckoutIntentRequest(BaseModel):
    product: str
    plan_code: str
    auto_renew: bool = False


def utc_now() -> datetime:
    return datetime.utcnow()


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), PBKDF2_ITERATIONS
    ).hex()
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations_raw, salt, expected = encoded.split("$", 3)
    except ValueError:
        return False

    if algorithm != "pbkdf2_sha256":
        return False

    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        int(iterations_raw),
    ).hex()
    return hmac.compare_digest(digest, expected)


def make_session_token() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = utc_now() + timedelta(days=SESSION_TTL_DAYS)
    return token, token_hash, expires_at


def make_invoice_id(product_code: str) -> str:
    return f"{product_code}-{secrets.token_hex(8)}"


def present_product_state(state: ProductAccessState | None, product_code: str) -> dict:
    default_plan = PRODUCT_DEFAULTS.get(product_code, {})
    return {
        "product_code": product_code,
        "plan_code": state.plan_code if state else default_plan.get("plan_code"),
        "plan_name": default_plan.get("plan_name"),
        "invoice_id": state.last_invoice_id if state else None,
        "transaction_id": state.last_transaction_id if state else None,
        "status": state.status if state else "inactive",
        "starts_at": state.starts_at.isoformat() if state and state.starts_at else None,
        "expires_at": state.expires_at.isoformat() if state and state.expires_at else None,
    }


def get_current_session(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> tuple[User, UserSession]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_session")

    token = authorization.removeprefix("Bearer ").strip()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    session = (
        db.query(UserSession)
        .filter(UserSession.token_hash == token_hash)
        .first()
    )
    if session is None or session.expires_at <= utc_now():
        raise HTTPException(status_code=401, detail="invalid_session")

    user = db.query(User).filter(User.id == session.user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_session")

    session.last_seen_at = utc_now()
    db.add(session)
    db.commit()
    db.refresh(session)
    return user, session


@router.post("/register")
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    if not payload.personal_consent:
        raise HTTPException(status_code=400, detail="missing_personal_consent")
    if not payload.offer_consent:
        raise HTTPException(status_code=400, detail="missing_offer_consent")

    normalized_email = payload.email.lower()
    existing = db.query(User).filter(User.email == normalized_email).first()
    if existing is not None:
        raise HTTPException(status_code=409, detail="email_already_registered")

    user = User(email=normalized_email, password_hash=hash_password(payload.password))
    db.add(user)
    db.commit()
    db.refresh(user)

    token, token_hash, expires_at = make_session_token()
    session = UserSession(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
    db.add(session)
    db.commit()

    return {
      "status": "registered",
      "token": token,
      "user": {"email": user.email},
    }


@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    normalized_email = payload.email.lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if user is None or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    token, token_hash, expires_at = make_session_token()
    session = UserSession(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
    db.add(session)
    db.commit()

    return {
        "status": "authenticated",
        "token": token,
        "user": {"email": user.email},
    }


@router.get("/session")
def get_session(
    product: str | None = None,
    current: tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user, _ = current

    product_state = None
    if product:
        state = (
            db.query(ProductAccessState)
            .filter(
                ProductAccessState.user_id == user.id,
                ProductAccessState.product_code == product,
            )
            .first()
        )
        product_state = present_product_state(state, product)

    return {
        "authenticated": True,
        "user": {"email": user.email},
        "product_state": product_state,
    }


@router.get("/payment-status")
def get_payment_status(
    invoice_id: str = Query(min_length=1),
    email: EmailStr = Query(),
    db: Session = Depends(get_db),
):
    normalized_email = email.lower()
    user = db.query(User).filter(User.email == normalized_email).first()
    if user is None:
        raise HTTPException(status_code=404, detail="payment_not_found")

    state = (
        db.query(ProductAccessState)
        .filter(
            ProductAccessState.user_id == user.id,
            ProductAccessState.last_invoice_id == invoice_id,
        )
        .first()
    )
    if state is None:
        raise HTTPException(status_code=404, detail="payment_not_found")

    return {
        "email": normalized_email,
        "product_state": present_product_state(state, state.product_code),
    }


@router.post("/logout")
def logout(
    current: tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    _, session = current
    db.delete(session)
    db.commit()
    return {"status": "logged_out"}


@router.post("/checkout-intent")
def create_checkout_intent(
    payload: CheckoutIntentRequest,
    current: tuple[User, UserSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user, _ = current
    invoice_id = make_invoice_id(payload.product)
    state = (
        db.query(ProductAccessState)
        .filter(
            ProductAccessState.user_id == user.id,
            ProductAccessState.product_code == payload.product,
        )
        .first()
    )
    if state is None:
        state = ProductAccessState(
            user_id=user.id,
            product_code=payload.product,
            plan_code=payload.plan_code,
            last_invoice_id=invoice_id,
            status="pending",
            starts_at=utc_now(),
        )
    else:
        state.plan_code = payload.plan_code
        state.last_invoice_id = invoice_id
        state.last_transaction_id = None
        state.status = "pending"
        state.starts_at = utc_now()
    db.add(state)
    db.commit()
    db.refresh(state)

    return {"status": "pending", "product_state": present_product_state(state, payload.product)}
