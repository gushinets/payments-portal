"""Accepted subscription inputs for allowance/schema checks; no paid writer."""

from dataclasses import dataclass
from datetime import timedelta
import hashlib
from uuid import UUID, uuid4

from app.core.time import utc_now
from app.models import AuthSession, User

from app.domains.purchases.contracts import AcceptedPurchase


@dataclass(frozen=True)
class AcceptedSubscription:
    subscription_id: UUID
    user_id: UUID
    accepted: AcceptedPurchase


def reader_identity(
    token: str, *, verified: bool = True, tenant: str = "anytoolai", region: str = "ru"
) -> tuple[User, AuthSession]:
    identity = uuid4()
    user = User(
        id=identity,
        tenant_id=tenant,
        region=region,
        email=f"{identity}@example.test",
        email_normalized=f"{identity}@example.test",
        email_verified_at=utc_now() if verified else None,
    )
    session = AuthSession(
        user_id=identity,
        tenant_id=tenant,
        region=region,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=utc_now() + timedelta(days=1),
    )
    return user, session
