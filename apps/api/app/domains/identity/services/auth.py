from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.core.time import utc_now
from app.domains.identity.errors import (
    AuthenticationRateLimitedError,
    EmailVerificationRequiredError,
    InvalidAuthSessionError,
    InvalidCredentialsError,
    InvalidOrExpiredVerificationTokenError,
    MissingOfferConsentError,
    MissingPersonalConsentError,
)
from app.domains.identity.passwords import hash_password, password_hash_needs_rehash, verify_password
from app.domains.identity.services.email_verification import (
    EmailVerificationDeliveryResult,
    make_email_verification_delivery,
    make_email_verification_token,
    make_skipped_email_verification_delivery,
)
from app.domains.legal.service import (
    create_registration_legal_evidence,
    get_registration_required_documents,
)
from app.generated.locales import RouteLocale
from app.infrastructure.persistence.authentication_rate_limit import (
    clear_authentication_rate_limit,
    get_login_account_rate_limit_state,
    increment_authentication_rate_limit,
    prune_expired_authentication_rate_limits,
    record_login_account_failure,
)
from app.infrastructure.persistence.email_verification import (
    claim_valid_email_verification_token,
    invalidate_outstanding_email_verification_tokens,
)
from app.infrastructure.persistence.identity import is_scoped_email_unique_conflict
from app.infrastructure.queries.identity import (
    get_active_user_by_normalized_email,
    get_active_user_for_auth_session,
    get_auth_session_by_token_hash,
    get_magic_link_token_by_hash_and_purpose,
    get_user_by_normalized_email,
    lock_active_user_by_id_and_scope,
    lock_active_user_by_normalized_email,
)
from app.models import AuthSession, MagicLinkPurpose, MagicLinkToken, User, UserStatus


SESSION_TTL_DAYS = 30
AUTHENTICATION_RATE_LIMIT_WINDOW_MINUTES = 15
REGISTRATION_ACCOUNT_RATE_LIMIT_MAX = 5
REGISTRATION_SOURCE_RATE_LIMIT_MAX = 20
VERIFICATION_ACCOUNT_RATE_LIMIT_MAX = 5
VERIFICATION_SOURCE_RATE_LIMIT_MAX = 20
LOGIN_SOURCE_RATE_LIMIT_MAX = 50
LOGIN_ACCOUNT_COOLDOWN_START = 10
LOGIN_ACCOUNT_COOLDOWN_MAX_SECONDS = 60
DUMMY_ARGON2_PASSWORD_HASH = hash_password("anytoolai-authentication-timing-placeholder")


@dataclass(frozen=True)
class AuthenticationResult:
    token: str
    user_id: uuid.UUID
    tenant_id: str
    region: str
    email: str


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


def authentication_rate_limit_keys(
    *,
    namespace: str,
    tenant_id: str,
    region: str,
    email_normalized: str,
    client_ip: str,
) -> tuple[str, str]:
    return (
        f"{namespace}:account:{tenant_id}:{region}:{email_normalized}",
        f"{namespace}:ip:{tenant_id}:{region}:{client_ip}",
    )


def login_account_rate_limit_key(
    *,
    tenant_id: str,
    region: str,
    email_normalized: str,
) -> str:
    return f"login:account:{tenant_id}:{region}:{email_normalized}"


