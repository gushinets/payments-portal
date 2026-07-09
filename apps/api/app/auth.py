from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.legal_consents import (
    build_acceptance_text,
    expected_acceptance_text_hash,
    get_missing_required_documents_for_user,
)
from app.models import AuthSession, ProductAccessState, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

DEFAULT_TENANT_ID = "anytoolai"
DEFAULT_REGION = "ru"
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
    tenant_id: str = DEFAULT_TENANT_ID
    region: str = DEFAULT_REGION
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    personal_consent: bool
    offer_consent: bool


class LoginRequest(BaseModel):
    tenant_id: str = DEFAULT_TENANT_ID
    region: str = DEFAULT_REGION
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class CheckoutIntentRequest(BaseModel):
    product: str
    plan_code: str
    auto_renew: bool = False


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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


def normalize_tenant_id(value: str) -> str:
    return value.strip().lower()


def normalize_region(value: str) -> str:
    return value.strip().lower()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def present_user(user: User) -> dict:
    return {
        "tenant_id": user.tenant_id,
        "region": user.region,
        "user_id": str(user.id),
        "email": user.email,
    }


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
) -> tuple[User, AuthSession]:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing_session")

    token = authorization.removeprefix("Bearer ").strip()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    session = (
        db.query(AuthSession)
        .filter(AuthSession.token_hash == token_hash)
        .first()
    )
    if (
        session is None
        or session.revoked_at is not None
        or as_utc(session.expires_at) <= utc_now()
    ):
        raise HTTPException(status_code=401, detail="invalid_session")

    user = (
        db.query(User)
        .filter(
            User.id == session.user_id,
            User.tenant_id == session.tenant_id,
            User.region == session.region,
        )
        .first()
    )
    if user is None:
        raise HTTPException(status_code=401, detail="invalid_session")

    session.last_seen_at = utc_now()
    db.add(session)
    db.commit()
    db.refresh(session)
    return user, session


@router.post("/register")
def register(
    payload: RegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    if not payload.personal_consent:
        raise HTTPException(status_code=400, detail="missing_personal_consent")
    if not payload.offer_consent:
        raise HTTPException(status_code=400, detail="missing_offer_consent")

    tenant_id = normalize_tenant_id(payload.tenant_id)
    region = normalize_region(payload.region)
    normalized_email = normalize_email(str(payload.email))
    existing = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.region == region,
            User.email_normalized == normalized_email,
        )
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="email_already_registered")

    user = User(
        tenant_id=tenant_id,
        region=region,
        email=str(payload.email),
        email_normalized=normalized_email,
        password_hash=hash_password(payload.password),
        email_verified_at=utc_now(),
        status="active",
        last_login_at=utc_now(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token, token_hash, expires_at = make_session_token()
    session = AuthSession(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    db.commit()

    return {
        "status": "registered",
        "token": token,
        "user": present_user(user),
    }


@router.post("/login")
def login(
    payload: LoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_id = normalize_tenant_id(payload.tenant_id)
    region = normalize_region(payload.region)
    normalized_email = normalize_email(str(payload.email))
    user = (
        db.query(User)
        .filter(
            User.tenant_id == tenant_id,
            User.region == region,
            User.email_normalized == normalized_email,
        )
        .first()
    )
    if (
        user is None
        or user.password_hash is None
        or not verify_password(payload.password, user.password_hash)
    ):
        raise HTTPException(status_code=401, detail="invalid_credentials")

    user.last_login_at = utc_now()
    db.add(user)
    token, token_hash, expires_at = make_session_token()
    session = AuthSession(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    db.add(session)
    db.commit()

    return {
        "status": "authenticated",
        "token": token,
        "user": present_user(user),
    }


@router.get("/session")
def get_session(
    product: str | None = None,
    current: tuple[User, AuthSession] = Depends(get_current_session),
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
        "user": present_user(user),
        "product_state": product_state,
    }


@router.get("/payment-status")
def get_payment_status(
    invoice_id: str = Query(min_length=1),
    email: EmailStr = Query(),
    tenant_id: str = Query(default=DEFAULT_TENANT_ID),
    region: str = Query(default=DEFAULT_REGION),
    db: Session = Depends(get_db),
):
    normalized_email = normalize_email(str(email))
    user = (
        db.query(User)
        .filter(
            User.tenant_id == normalize_tenant_id(tenant_id),
            User.region == normalize_region(region),
            User.email_normalized == normalized_email,
        )
        .first()
    )
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
        "tenant_id": user.tenant_id,
        "region": user.region,
        "user_id": str(user.id),
        "email": normalized_email,
        "product_state": present_product_state(state, state.product_code),
    }


@router.post("/logout")
def logout(
    current: tuple[User, AuthSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    _, session = current
    db.delete(session)
    db.commit()
    return {"status": "logged_out"}


@router.post("/checkout-intent")
def create_checkout_intent(
    payload: CheckoutIntentRequest,
    current: tuple[User, AuthSession] = Depends(get_current_session),
    db: Session = Depends(get_db),
):
    user, _ = current
    missing_documents = get_missing_required_documents_for_user(db, user=user)
    if missing_documents:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "missing_required_documents",
                "documents": [
                    {
                        "document_version_id": str(document.id),
                        "doc_type": document.doc_type,
                        "version": document.version,
                        "title": document.title,
                        "url_path": document.url_path,
                        "acceptance_text": build_acceptance_text(document),
                        "acceptance_text_hash": expected_acceptance_text_hash(document),
                    }
                    for document in missing_documents
                ],
            },
        )

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
