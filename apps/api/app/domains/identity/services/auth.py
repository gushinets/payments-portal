from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domains.identity.errors import (
    EmailAlreadyRegisteredError,
    InvalidAuthSessionError,
    InvalidCredentialsError,
    MissingOfferConsentError,
    MissingPersonalConsentError,
)
from app.domains.identity.passwords import hash_password, verify_password
from app.infrastructure.queries.identity import (
    get_auth_session_by_token_hash,
    get_user_by_normalized_email,
    get_user_for_auth_session,
)
from app.models import AuthSession, User, UserStatus


SESSION_TTL_DAYS = 30


@dataclass(frozen=True)
class AuthenticationResult:
    user: User
    token: str


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def normalize_tenant_id(value: str) -> str:
    return value.strip().lower()


def normalize_region(value: str) -> str:
    return value.strip().lower()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def make_session_token() -> tuple[str, str, datetime]:
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    expires_at = utc_now() + timedelta(days=SESSION_TTL_DAYS)
    return token, token_hash, expires_at


def authenticate_session(db: Session, *, token: str) -> tuple[User, AuthSession]:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    auth_session = get_auth_session_by_token_hash(db, token_hash)
    if auth_session is None or auth_session.revoked_at is not None or as_utc(auth_session.expires_at) <= utc_now():
        raise InvalidAuthSessionError()

    user = get_user_for_auth_session(db, auth_session)
    if user is None:
        raise InvalidAuthSessionError()

    auth_session.last_seen_at = utc_now()
    db.add(auth_session)
    db.commit()
    db.refresh(auth_session)
    return user, auth_session


def register_user(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    email: str,
    password: str,
    personal_consent: bool,
    offer_consent: bool,
    client_ip: str | None,
    user_agent: str | None,
) -> AuthenticationResult:
    if not personal_consent:
        raise MissingPersonalConsentError()
    if not offer_consent:
        raise MissingOfferConsentError()

    normalized_tenant_id = normalize_tenant_id(tenant_id)
    normalized_region = normalize_region(region)
    normalized_email = normalize_email(email)
    existing = get_user_by_normalized_email(
        db,
        tenant_id=normalized_tenant_id,
        region=normalized_region,
        email_normalized=normalized_email,
    )
    if existing is not None:
        raise EmailAlreadyRegisteredError()

    user = User(
        tenant_id=normalized_tenant_id,
        region=normalized_region,
        email=email,
        email_normalized=normalized_email,
        password_hash=hash_password(password),
        email_verified_at=utc_now(),
        status=UserStatus.ACTIVE,
        last_login_at=utc_now(),
    )
    db.add(user)
    db.flush()

    token, token_hash, expires_at = make_session_token()
    auth_session = AuthSession(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        ip=client_ip,
        user_agent=user_agent,
    )
    db.add(auth_session)
    db.commit()
    return AuthenticationResult(user=user, token=token)


def login_user(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    email: str,
    password: str,
    client_ip: str | None,
    user_agent: str | None,
) -> AuthenticationResult:
    user = get_user_by_normalized_email(
        db,
        tenant_id=normalize_tenant_id(tenant_id),
        region=normalize_region(region),
        email_normalized=normalize_email(email),
    )
    if user is None or user.password_hash is None or not verify_password(password, user.password_hash):
        raise InvalidCredentialsError()

    user.last_login_at = utc_now()
    db.add(user)
    token, token_hash, expires_at = make_session_token()
    auth_session = AuthSession(
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        token_hash=token_hash,
        expires_at=expires_at,
        ip=client_ip,
        user_agent=user_agent,
    )
    db.add(auth_session)
    db.commit()
    return AuthenticationResult(user=user, token=token)


def logout_session(db: Session, *, auth_session: AuthSession) -> None:
    db.delete(auth_session)
    db.commit()