def _persist_fixed_window_attempt(
    db: Session,
    *,
    key: str,
    limit: int,
    now: datetime,
) -> None:
    try:
        attempts = increment_authentication_rate_limit(
            db,
            key=key,
            now=now,
            expires_at=now + timedelta(minutes=AUTHENTICATION_RATE_LIMIT_WINDOW_MINUTES),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    if attempts > limit:
        raise AuthenticationRateLimitedError()


def _prepare_rate_limit_window(db: Session, *, now: datetime) -> None:
    try:
        prune_expired_authentication_rate_limits(db, now=now)
        db.commit()
    except Exception:
        db.rollback()
        raise


def _enforce_account_and_source_limits(
    db: Session,
    *,
    namespace: str,
    tenant_id: str,
    region: str,
    email_normalized: str,
    client_ip: str,
    account_limit: int,
    source_limit: int,
    now: datetime,
) -> None:
    account_key, source_key = authentication_rate_limit_keys(
        namespace=namespace,
        tenant_id=tenant_id,
        region=region,
        email_normalized=email_normalized,
        client_ip=client_ip,
    )
    _prepare_rate_limit_window(db, now=now)
    _persist_fixed_window_attempt(db, key=source_key, limit=source_limit, now=now)
    _persist_fixed_window_attempt(db, key=account_key, limit=account_limit, now=now)


def _authentication_result(*, user: User, token: str) -> AuthenticationResult:
    return AuthenticationResult(
        token=token,
        user_id=user.id,
        tenant_id=user.tenant_id,
        region=user.region,
        email=user.email,
    )


def _create_auth_session(
    *,
    user: User,
    client_ip: str | None,
    user_agent: str | None,
) -> tuple[AuthSession, str]:
    token, token_hash, expires_at = make_session_token()
    return (
        AuthSession(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            token_hash=token_hash,
            expires_at=expires_at,
            ip=client_ip,
            user_agent=user_agent,
        ),
        token,
    )


def authenticate_session(
    db: Session,
    *,
    token: str,
    tenant_id: str,
    region: str,
) -> tuple[User, AuthSession]:
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    auth_session = get_auth_session_by_token_hash(db, token_hash)
    if (
        auth_session is None
        or auth_session.tenant_id != tenant_id
        or auth_session.region != region
        or auth_session.revoked_at is not None
        or as_utc(auth_session.expires_at) <= utc_now()
    ):
        raise InvalidAuthSessionError()

    user = get_active_user_for_auth_session(db, auth_session)
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
    route_locale: RouteLocale = "ru",
) -> EmailVerificationDeliveryResult:
    if not personal_consent:
        raise MissingPersonalConsentError()
    if not offer_consent:
        raise MissingOfferConsentError()

    normalized_tenant_id = normalize_tenant_id(tenant_id)
    normalized_region = normalize_region(region)
    normalized_email = normalize_email(email)
    now = utc_now()
    _enforce_account_and_source_limits(
        db,
        namespace="registration",
        tenant_id=normalized_tenant_id,
        region=normalized_region,
        email_normalized=normalized_email,
        client_ip=client_ip or "unknown",
        account_limit=REGISTRATION_ACCOUNT_RATE_LIMIT_MAX,
        source_limit=REGISTRATION_SOURCE_RATE_LIMIT_MAX,
        now=now,
    )

    existing = get_user_by_normalized_email(
        db,
        tenant_id=normalized_tenant_id,
        region=normalized_region,
        email_normalized=normalized_email,
    )
    if existing is not None:
        db.rollback()
        return make_skipped_email_verification_delivery(
            recipient_email=normalized_email,
            route_locale=route_locale,
        )

    try:
        registration_documents = get_registration_required_documents(
            db,
            tenant_id=normalized_tenant_id,
            region=normalized_region,
            now=now,
        )
        user = User(
            tenant_id=normalized_tenant_id,
            region=normalized_region,
            email=email,
            email_normalized=normalized_email,
            password_hash=hash_password(password),
            email_verified_at=None,
            status=UserStatus.ACTIVE,
            last_login_at=None,
        )
        db.add(user)
        db.flush()

        create_registration_legal_evidence(
            db,
            user=user,
            documents=registration_documents,
            accepted_at=now,
            ip=client_ip,
            user_agent=user_agent,
        )

        token, token_hash, expires_at = make_email_verification_token()
        db.add(
            MagicLinkToken(
                tenant_id=user.tenant_id,
                region=user.region,
                user_id=user.id,
                email_normalized=user.email_normalized,
                token_hash=token_hash,
                purpose=MagicLinkPurpose.EMAIL_VERIFICATION,
                expires_at=expires_at,
                ip=client_ip,
                user_agent=user_agent,
            )
        )
        delivery = make_email_verification_delivery(
            recipient_email=user.email,
            token=token,
            route_locale=route_locale,
            user_id=user.id,
        )
        db.commit()
        return delivery
    except Exception as exc:
        db.rollback()
        if not is_scoped_email_unique_conflict(exc):
            raise
        winner = get_user_by_normalized_email(
            db,
            tenant_id=normalized_tenant_id,
            region=normalized_region,
            email_normalized=normalized_email,
        )
        if winner is None:
            raise
        db.rollback()
        return make_skipped_email_verification_delivery(
            recipient_email=normalized_email,
            route_locale=route_locale,
        )


