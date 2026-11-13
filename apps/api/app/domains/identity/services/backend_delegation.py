"""Delegate existing authority; never create or match a second identity."""

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.backend_consumers import BackendConsumer
from app.infrastructure.queries.backend_policies import BackendPolicyConflict, require_current_policy
from app.core.time import utc_now
from app.domains.identity.errors import InvalidAuthSessionError
from app.domains.identity.services.auth import as_utc, validate_session
from app.infrastructure.queries.identity import lock_active_user_by_id_and_scope
from app.infrastructure.persistence.backend_delegations import delegation_storage_errors
from app.infrastructure.persistence.backend_delegations import DelegationUnavailableError as DelegationUnavailableError
from app.infrastructure.queries.backend_delegations import lock_delegation, lock_parent_session, read_delegation
from app.models import AuthSession, BackendSessionDelegation, User, UserStatus

CODE_TTL_SECONDS = 60
DELEGATION_TTL_SECONDS = 30 * 60


class DelegationRefusal(StrEnum):
    PARENT_INVALID = "backend_parent_authority_invalid"
    CODE_INVALID = "backend_session_code_invalid"
    EXPIRED = "backend_delegation_expired"


class InvalidDelegationError(Exception):
    def __init__(self, code: DelegationRefusal) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class DelegationCode:
    code: str = field(repr=False)
    expires_at: datetime


@dataclass(frozen=True)
class DelegatedIdentity:
    tenant_id: str
    region: str
    user_id: UUID
    expires_at: datetime


@dataclass(frozen=True)
class DelegationToken:
    access_token: str = field(repr=False)
    identity: DelegatedIdentity


def credential_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def pkce_challenge(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")


def _require_parent(user: User | None, parent: AuthSession | None, tenant_id: str, region: str) -> None:
    if (
        user is None
        or parent is None
        or user.status != UserStatus.ACTIVE
        or user.email_verified_at is None
        or (user.tenant_id, user.region) != (tenant_id, region)
        or (parent.user_id, parent.tenant_id, parent.region) != (user.id, tenant_id, region)
        or parent.revoked_at is not None
        or as_utc(parent.expires_at) <= utc_now()
    ):
        raise InvalidDelegationError(DelegationRefusal.PARENT_INVALID)


def issue_code(
    db: Session, *, token: str, tenant_id: str, region: str, code_challenge: str, consumer_id: str
) -> DelegationCode:
    with delegation_storage_errors():
        try:
            user, parent = validate_session(db, token=token, tenant_id=tenant_id, region=region)
        except InvalidAuthSessionError:
            raise InvalidDelegationError(DelegationRefusal.PARENT_INVALID) from None
        user = lock_active_user_by_id_and_scope(db, user_id=user.id, tenant_id=tenant_id, region=region)
        if user is None:
            raise InvalidDelegationError(DelegationRefusal.PARENT_INVALID)
        parent = lock_parent_session(db, parent.id)
        _require_parent(user, parent, tenant_id, region)
        code = secrets.token_urlsafe(32)
        expires_at = min(utc_now() + timedelta(seconds=CODE_TTL_SECONDS), as_utc(parent.expires_at))
        db.add(
            BackendSessionDelegation(
                auth_session_id=parent.id,
                consumer_id=consumer_id,
                code_hash=credential_hash(code),
                code_challenge=code_challenge,
                code_expires_at=expires_at,
            )
        )
        db.commit()
        return DelegationCode(code, expires_at)


def exchange_code(
    db: Session, *, code: str, verifier: str, tenant_id: str, region: str, consumer_id: str
) -> DelegationToken:
    with delegation_storage_errors():
        found = read_delegation(db, credential_hash=credential_hash(code), by_code=True)
        if found is None:
            raise InvalidDelegationError(DelegationRefusal.CODE_INVALID)
        delegation, parent, user = found
        user = lock_active_user_by_id_and_scope(db, user_id=user.id, tenant_id=tenant_id, region=region)
        if user is None:
            raise InvalidDelegationError(DelegationRefusal.PARENT_INVALID)
        parent = lock_parent_session(db, parent.id)
        delegation = lock_delegation(db, delegation.id)
        _require_parent(user, parent, tenant_id, region)
        now = utc_now()
        if (
            delegation is None
            or delegation.consumer_id != consumer_id
            or delegation.exchanged_at is not None
            or as_utc(delegation.code_expires_at) <= now
            or not secrets.compare_digest(delegation.code_challenge, pkce_challenge(verifier))
        ):
            raise InvalidDelegationError(DelegationRefusal.CODE_INVALID)
        token = secrets.token_urlsafe(32)
        expires_at = min(now + timedelta(seconds=DELEGATION_TTL_SECONDS), as_utc(parent.expires_at))
        delegation.exchanged_at = now
        delegation.token_hash = credential_hash(token)
        delegation.token_expires_at = expires_at
        identity = DelegatedIdentity(tenant_id, region, user.id, expires_at)
        db.commit()
        return DelegationToken(token, identity)


def introspect_token(
    db: Session,
    *,
    token: str,
    tenant_id: str,
    region: str,
    clock_skew_seconds: int,
    consumer_id: str,
) -> DelegatedIdentity:
    with delegation_storage_errors():
        found = read_delegation(db, credential_hash=credential_hash(token), by_code=False)
        if found is None:
            # Parent deletion cascades the row; no retained credential can prove ordinary expiry.
            raise InvalidDelegationError(DelegationRefusal.PARENT_INVALID)
        delegation, parent, user = found
        _require_parent(user, parent, tenant_id, region)
        if delegation.consumer_id != consumer_id:
            raise InvalidDelegationError(DelegationRefusal.PARENT_INVALID)
        expires_at = min(as_utc(delegation.token_expires_at), as_utc(parent.expires_at)) - timedelta(
            seconds=clock_skew_seconds
        )
        if expires_at <= utc_now():
            raise InvalidDelegationError(DelegationRefusal.EXPIRED)
        return DelegatedIdentity(tenant_id, region, user.id, expires_at)


def require_consumer_policy(db: Session, consumer: BackendConsumer) -> None:
    with delegation_storage_errors():
        try:
            require_current_policy(db, consumer)
        except BackendPolicyConflict:
            raise DelegationUnavailableError() from None