def request_email_verification(
    db: Session,
    *,
    tenant_id: str,
    region: str,
    email: str,
    client_ip: str | None,
    user_agent: str | None,
    route_locale: RouteLocale,
) -> EmailVerificationDeliveryResult:
    normalized_tenant_id = normalize_tenant_id(tenant_id)
    normalized_region = normalize_region(region)
    normalized_email = normalize_email(email)
    now = utc_now()
    _enforce_account_and_source_limits(
        db,
        namespace="verification",
        tenant_id=normalized_tenant_id,
        region=normalized_region,
        email_normalized=normalized_email,
        client_ip=client_ip or "unknown",
        account_limit=VERIFICATION_ACCOUNT_RATE_LIMIT_MAX,
        source_limit=VERIFICATION_SOURCE_RATE_LIMIT_MAX,
        now=now,
    )

    user = lock_active_user_by_normalized_email(
        db,
        tenant_id=normalized_tenant_id,
        region=normalized_region,
        email_normalized=normalized_email,
    )
    if user is None or user.email_verified_at is not None:
        db.rollback()
        return make_skipped_email_verification_delivery(
            recipient_email=normalized_email,
            route_locale=route_locale,
        )

    invalidate_outstanding_email_verification_tokens(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        now=now,
    )
    token, token_hash, expires_at = make_email_verification_token()
    db.add(
        MagicLinkToken(
            tenant_id=user.tenant_id,
            region=user.region,
            user_id=user.id,
            email_normalized=user.email_normalized,
            token_hash=token_hash,
            purpose=MagicLinkPurpose.EMAIL_VERIFICATION,
            expires_at=expires_at,
            ip=client_ip,
            user_agent=user_agent,
        )
    )
    delivery = make_email_verification_delivery(
        recipient_email=user.email,
        token=token,
        route_locale=route_locale,
        user_id=user.id,
    )
    db.commit()
    return delivery


def confirm_email_verification(
    db: Session,
    *,
    token: str,
    password: str,
    tenant_id: str,
    region: str,
    client_ip: str | None,
    user_agent: str | None,
) -> AuthenticationResult:
    normalized_tenant_id = normalize_tenant_id(tenant_id)
    normalized_region = normalize_region(region)
    now = utc_now()
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    candidate = get_magic_link_token_by_hash_and_purpose(
        db,
        token_hash=token_hash,
        purpose=MagicLinkPurpose.EMAIL_VERIFICATION,
    )
    if (
        candidate is None
        or candidate.tenant_id != normalized_tenant_id
        or candidate.region != normalized_region
        or candidate.user_id is None
    ):
        db.rollback()
        raise InvalidOrExpiredVerificationTokenError()

    user = lock_active_user_by_id_and_scope(
        db,
        user_id=candidate.user_id,
        tenant_id=normalized_tenant_id,
        region=normalized_region,
    )
    if user is None:
        db.rollback()
        raise InvalidOrExpiredVerificationTokenError()

    verification_token = get_magic_link_token_by_hash_and_purpose(
        db,
        token_hash=token_hash,
        purpose=MagicLinkPurpose.EMAIL_VERIFICATION,
    )
    if (
        verification_token is None
        or verification_token.user_id != user.id
        or verification_token.tenant_id != user.tenant_id
        or verification_token.region != user.region
        or verification_token.email_normalized != user.email_normalized
        or verification_token.used_at is not None
        or as_utc(verification_token.expires_at) <= now
        or user.email_verified_at is not None
    ):
        db.rollback()
        raise InvalidOrExpiredVerificationTokenError()

    stored_password_hash = user.password_hash
    if stored_password_hash is None or not verify_password(password, stored_password_hash):
        db.rollback()
        raise InvalidCredentialsError()

    if password_hash_needs_rehash(stored_password_hash):
        user.password_hash = hash_password(password)

    claimed = claim_valid_email_verification_token(
        db,
        token_hash=token_hash,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        now=now,
    )
    if claimed != 1:
        db.rollback()
        raise InvalidOrExpiredVerificationTokenError()

    user.email_verified_at = now
    user.last_login_at = now
    db.add(user)
    invalidate_outstanding_email_verification_tokens(
        db,
        tenant_id=user.tenant_id,
        region=user.region,
        user_id=user.id,
        now=now,
    )
    auth_session, session_token = _create_auth_session(
        user=user,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    db.add(auth_session)
    result = _authentication_result(user=user, token=session_token)
    db.commit()
    return result


def _login_account_cooldown_seconds(failure_count: int) -> int:
    if failure_count < LOGIN_ACCOUNT_COOLDOWN_START:
        return 0
    if failure_count >= 16:
        return LOGIN_ACCOUNT_COOLDOWN_MAX_SECONDS
    return 2 ** (failure_count - LOGIN_ACCOUNT_COOLDOWN_START)


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
    normalized_tenant_id = normalize_tenant_id(tenant_id)
    normalized_region = normalize_region(region)
    normalized_email = normalize_email(email)
    now = utc_now()
    _prepare_rate_limit_window(db, now=now)
    _persist_fixed_window_attempt(
        db,
        key=f"login:ip:{normalized_tenant_id}:{normalized_region}:{client_ip or 'unknown'}",
        limit=LOGIN_SOURCE_RATE_LIMIT_MAX,
        now=now,
    )

    account_key = login_account_rate_limit_key(
        tenant_id=normalized_tenant_id,
        region=normalized_region,
        email_normalized=normalized_email,
    )
    failure_state = get_login_account_rate_limit_state(db, key=account_key)
    if failure_state is not None:
        cooldown_seconds = _login_account_cooldown_seconds(failure_state.count)
        if cooldown_seconds and as_utc(failure_state.updated_at) + timedelta(seconds=cooldown_seconds) > now:
            db.rollback()
            raise AuthenticationRateLimitedError()

    user = get_active_user_by_normalized_email(
        db,
        tenant_id=normalized_tenant_id,
        region=normalized_region,
        email_normalized=normalized_email,
    )
    stored_password_hash = user.password_hash if user is not None else None
    password_matches = False
    if stored_password_hash is None:
        verify_password(password, DUMMY_ARGON2_PASSWORD_HASH)
    else:
        password_matches = verify_password(password, stored_password_hash)
        if not password_matches and stored_password_hash.startswith("pbkdf2_sha256$"):
            verify_password(password, DUMMY_ARGON2_PASSWORD_HASH)

    if user is None or stored_password_hash is None or not password_matches:
        try:
            record_login_account_failure(
                db,
                key=account_key,
                now=now,
                expires_at=now + timedelta(minutes=AUTHENTICATION_RATE_LIMIT_WINDOW_MINUTES),
            )
            db.commit()
        except Exception:
            db.rollback()
            raise
        raise InvalidCredentialsError()

    clear_authentication_rate_limit(db, key=account_key)
    if password_hash_needs_rehash(stored_password_hash):
        user.password_hash = hash_password(password)
        db.add(user)
    if user.email_verified_at is None:
        db.commit()
        raise EmailVerificationRequiredError()

    user.last_login_at = now
    db.add(user)
    auth_session, token = _create_auth_session(
        user=user,
        client_ip=client_ip,
        user_agent=user_agent,
    )
    db.add(auth_session)
    result = _authentication_result(user=user, token=token)
    db.commit()
    return result


def logout_session(db: Session, *, auth_session: AuthSession) -> None:
    db.delete(auth_session)
    db.commit()
